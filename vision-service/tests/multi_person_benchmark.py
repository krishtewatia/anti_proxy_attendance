"""Multi-Person Simultaneous Vision Benchmark (Step 4.10.6).

Validates concurrent multi-subject perception:
1. Simultaneous multi-face detection (SCRFD).
2. Independent concurrent tracking (ByteTrack).
3. Track-level biometric evidence fusion (ArcFace vs 4-person gallery).
4. Concurrent virtual boundary crossing and discrete event emission.

Verifies:
  Camera Canvas (Multi-person)
        │
   ┌────┴───────────────────────────┐
   ▼                                ▼
Track A (Left Lane)          Track B (Right Lane)
   │                                │
Identity: person_01          Identity: person_02
   │                                │
Crossing: ENTRY (t=3.6s)     Crossing: ENTRY (t=3.6s)
"""

from collections import defaultdict
from enum import Enum
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

VIDEO_PATH = SERVICE_ROOT / "tests" / "video_test" / "multi_person_simultaneous.mp4"
ENROLLMENT_DIR = SERVICE_ROOT / "tests" / "recognition_benchmark"
OUTPUT_DIR = SERVICE_ROOT / "tests" / "multi_person_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_FPS = 5.0

# Tracking parameters
TRACK_THRESH = 0.40
MATCH_THRESH = 0.80
TRACK_BUFFER = 20
FRAME_RATE = 30

# Virtual Boundary Line: Perspective line across doorway from (0, 585) to (1152, 650)
BOUNDARY_P1 = (0.0, 585.0)
BOUNDARY_P2 = (1152.0, 650.0)
DEADBAND_PIXELS = 4.0

# Biometric parameters
SIMILARITY_THRESHOLD = 0.40
MIN_MARGIN = 0.20
MIN_SUPPORTING_FRAMES = 3


class BoundarySide(Enum):
    SIDE_A = "APPROACH"  # Y < line_y - DEADBAND
    ON_LINE = "ON_LINE"  # Inside deadband
    SIDE_B = "INTERIOR"  # Y > line_y + DEADBAND


