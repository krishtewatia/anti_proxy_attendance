"""Create Multi-Person Simultaneous Crossing Video.

Composites `person_1_vid.mp4` and `person_2_vid.mp4` side-by-side (1152x1024)
with temporal alignment so both subjects approach and cross the virtual boundary
simultaneously in parallel lanes.
"""

from pathlib import Path
import cv2
import numpy as np

VIDEO_DIR = Path(__file__).resolve().parent / "video_test"
V1_PATH = VIDEO_DIR / "person_1_vid.mp4"
V2_PATH = VIDEO_DIR / "person_2_vid.mp4"
OUTPUT_PATH = VIDEO_DIR / "multi_person_simultaneous.mp4"

# Alignment offset: Video 2 crossing is ~120 frames after Video 1 crossing.
# By advancing Video 2 by 120 frames, both crossings align around frame 108.
V2_OFFSET_FRAMES = 120


def compose_videos():
    cap1 = cv2.VideoCapture(str(V1_PATH))
    cap2 = cv2.VideoCapture(str(V2_PATH))

    fps1 = cap1.get(cv2.CAP_PROP_FPS)
    w1, h1 = int(cap1.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap1.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames_1 = int(cap1.get(cv2.CAP_PROP_FRAME_COUNT))

    w2, h2 = int(cap2.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap2.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames_2 = int(cap2.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"Video 1: {w1}x{h1}, {total_frames_1} frames @ {fps1:.2f} fps")
    print(f"Video 2: {w2}x{h2}, {total_frames_2} frames @ {fps1:.2f} fps")

    # Fast-forward Video 2 by V2_OFFSET_FRAMES
    cap2.set(cv2.CAP_PROP_POS_FRAMES, V2_OFFSET_FRAMES)

    out_width = w1 + w2  # 1152
    out_height = max(h1, h2)  # 1024

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(OUTPUT_PATH), fourcc, fps1, (out_width, out_height))

    frame_idx = 0
    while True:
        ret1, frame1 = cap1.read()
        ret2, frame2 = cap2.read()

        if not ret1 and not ret2:
            break

        # Fallback to black if one video ends before the other
        if not ret1:
            frame1 = np.zeros((h1, w1, 3), dtype=np.uint8)
        if not ret2:
            frame2 = np.zeros((h2, w2, 3), dtype=np.uint8)

        # Composite side-by-side
        canvas = np.zeros((out_height, out_width, 3), dtype=np.uint8)
        canvas[:h1, :w1] = frame1
        canvas[:h2, w1 : w1 + w2] = frame2

        out.write(canvas)
        frame_idx += 1

    cap1.release()
    cap2.release()
    out.release()

    print(f"Successfully generated composite video: {OUTPUT_PATH}")
    print(f"Total Frames: {frame_idx}, Resolution: {out_width}x{out_height}, FPS: {fps1:.2f}")


if __name__ == "__main__":
    compose_videos()
