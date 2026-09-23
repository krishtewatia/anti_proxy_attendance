"""Video Direction & ENTRY/EXIT Boundary Logic Test (Step 4.10.5).

Pipeline:
  Video @ 5 FPS
      ↓
  InsightFace (Face detection)
      ↓
  ByteTrack (Track ID + trajectory center positions)
      ↓
  Virtual Boundary Line & Signed Distance Geometry
      ↓
  Direction & Line-Crossing State Machine:
      SIDE_A  ───(cross line)───►  SIDE_B   ==>  ENTRY
      SIDE_B  ───(cross line)───►  SIDE_A   ==>  EXIT
      (No crossing / insufficient motion)   ==>  UNRESOLVED

Note: Attendance database, business logic, and API calls are decoupled.
This test benchmarks pure spatial boundary crossing and directionality.
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

VIDEO_DIR = SERVICE_ROOT / "tests" / "video_test"
TARGET_FPS = 5.0

# Tracking parameters (consistent with Step 4.10.3 / 4.10.4)
TRACK_THRESH = 0.40
MATCH_THRESH = 0.80
TRACK_BUFFER = 20
FRAME_RATE = 30

# Virtual Boundary Line Definitions (Y-coordinate across frame width)
# Resolution: 576 x 1024
# Video 1 face Y spans ~570 -> 603 (Line at Y=585 captures crossing)
# Video 2 face Y spans ~603 -> 723 (Line at Y=650 captures crossing)
BOUNDARY_LINES = {
    "person_1_vid.mp4": 585,
    "person_2_vid.mp4": 650,
}
DEFAULT_LINE_Y = 600

# Hysteresis deadband in pixels around the line to prevent noise oscillation
DEADBAND_PIXELS = 4.0


# ============================================================
# DIRECTION & BOUNDARY LOGIC
# ============================================================

class BoundarySide(Enum):
    SIDE_A = "A"        # Above boundary line (outside / approach zone)
    SIDE_B = "B"        # Below boundary line (inside / entered zone)
    CROSSING = "ON_LINE"  # Inside deadband


class MovementEvent(Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    UNRESOLVED = "UNRESOLVED"


class TrackBoundaryState:
    """Maintains trajectory and boundary crossing state for a single track."""

    def __init__(self, track_id: int, line_y: float):
        self.track_id = track_id
        self.line_y = line_y
        self.positions = []       # [(frame, time, cx, cy, side)]
        self.initial_side = None
        self.current_side = None
        self.crossed = False
        self.event = MovementEvent.UNRESOLVED

    def update_position(self, frame_num: int, timestamp: float, cx: float, cy: float) -> tuple:
        """Update track position and evaluate line relative position.

        Returns:
            (side, new_event_or_None)
        """
        # Signed distance relative to horizontal line: cy - line_y
        signed_dist = cy - self.line_y

        if signed_dist < -DEADBAND_PIXELS:
            side = BoundarySide.SIDE_A
        elif signed_dist > DEADBAND_PIXELS:
            side = BoundarySide.SIDE_B
        else:
            side = BoundarySide.CROSSING

        if self.initial_side is None and side != BoundarySide.CROSSING:
            self.initial_side = side

        self.current_side = side
        self.positions.append((frame_num, timestamp, cx, cy, side))

        emitted_event = None

        # Check for state transition
        if not self.crossed and self.initial_side is not None:
            if self.initial_side == BoundarySide.SIDE_A and side == BoundarySide.SIDE_B:
                self.crossed = True
                self.event = MovementEvent.ENTRY
                emitted_event = MovementEvent.ENTRY
            elif self.initial_side == BoundarySide.SIDE_B and side == BoundarySide.SIDE_A:
                self.crossed = True
                self.event = MovementEvent.EXIT
                emitted_event = MovementEvent.EXIT

        return side, emitted_event


# ============================================================
# VIDEO PROCESSING
# ============================================================

def process_video_direction(video_path: Path, app: FaceAnalysis):
    line_y = BOUNDARY_LINES.get(video_path.name, DEFAULT_LINE_Y)

    print("\n" + "=" * 70)
    print(f"BOUNDARY CROSSING BENCHMARK: {video_path.name}")
    print("=" * 70)
    print(f"  Virtual Boundary Line : Horizontal line at Y = {line_y:.1f}px")
    print(f"  Side A (Approach)     : Y < {line_y - DEADBAND_PIXELS:.1f}px (Above line)")
    print(f"  Side B (Inside)       : Y > {line_y + DEADBAND_PIXELS:.1f}px (Below line)")
    print(f"  Crossing Deadband     : ±{DEADBAND_PIXELS}px")

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

    tracker = BYTETracker(
        track_thresh=TRACK_THRESH,
        match_thresh=MATCH_THRESH,
        track_buffer=TRACK_BUFFER,
        frame_rate=FRAME_RATE,
    )

    track_states = {}
    emitted_events = []

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

        # 1. Detect faces
        faces = app.get(frame)
        if faces:
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

        # 2. Update tracker
        online_tracks = tracker.update(detections)

        # 3. Associate tracks with positions & line boundary logic
        frame_logs = []

        if online_tracks and len(faces) > 0:
            track_boxes = np.array([t.tlbr for t in online_tracks], dtype=np.float32)
            face_boxes = np.array([f.bbox for f in faces], dtype=np.float32)
            ious = box_iou(track_boxes, face_boxes)

            for t_idx, track in enumerate(online_tracks):
                best_face_idx = int(np.argmax(ious[t_idx]))
                if ious[t_idx, best_face_idx] > 0.30:
                    cx = float((track.tlbr[0] + track.tlbr[2]) / 2.0)
                    cy = float((track.tlbr[1] + track.tlbr[3]) / 2.0)

                    if track.track_id not in track_states:
                        track_states[track.track_id] = TrackBoundaryState(
                            track.track_id, line_y
                        )

                    state = track_states[track.track_id]
                    side, event = state.update_position(
                        frame_number, current_time, cx, cy
                    )

                    frame_logs.append(
                        f"Track {track.track_id:2d} | position=({cx:5.1f}, {cy:5.1f}) | SIDE={side.value}"
                    )

                    if event:
                        emitted_events.append({
                            "track_id": track.track_id,
                            "event": event.value,
                            "frame": frame_number,
                            "time": current_time,
                            "pos": (cx, cy),
                        })
                        frame_logs.append(f"==> EVENT: {event.value} (Track {track.track_id})")

        log_str = " | ".join(frame_logs) if frame_logs else "No active tracks"
        print(
            f"Frame {frame_number:4d} | Time {current_time:5.2f}s | {log_str}",
            flush=True,
        )

        next_sample_time += frame_interval
        frame_number += 1

    cap.release()
    elapsed = time.perf_counter() - start_time

    # ============================================================
    # SUMMARY REPORT
    # ============================================================

    print("\n" + "-" * 70)
    print(f"BOUNDARY CROSSING SUMMARY: {video_path.name}")
    print("-" * 70)

    for tid, st in sorted(track_states.items()):
        if not st.positions:
            continue
        first_pos = st.positions[0]
        last_pos = st.positions[-1]
        delta_y = last_pos[3] - first_pos[3]
        motion_dir = "Downward (A -> B)" if delta_y > 0 else "Upward (B -> A)" if delta_y < 0 else "Stationary"

        print(f"Track {tid:2d}:")
        print(f"  First Seen : Frame {first_pos[0]} ({first_pos[1]:.2f}s) at ({first_pos[2]:.1f}, {first_pos[3]:.1f}) -> SIDE_{first_pos[4].value}")
        print(f"  Last Seen  : Frame {last_pos[0]} ({last_pos[1]:.2f}s) at ({last_pos[2]:.1f}, {last_pos[3]:.1f}) -> SIDE_{last_pos[4].value}")
        print(f"  Delta Y    : {delta_y:+.1f}px ({motion_dir})")
        print(f"  Result     : {st.event.value}")

    return {
        "video": video_path.name,
        "line_y": line_y,
        "tracks": track_states,
        "events": emitted_events,
    }


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("STEP 4.10.5: DIRECTIONALITY & ENTRY/EXIT BOUNDARY LOGIC")
    print("=" * 70)

    print("\nLoading InsightFace...")
    app = FaceAnalysis(
        name="buffalo_l",
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=0, det_size=(640, 640))
    print("InsightFace loaded successfully.")

    videos = sorted(VIDEO_DIR.glob("*.mp4"))
    if not videos:
        raise RuntimeError(f"No .mp4 videos found in {VIDEO_DIR}")

    print("\n" + "=" * 70)
    print(f"FOUND {len(videos)} TEST VIDEO(S)")
    print("=" * 70)

    all_results = []
    for video_path in videos:
        res = process_video_direction(video_path, app)
        all_results.append(res)

    print("\n" + "=" * 75)
    print("STEP 4.10.5 FINAL SUMMARY: MOVEMENT EVENTS")
    print("=" * 75)
    print(f"{'Video':<18} | {'Track':<6} | {'Start Side':<11} | {'End Side':<10} | {'Event':<10}")
    print("-" * 75)
    for r in all_results:
        for tid, st in sorted(r["tracks"].items()):
            if not st.positions:
                continue
            s_init = f"SIDE_{st.positions[0][4].value}"
            s_curr = f"SIDE_{st.positions[-1][4].value}"
            print(
                f"{r['video']:<18} | "
                f"T{tid:<5} | "
                f"{s_init:<11} | "
                f"{s_curr:<10} | "
                f"{st.event.value:<10}"
            )
    print("=" * 75)
    print("Step 4.10.5 Complete.")


if __name__ == "__main__":
    main()