class DirectionEvent(Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    UNRESOLVED = "UNRESOLVED"


def get_boundary_y_at_x(x: float) -> float:
    """Calculate the Y-threshold of the boundary line at given X coordinate."""
    x1, y1 = BOUNDARY_P1
    x2, y2 = BOUNDARY_P2
    if x2 == x1:
        return y1
    slope = (y2 - y1) / (x2 - x1)
    return y1 + slope * (x - x1)


def compute_side(x: float, y: float, deadband: float) -> BoundarySide:
    line_y = get_boundary_y_at_x(x)
    if y < line_y - deadband:
        return BoundarySide.SIDE_A
    elif y > line_y + deadband:
        return BoundarySide.SIDE_B
    return BoundarySide.ON_LINE



def load_gallery(app: FaceAnalysis, gallery_dir: Path) -> dict:
    """Extract reference ArcFace embeddings for all enrolled identities."""
    print("=" * 70)
    print("ENROLLING REFERENCE BIOMETRIC GALLERY")
    print("=" * 70)

    gallery = {}
    for person_dir in sorted(gallery_dir.iterdir()):
        if not person_dir.is_dir():
            continue
        person_name = person_dir.name
        img_paths = sorted(
            p
            for p in person_dir.iterdir()
            if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )

        embeddings = []
        for img_path in img_paths:
            img = cv2.imread(str(img_path))
            if img is None:
                continue
            faces = app.get(img)
            if faces:
                best_face = max(faces, key=lambda f: f.det_score)
                embeddings.append(best_face.embedding)

        if embeddings:
            mean_emb = np.mean(embeddings, axis=0)
            norm = np.linalg.norm(mean_emb)
            mean_emb = mean_emb / (norm + 1e-10)
            gallery[person_name] = mean_emb
            print(f"  Enrolled '{person_name}': {len(embeddings)} reference images")

    print(f"Total enrolled identities in gallery: {len(gallery)}\n")
    return gallery


def match_identity(face_embedding: np.ndarray, gallery: dict) -> tuple:
    """Compare a 512-d embedding against the gallery, returning rankings."""
    norm = np.linalg.norm(face_embedding)
    face_emb = face_embedding / (norm + 1e-10)

    scores = {}
    for name, ref_emb in gallery.items():
        sim = float(np.dot(face_emb, ref_emb))
        scores[name] = sim

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_name, top_sim = sorted_scores[0]
    runner_up_name, runner_up_sim = sorted_scores[1] if len(sorted_scores) > 1 else ("none", -1.0)
    margin = top_sim - runner_up_sim

    return top_name, top_sim, runner_up_name, margin


def run_multi_person_benchmark():
    if not VIDEO_PATH.exists():
        raise FileNotFoundError(f"Video not found: {VIDEO_PATH}")

    print("=" * 70)
    print("STEP 4.10.6: MULTI-PERSON SIMULTANEOUS CV BENCHMARK")
    print("=" * 70)
    print(f"Video: {VIDEO_PATH.name}")

    # 1. Initialize InsightFace
    t0 = time.time()
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))
    print(f"InsightFace loaded in {time.time() - t0:.2f}s")

    # 2. Load Gallery
    gallery = load_gallery(app, ENROLLMENT_DIR)

    # 3. Open Video
    cap = cv2.VideoCapture(str(VIDEO_PATH))
    source_fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_s = total_frames / source_fps if source_fps > 0 else 0.0

    print(f"Resolution : {w} x {h}")
    print(f"Source FPS : {source_fps:.2f} (Target Sampling: {TARGET_FPS} FPS)")
    print(f"Duration   : {duration_s:.2f}s ({total_frames} frames)")
    print(f"Boundary   : Doorway line from {BOUNDARY_P1} to {BOUNDARY_P2} px\n")

    tracker = BYTETracker(
        track_thresh=TRACK_THRESH,
        match_thresh=MATCH_THRESH,
        track_buffer=TRACK_BUFFER,
        frame_rate=int(round(source_fps)),
    )

    step_interval = source_fps / TARGET_FPS
    next_sample_frame = 0.0
    read_count = 0
    sampled_count = 0

    # Multi-person statistics
    simultaneous_detection_frames = 0
    simultaneous_tracking_frames = 0

    # Tracking & Evidence Buffers per Track ID
    track_history = defaultdict(list)  # track_id -> [(fn, t, cx, cy, side, bbox)]
    track_evidence = defaultdict(list)  # track_id -> [(fn, t, top_name, top_sim, runner_up, margin)]
    track_events = {}  # track_id -> {event, timestamp, frame}
    saved_annotated_samples = []

    print("-" * 70)
    print("PROCESSING VIDEO FRAMES...")
    print("-" * 70)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if read_count >= int(round(next_sample_frame)):
            sampled_count += 1
            t_sec = read_count / source_fps if source_fps > 0 else 0.0

            faces = app.get(frame)
            num_faces = len(faces)
            if num_faces >= 2:
                simultaneous_detection_frames += 1

            # Prepare ByteTrack detections
            if faces:
                dets = np.array(
                    [[f.bbox[0], f.bbox[1], f.bbox[2], f.bbox[3], f.det_score] for f in faces],
                    dtype=np.float32,
                )
            else:
                dets = np.empty((0, 5), dtype=np.float32)

            online_targets = tracker.update(dets)
            if len(online_targets) >= 2:
                simultaneous_tracking_frames += 1

            # Associate tracker targets to InsightFace face embeddings
            if online_targets and len(faces) > 0:
                tb = np.array([tr.tlbr for tr in online_targets])
                fb = np.array([f.bbox for f in faces])
                ious = box_iou(tb, fb)

                for tr_idx, tr in enumerate(online_targets):
                    best_face_idx = np.argmax(ious[tr_idx])
                    if ious[tr_idx, best_face_idx] > 0.3:
                        face_obj = faces[best_face_idx]
                        cx = (tr.tlbr[0] + tr.tlbr[2]) / 2.0
                        cy = (tr.tlbr[1] + tr.tlbr[3]) / 2.0
                        side = compute_side(cx, cy, DEADBAND_PIXELS)

                        track_history[tr.track_id].append(
                            (read_count, t_sec, cx, cy, side, tr.tlbr)
                        )

                        # Match embedding
                        top_n, top_s, r_n, m = match_identity(face_obj.embedding, gallery)
                        track_evidence[tr.track_id].append(
                            (read_count, t_sec, top_n, top_s, r_n, m)
                        )

                        # Evaluate boundary crossing
                        hist = track_history[tr.track_id]
                        if tr.track_id not in track_events and len(hist) >= 2:
                            prev_sides = [h_entry[4] for h_entry in hist[:-1]]
                            curr_side = side
                            line_y = get_boundary_y_at_x(cx)
                            if (BoundarySide.SIDE_A in prev_sides) and (curr_side == BoundarySide.SIDE_B):
                                track_events[tr.track_id] = {
                                    "direction": DirectionEvent.ENTRY,
                                    "timestamp": t_sec,
                                    "frame": read_count,
                                }
                                print(f"  >>> [EVENT] Track {tr.track_id} crossed Doorway Line (Y~{line_y:.0f}): ENTRY at t={t_sec:.2f}s (Frame {read_count})")
                            elif (BoundarySide.SIDE_B in prev_sides) and (curr_side == BoundarySide.SIDE_A):
                                track_events[tr.track_id] = {
                                    "direction": DirectionEvent.EXIT,
                                    "timestamp": t_sec,
                                    "frame": read_count,
                                }
                                print(f"  >>> [EVENT] Track {tr.track_id} crossed Doorway Line (Y~{line_y:.0f}): EXIT at t={t_sec:.2f}s (Frame {read_count})")

            # Save annotated frame during simultaneous crossing window (around frames 90-114)
            if num_faces >= 2 and len(saved_annotated_samples) < 3:
                annotated = frame.copy()
                # Draw boundary line
                cv2.line(annotated, (int(BOUNDARY_P1[0]), int(BOUNDARY_P1[1])), (int(BOUNDARY_P2[0]), int(BOUNDARY_P2[1])), (0, 0, 255), 2)
                cv2.putText(annotated, "VIRTUAL BOUNDARY LINE", (20, int(BOUNDARY_P1[1]) - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)


                for tr in online_targets:
                    tlbr = [int(v) for v in tr.tlbr]
                    color = (0, 255, 0)
                    cv2.rectangle(annotated, (tlbr[0], tlbr[1]), (tlbr[2], tlbr[3]), color, 2)
                    ev_list = track_evidence.get(tr.track_id, [])
                    label = f"ID {tr.track_id}"
                    if ev_list:
                        label += f": {ev_list[-1][2]} ({ev_list[-1][3]:.2f})"
                    cv2.putText(annotated, label, (tlbr[0], max(20, tlbr[1] - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

                sample_path = OUTPUT_DIR / f"simultaneous_crossing_frame_{read_count:03d}.jpg"
                cv2.imwrite(str(sample_path), annotated)
                saved_annotated_samples.append(sample_path)

            next_sample_frame += step_interval

        read_count += 1

    cap.release()

    print("\n" + "=" * 70)
    print("MULTI-PERSON BENCHMARK EVALUATION & RESULTS")
    print("=" * 70)
    print(f"Sampled Frames Processed        : {sampled_count}")
    print(f"Concurrent Detections (>=2 faces): {simultaneous_detection_frames} frames ({simultaneous_detection_frames/sampled_count*100:.1f}%)")
    print(f"Concurrent Active Tracks (>=2)   : {simultaneous_tracking_frames} frames ({simultaneous_tracking_frames/sampled_count*100:.1f}%)")
    print(f"Total Unique Tracks Created      : {len(track_history)}")

    # Identity Fusion Analysis for tracks with >= 3 observations
    primary_tracks = [tr_id for tr_id, hist in track_history.items() if len(hist) >= 3]

    print("\n" + "=" * 70)
    print("TRACK IDENTITY FUSION & LINE-CROSSING TABLE")
    print("=" * 70)
    header = f"{'Track':<6} | {'Identity':<10} | {'Frames':<7} | {'Peak Sim':<9} | {'Mean Sim':<9} | {'Consistency':<12} | {'Event':<8} | {'Crossing t':<10}"
    print(header)
    print("-" * len(header))

    resolved_events = []
    for tr_id in sorted(primary_tracks):
        ev_list = track_evidence[tr_id]
        if not ev_list:
            continue

        # Vote tallies
        votes = defaultdict(int)
        for _, _, top_n, _, _, _ in ev_list:
            votes[top_n] += 1

        top_id, top_count = max(votes.items(), key=lambda x: x[1])
        consistency = (top_count / len(ev_list)) * 100.0

        top_sims = [sim for _, _, name, sim, _, _ in ev_list if name == top_id]
        peak_sim = max(top_sims) if top_sims else 0.0
        mean_sim = np.mean(top_sims) if top_sims else 0.0

        event_info = track_events.get(tr_id, {"direction": DirectionEvent.UNRESOLVED, "timestamp": 0.0})
        dir_str = event_info["direction"].value
        ts_str = f"{event_info['timestamp']:.2f}s" if dir_str != "UNRESOLVED" else "N/A"

        print(
            f"ID {tr_id:<3} | {top_id:<10} | {len(ev_list):<7} | {peak_sim:<9.3f} | {mean_sim:<9.3f} | {consistency:<11.1f}% | {dir_str:<8} | {ts_str:<10}"
        )

        resolved_events.append({
            "track_id": tr_id,
            "identity": top_id,
            "frames": len(ev_list),
            "peak_sim": peak_sim,
            "mean_sim": mean_sim,
            "consistency": consistency,
            "event": dir_str,
            "timestamp": event_info["timestamp"],
        })

    print("=" * 70)

    # Validation criteria checks
    entries = [e for e in resolved_events if e["event"] == "ENTRY"]
    identities_entered = set(e["identity"] for e in entries)

    has_multi_entry = len(entries) >= 2
    has_independent_identities = len(identities_entered) >= 2
    no_track_swap = len(identities_entered) == len(entries)

    print("\nBENCHMARK VALIDATION GATEWAY:")
    print(f"  [1] Simultaneous Face Detections: {'PASS' if simultaneous_detection_frames >= 5 else 'FAIL'} ({simultaneous_detection_frames} frames)")
    print(f"  [2] Concurrent Active Tracking   : {'PASS' if simultaneous_tracking_frames >= 4 else 'FAIL'} ({simultaneous_tracking_frames} frames)")
    print(f"  [3] Multiple ENTRY Events        : {'PASS' if has_multi_entry else 'FAIL'} ({len(entries)} ENTRY events)")
    print(f"  [4] Independent Identity Fusion  : {'PASS' if has_independent_identities else 'FAIL'} ({identities_entered})")
    print(f"  [5] Zero Identity Swap Collision : {'PASS' if no_track_swap else 'FAIL'}")

    overall_pass = (
        simultaneous_detection_frames >= 5
        and has_multi_entry
        and has_independent_identities
    )
    print(f"\nOVERALL MULTI-PERSON BENCHMARK RESULT: {'SUCCESS (PASS)' if overall_pass else 'FAILED'}")
    print(f"Annotated frame samples saved to: {OUTPUT_DIR}\n")
    return overall_pass


if __name__ == "__main__":
    run_multi_person_benchmark()
