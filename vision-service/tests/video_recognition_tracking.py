"""Video Recognition + Tracking Fusion Test (Step 4.10.4).

Pipeline:
                    ┌── InsightFace (Detection + ArcFace Embedding)
  Video @ 5 FPS ───┤
                    └── ByteTrack (Kalman Motion Model + Association)
                              │
                              ▼
                         Track ID
                              │
                              ▼
                     Per-Frame Embeddings
                              │
                              ▼
                    Track Evidence Buffer
                              │
                              ▼
         Track-Level Aggregation & Decision Analysis
         - Best Similarity
         - Mean Similarity
         - Supporting Frames Count
         - Identity Consistency %
         - Fusion Candidate Identity
"""

from collections import defaultdict
from pathlib import Path
import sys
import time

import cv2
import numpy as np
from insightface.app import FaceAnalysis

# Add vision-service root to Python path
SCRIPT_DIR = Path(__file__).resolve().parent
SERVICE_ROOT = SCRIPT_DIR.parent
PROJECT_ROOT = SERVICE_ROOT.parent

if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from tracking.bytetrack import BYTETracker, box_iou


# ============================================================
# CONFIGURATION
# ============================================================

VIDEO_DIR = SERVICE_ROOT / "tests" / "video_test"
ENROLLMENT_DIR = SERVICE_ROOT / "tests" / "recognition_benchmark"
if not ENROLLMENT_DIR.exists():
    ENROLLMENT_DIR = SERVICE_ROOT / "tests" / "face_images"

TARGET_FPS = 5.0

# Tracking parameters (consistent with Step 4.10.3)
TRACK_THRESH = 0.40
MATCH_THRESH = 0.80
TRACK_BUFFER = 20
FRAME_RATE = 30


