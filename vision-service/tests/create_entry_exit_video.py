"""Create controlled ENTRY -> DWELL -> EXIT test video from existing footage.

Composition:
1. Forward sequence (Frames 0 to N-1): ENTRY from SIDE_A to SIDE_B
2. Dwell sequence (hold inside SIDE_B for DWELL_FRAMES)
3. Reverse sequence (Frames N-1 down to 0): EXIT from SIDE_B to SIDE_A
"""

import os
from pathlib import Path
import cv2
import numpy as np

VIDEO_DIR = Path(os.environ.get("VISION_FIXTURES_DIR") or "vision-fixtures-not-configured") / "video_test"
INPUT_PATH = VIDEO_DIR / "multi_person_simultaneous.mp4"
OUTPUT_PATH = VIDEO_DIR / "entry_exit_simultaneous.mp4"

DWELL_SECONDS = 1.0


def create_entry_exit_video():
    cap = cv2.VideoCapture(str(INPUT_PATH))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open input video: {INPUT_PATH}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"Reading {total_frames} frames from {INPUT_PATH.name} ({w}x{h} @ {fps:.2f} fps)...")

    frames = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    cap.release()

    dwell_frames = int(round(fps * DWELL_SECONDS))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(OUTPUT_PATH), fourcc, fps, (w, h))

    # Phase 1: Forward (ENTRY)
    print(f"Writing Phase 1: Forward (ENTRY) - {len(frames)} frames...")
    for frame in frames:
        out.write(frame)

    # Phase 2: Dwell inside SIDE_B
    print(f"Writing Phase 2: Dwell inside SIDE_B - {dwell_frames} frames...")
    last_frame = frames[-1]
    for _ in range(dwell_frames):
        out.write(last_frame)

    # Phase 3: Reverse (EXIT)
    print(f"Writing Phase 3: Reverse (EXIT) - {len(frames)} frames...")
    for frame in reversed(frames):
        out.write(frame)

    out.release()

    total_out_frames = len(frames) * 2 + dwell_frames
    duration_s = total_out_frames / fps
    print(f"Generated {OUTPUT_PATH.name}:")
    print(f"  Total frames: {total_out_frames} ({duration_s:.2f}s)")
    print(f"  Resolution  : {w}x{h}")
    print(f"  FPS         : {fps:.2f}")


if __name__ == "__main__":
    create_entry_exit_video()
