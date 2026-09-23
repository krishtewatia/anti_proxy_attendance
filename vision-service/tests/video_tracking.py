"""Video Tracking Test (Step 4.10.3).

Pipeline:
  Video (e.g. person_1_vid.mp4, person_2_vid.mp4)
      ↓
  OpenCV @ 5 FPS sampling
      ↓
  InsightFace face detection (bounding box + det_score)
      ↓
  ByteTrack (Kalman motion model + two-stage IoU association)
      ↓
  Track IDs & track continuity analysis

Note: Recognition (ArcFace embeddings) is NOT evaluated in this step.
This test benchmarks pure face tracking stability.
"""

from collections import defaultdict
from pathlib import Path
import sys
import time

import cv2
import numpy as np
from insightface.app import FaceAnalysis

# Add vision-service root to Python path so tracking package can be imported
SCRIPT_DIR = Path(__file__).resolve().parent
SERVICE_ROOT = SCRIPT_DIR.parent
PROJECT_ROOT = SERVICE_ROOT.parent

if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from tracking.bytetrack import BYTETracker


# ============================================================
# CONFIGURATION
# ============================================================

VIDEO_DIR = SERVICE_ROOT / "tests" / "video_test"
TARGET_FPS = 5.0

# Tracker tuning for 5 FPS face tracking
TRACK_THRESH = 0.40   # High-confidence detection threshold
MATCH_THRESH = 0.80   # Gating IoU distance (1 - IoU)
TRACK_BUFFER = 20     # Max lost frames before track deletion (allows ~4s gap at 5 FPS)
FRAME_RATE = 30       # Base rate for track buffer scaling


# ============================================================
# VIDEO TRACKING LOGIC
# ============================================================

def process_video_tracking(video_path: Path, app: FaceAnalysis):
    """Run face detection and ByteTrack across sampled video frames."""
    print("\n" + "=" * 70)
    print(f"TRACKING BENCHMARK: {video_path.name}")
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
    frames_with_tracks = 0

    # Initialize a fresh ByteTrack instance for each video
    tracker = BYTETracker(
        track_thresh=TRACK_THRESH,
        match_thresh=MATCH_THRESH,
        track_buffer=TRACK_BUFFER,
        frame_rate=FRAME_RATE,
    )

    # Track metrics: track_id -> list of frame indices where it appeared
    track_history = defaultdict(list)
    track_scores = defaultdict(list)

    start_time = time.perf_counter()

    while True:
        success, frame = cap.read()
        if not success:
            break

        current_time = frame_number / source_fps

        # Frame sampling control
        if current_time + 1e-9 < next_sample_time:
            frame_number += 1
            continue

        sampled_frames += 1

        # 1. InsightFace face detection
        faces = app.get(frame)

        if faces:
            frames_with_faces += 1
            # Prepare detections array: [x1, y1, x2, y2, det_score]
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

        active_track_ids = [t.track_id for t in online_tracks]

        if active_track_ids:
            frames_with_tracks += 1
            for t in online_tracks:
                track_history[t.track_id].append(frame_number)
                track_scores[t.track_id].append(t.score)

        # 3. Formatted frame output
        det_scores_str = (
            ", ".join(f"{f.det_score:.2f}" for f in faces) if faces else "none"
        )
        tracks_str = str(active_track_ids) if active_track_ids else "[]"

        print(
            f"Frame {frame_number:4d} | Time {current_time:5.2f}s | "
            f"Faces: {len(faces)} (scores: {det_scores_str}) | "
            f"Track IDs: {tracks_str}",
            flush=True,
        )

        next_sample_time += frame_interval
        frame_number += 1

    cap.release()

    elapsed = time.perf_counter() - start_time
    effective_fps = sampled_frames / elapsed if elapsed > 0 else 0.0

    # 4. Track statistics summary
    total_unique_tracks = len(track_history)

    print("\n" + "-" * 70)
    print("TRACKING METRICS & STABILITY")
    print("-" * 70)
    print(f"Total frames read       : {frame_number}")
    print(f"Frames sampled          : {sampled_frames}")
    print(f"Frames containing faces : {frames_with_faces}")
    print(f"Frames with active track: {frames_with_tracks}")
    print(f"Unique Track IDs created: {total_unique_tracks}")
    print(f"Processing time         : {elapsed:.2f}s ({effective_fps:.2f} FPS)")

    print("\nTrack Details:")
    if track_history:
        for tid, frames in sorted(track_history.items()):
            dur = len(frames)
            span = frames[-1] - frames[0]
            avg_score = np.mean(track_scores[tid]) if track_scores[tid] else 0.0
            print(
                f"  Track ID {tid:2d}: active in {dur} frames "
                f"(first: frame {frames[0]}, last: frame {frames[-1]}, span: {span} frames, "
                f"avg det_score: {avg_score:.2f})"
            )
    else:
        print("  No tracks were generated.")

    return {
        "video": video_path.name,
        "sampled_frames": sampled_frames,
        "frames_with_faces": frames_with_faces,
        "frames_with_tracks": frames_with_tracks,
        "unique_track_ids": total_unique_tracks,
        "track_history": track_history,
    }


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("STEP 4.10.3: VIDEO TRACKING BENCHMARK (BYTETRACK)")
    print("=" * 70)

    # Initialize InsightFace detector
    print("\nLoading InsightFace detector...")
    app = FaceAnalysis(
        name="buffalo_l",
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=0, det_size=(640, 640))
    print("InsightFace loaded successfully.")

    # Find test videos
    videos = sorted(VIDEO_DIR.glob("*.mp4"))
    if not videos:
        raise RuntimeError(f"No .mp4 videos found in {VIDEO_DIR}")

    print("\n" + "=" * 70)
    print(f"FOUND {len(videos)} TEST VIDEO(S)")
    print("=" * 70)

    results = []
    for video_path in videos:
        res = process_video_tracking(video_path, app)
        results.append(res)

    print("\n" + "=" * 70)
    print("STEP 4.10.3 COMPLETE: SUMMARY")
    print("=" * 70)
    print(f"{'Video':<20} | {'Sampled':<8} | {'Face Frames':<12} | {'Track Frames':<13} | {'Unique Tracks':<14}")
    print("-" * 75)
    for r in results:
        print(
            f"{r['video']:<20} | {r['sampled_frames']:<8} | "
            f"{r['frames_with_faces']:<12} | {r['frames_with_tracks']:<13} | "
            f"{r['unique_track_ids']:<14}"
        )
    print("=" * 70)


if __name__ == "__main__":
    main()
