from pathlib import Path
import sys
import time

import cv2
import numpy as np

VISION_SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(VISION_SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(VISION_SERVICE_DIR))

from insightface.app import FaceAnalysis
from tracking.bytetrack import BYTETracker, box_iou
from live_cv_backend_demo import (
    load_gallery,
    recognize_face,
    classify_side,
    BOUNDARY_P1,
    BOUNDARY_P2,
    DEADBAND,
    TARGET_FPS,
)

VIDEO_PATH = VISION_SERVICE_DIR / "tests" / "video_test" / "entry_exit_simultaneous.mp4"


def main():
    print("Testing tracking and crossing on entry_exit_simultaneous.mp4...")
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))
    gallery = load_gallery(app)

    cap = cv2.VideoCapture(str(VIDEO_PATH))
    source_fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    tracker = BYTETracker(track_thresh=0.40, match_thresh=0.80, track_buffer=20, frame_rate=30)

    step_interval = source_fps / TARGET_FPS
    next_sample_frame = 0.0
    read_count = 0

    track_sides = {}  # track_id -> [sides]
    track_identities = {}  # track_id -> [identities]
    track_coords = {}  # track_id -> [(cx, cy)]

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if read_count >= int(round(next_sample_frame)):
            t_sec = read_count / source_fps
            faces = app.get(frame)
            dets = (
                np.array([[*f.bbox, f.det_score] for f in faces], dtype=np.float32)
                if faces
                else np.empty((0, 5), dtype=np.float32)
            )

            active_tracks = tracker.update(dets)

            if active_tracks and len(faces) > 0:
                tb = np.array([tr.tlbr for tr in active_tracks])
                fb = np.array([f.bbox for f in faces])
                ious = box_iou(tb, fb)

                for tr_idx, track in enumerate(active_tracks):
                    track_id = int(track.track_id)
                    best_f = np.argmax(ious[tr_idx])
                    if ious[tr_idx, best_f] < 0.3:
                        continue

                    face = faces[best_f]
                    cx = float((track.tlbr[0] + track.tlbr[2]) / 2.0)
                    cy = float((track.tlbr[1] + track.tlbr[3]) / 2.0)
                    side = classify_side(cx, cy)
                    ident, sim, _ = recognize_face(face.embedding, gallery)

                    if track_id not in track_sides:
                        track_sides[track_id] = []
                        track_identities[track_id] = []
                        track_coords[track_id] = []

                    track_sides[track_id].append((read_count, t_sec, side))
                    track_identities[track_id].append(ident)
                    track_coords[track_id].append((cx, cy))

            next_sample_frame += step_interval

        read_count += 1

    cap.release()

    print("\n" + "=" * 70)
    print("TRACK TRAJECTORY ANALYSIS ON ENTRY-EXIT VIDEO")
    print("=" * 70)
    for tid in sorted(track_sides.keys()):
        sides_seq = [s[2] for s in track_sides[tid]]
        idents = track_identities[tid]
        coords = track_coords[tid]
        first_t = track_sides[tid][0][1]
        last_t = track_sides[tid][-1][1]

        # Count identities
        id_counts = {}
        for i in idents:
            id_counts[i] = id_counts.get(i, 0) + 1
        best_id = max(id_counts, key=id_counts.get)

        print(f"Track {tid:2d}: {best_id} ({len(sides_seq)} frames, t={first_t:.2f}s -> {last_t:.2f}s)")
        print(f"  First pos: {coords[0]}, Side: {sides_seq[0]}")
        print(f"  Last pos : {coords[-1]}, Side: {sides_seq[-1]}")
        print(f"  Sides summary: start={sides_seq[0]} -> end={sides_seq[-1]}, unique={set(sides_seq)}")


if __name__ == "__main__":
    main()