# ============================================================
# GALLERY & SIMILARITY HELPERS
# ============================================================

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Calculate cosine similarity between two embeddings."""
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def load_enrollment_gallery(app: FaceAnalysis) -> dict:
    """Load enrolled images and compute averaged 512-d embeddings per person."""
    gallery = {}
    if not ENROLLMENT_DIR.exists():
        raise FileNotFoundError(f"Enrollment directory not found: {ENROLLMENT_DIR}")

    person_dirs = sorted(p for p in ENROLLMENT_DIR.iterdir() if p.is_dir())
    if not person_dirs:
        raise RuntimeError(f"No identity directories found in {ENROLLMENT_DIR}")

    print("\n" + "=" * 70)
    print("LOADING ENROLLMENT GALLERY")
    print("=" * 70)

    for person_dir in person_dirs:
        embeddings = []
        image_files = sorted(
            p for p in person_dir.iterdir()
            if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )

        for img_path in image_files:
            img = cv2.imread(str(img_path))
            if img is None:
                continue
            faces = app.get(img)
            if not faces:
                continue

            # Select largest face
            face = max(
                faces,
                key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
            )
            emb = face.embedding.astype(np.float32)
            emb /= np.linalg.norm(emb)
            embeddings.append(emb)

        if embeddings:
            mean_emb = np.mean(embeddings, axis=0)
            mean_emb /= np.linalg.norm(mean_emb)
            gallery[person_dir.name] = mean_emb
            print(f"  {person_dir.name}: {len(embeddings)} image(s) enrolled")

    print(f"Gallery ready with {len(gallery)} identities.")
    return gallery


def match_embedding_to_gallery(embedding: np.ndarray, gallery: dict) -> Tuple[str, float, dict]:
    """Compare embedding against all gallery identities.

    Returns:
        (best_identity, best_score, all_scores_dict)
    """
    embedding = embedding.astype(np.float32)
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding /= norm

    scores = {}
    for person_name, enrolled_emb in gallery.items():
        scores[person_name] = cosine_similarity(embedding, enrolled_emb)

    best_identity = max(scores, key=scores.get)
    best_score = scores[best_identity]
    return best_identity, best_score, scores


# ============================================================
# FUSION PIPELINE
# ============================================================

def process_video_fusion(video_path: Path, app: FaceAnalysis, gallery: dict):
    print("\n" + "=" * 70)
    print(f"RECOGNITION + TRACKING FUSION: {video_path.name}")
    print("=" * 70)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    source_fps = cap.get(cv2.CAP_PROP_FPS)
    if source_fps <= 0:
        raise RuntimeError(f"Invalid source FPS for {video_path}")

    frame_interval = 1.0 / TARGET_FPS
    next_sample_time = 0.0

    frame_number = 0
    sampled_frames = 0
    frames_with_faces = 0

    tracker = BYTETracker(
        track_thresh=TRACK_THRESH,
        match_thresh=MATCH_THRESH,
        track_buffer=TRACK_BUFFER,
        frame_rate=FRAME_RATE,
    )

    # Track evidence structure:
    # track_id -> {
    #     "observations": [ { "frame", "time", "identity", "score", "all_scores", "bbox" } ],
    #     "identity_scores": defaultdict(list)
    # }
    track_evidence = defaultdict(lambda: {
        "observations": [],
        "identity_scores": defaultdict(list),
    })

    start_time = time.perf_counter()

    while True:
        success, frame = cap.read()
        if not success:
            break

        current_time = frame_number / source_fps

        if current_time + 1e-9 < next_sample_time:
            frame_number += 1
            continue

        sampled_frames += 1

        # 1. InsightFace detection + embedding extraction
        faces = app.get(frame)

        if faces:
            frames_with_faces += 1
            detections = np.array(
                [
                    [
                        face.bbox[0],
                        face.bbox[1],
                        face.bbox[2],
                        face.bbox[3],
                        getattr(face, "det_score", 0.90),
                    ]
                    for face in faces
                ],
                dtype=np.float32,
            )
        else:
            detections = np.empty((0, 5), dtype=np.float32)

        # 2. ByteTrack update
        online_tracks = tracker.update(detections)

        # 3. Associate active tracks with detected faces via IoU
        frame_track_info = []

        if online_tracks and len(faces) > 0:
            track_boxes = np.array([t.tlbr for t in online_tracks], dtype=np.float32)
            face_boxes = np.array([f.bbox for f in faces], dtype=np.float32)

            ious = box_iou(track_boxes, face_boxes)

            for t_idx, track in enumerate(online_tracks):
                best_face_idx = int(np.argmax(ious[t_idx]))
                best_iou = ious[t_idx, best_face_idx]

                if best_iou > 0.30:  # Valid association
                    matched_face = faces[best_face_idx]
                    top_id, top_score, all_scores = match_embedding_to_gallery(
                        matched_face.embedding, gallery
                    )

                    evidence = track_evidence[track.track_id]
                    evidence["observations"].append({
                        "frame": frame_number,
                        "timestamp": current_time,
                        "identity": top_id,
                        "similarity": top_score,
                        "all_scores": all_scores,
                        "det_score": getattr(matched_face, "det_score", 0.0),
                        "bbox": matched_face.bbox.tolist(),
                    })

                    for pid, sc in all_scores.items():
                        evidence["identity_scores"][pid].append(sc)

                    frame_track_info.append(
                        f"Track {track.track_id:2d} -> {top_id} ({top_score:.3f})"
                    )

        # Print per-frame status
        tracks_str = " | ".join(frame_track_info) if frame_track_info else "No active tracks"
        print(
            f"Frame {frame_number:4d} | Time {current_time:5.2f}s | Faces: {len(faces)} | {tracks_str}",
            flush=True,
        )

        next_sample_time += frame_interval
        frame_number += 1

    cap.release()

    elapsed = time.perf_counter() - start_time
    effective_fps = sampled_frames / elapsed if elapsed > 0 else 0.0

    # ============================================================
    # 4. TRACK-LEVEL EVIDENCE AGGREGATION & REPORTING
    # ============================================================

    print("\n" + "=" * 70)
    print(f"TRACK EVIDENCE REPORT: {video_path.name}")
    print("=" * 70)

    track_summaries = []

    for tid, evidence in sorted(track_evidence.items()):
        obs = evidence["observations"]
        if not obs:
            continue

        print(f"\n--- Track {tid} ---")
        for o in obs:
            print(
                f"  Frame {o['frame']:4d} ({o['timestamp']:5.2f}s): "
                f"{o['identity']} (sim: {o['similarity']:.3f}, det: {o['det_score']:.2f})"
            )

        # Calculate votes and mean similarities per identity across the track
        ident_counts = defaultdict(int)
        for o in obs:
            ident_counts[o["identity"]] += 1

        top_ident = max(ident_counts, key=ident_counts.get)
        supporting_frames = ident_counts[top_ident]
        total_obs = len(obs)
        consistency_pct = (supporting_frames / total_obs) * 100.0

        scores_for_top = [o["similarity"] for o in obs if o["identity"] == top_ident]
        best_sim = max(scores_for_top)
        mean_sim = float(np.mean(scores_for_top))

        # Runner up analysis
        other_scores = {
            pid: float(np.mean(sc_list))
            for pid, sc_list in evidence["identity_scores"].items()
            if pid != top_ident
        }
        runner_up = max(other_scores, key=other_scores.get) if other_scores else "None"
        runner_up_mean = other_scores.get(runner_up, 0.0)
        margin = mean_sim - runner_up_mean

        start_f = obs[0]["frame"]
        end_f = obs[-1]["frame"]
        track_dur = obs[-1]["timestamp"] - obs[0]["timestamp"]

        print(f"  Summary:")
        print(f"    Top Candidate Identity : {top_ident}")
        print(f"    Best Frame Similarity  : {best_sim:.3f} (Frame {max(obs, key=lambda x: x['similarity'])['frame']})")
        print(f"    Mean Similarity        : {mean_sim:.3f}")
        print(f"    Supporting Frames      : {supporting_frames} / {total_obs} ({consistency_pct:.1f}% consistency)")
        print(f"    Runner-up Identity     : {runner_up} (mean: {runner_up_mean:.3f})")
        print(f"    Separation Margin      : {margin:+.3f}")
        print(f"    Track Span             : {start_f} -> {end_f} ({track_dur:.2f}s, {total_obs} frames)")

        track_summaries.append({
            "track_id": tid,
            "top_identity": top_ident,
            "best_sim": best_sim,
            "mean_sim": mean_sim,
            "supporting_frames": supporting_frames,
            "total_frames": total_obs,
            "consistency": consistency_pct,
            "margin": margin,
            "track_duration": track_dur,
        })

    print("\n" + "-" * 70)
    print(f"PROCESSING STATS: {video_path.name}")
    print(f"  Total frames read: {frame_number}, Sampled: {sampled_frames}")
    print(f"  Processing time  : {elapsed:.2f}s ({effective_fps:.2f} FPS)")
    print("-" * 70)

    return track_summaries


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("STEP 4.10.4: RECOGNITION + TRACKING FUSION")
    print("=" * 70)

    # 1. Initialize InsightFace
    print("\nLoading InsightFace...")
    app = FaceAnalysis(
        name="buffalo_l",
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=0, det_size=(640, 640))
    print("InsightFace loaded successfully.")

    # 2. Load Gallery
    gallery = load_enrollment_gallery(app)

    # 3. Locate Videos
    videos = sorted(VIDEO_DIR.glob("*.mp4"))
    if not videos:
        raise RuntimeError(f"No .mp4 videos found in {VIDEO_DIR}")

    print("\n" + "=" * 70)
    print(f"FOUND {len(videos)} TEST VIDEO(S)")
    print("=" * 70)

    all_video_summaries = {}
    for video_path in videos:
        summaries = process_video_fusion(video_path, app, gallery)
        all_video_summaries[video_path.name] = summaries

    # 4. Final Fusion Summary Table
    print("\n" + "=" * 75)
    print("STEP 4.10.4 FINAL SUMMARY: TRACK-LEVEL RECOGNITION EVIDENCE")
    print("=" * 75)
    print(f"{'Video':<18} | {'Track':<5} | {'Candidate':<10} | {'Best':<6} | {'Mean':<6} | {'Support':<8} | {'Margin':<7}")
    print("-" * 75)
    for vname, summaries in all_video_summaries.items():
        if not summaries:
            print(f"{vname:<18} | None  | No tracks accumulated evidence")
            continue
        for s in summaries:
            sup_str = f"{s['supporting_frames']}/{s['total_frames']} ({s['consistency']:.0f}%)"
            print(
                f"{vname:<18} | "
                f"T{s['track_id']:<4} | "
                f"{s['top_identity']:<10} | "
                f"{s['best_sim']:<6.3f} | "
                f"{s['mean_sim']:<6.3f} | "
                f"{sup_str:<8} | "
                f"{s['margin']:<+7.3f}"
            )
    print("=" * 75)
    print("Step 4.10.4 Complete.")


if __name__ == "__main__":
    main()
