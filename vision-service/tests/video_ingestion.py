"""Video Ingestion & Frame Sampling Test (Step 4.10.1).

Verifies that OpenCV can:
1. Open video files reliably.
2. Read frames sequentially without dropping or corrupting.
3. Extract metadata (FPS, resolution, total frame count, duration).
4. Sample frames at a controlled target rate (e.g., 5 FPS).
5. Save sampled frames to disk for visual verification.
"""

import argparse
from pathlib import Path
import cv2


def ingest_and_sample_video(
    video_path: Path,
    target_fps: float = 5.0,
    max_saved_frames: int = 5,
    output_dir: Path = None,
) -> dict:
    """Ingest a video, extract metadata, sequentially sample frames, and save a subset.

    Args:
        video_path: Path to the input video file.
        target_fps: Desired sampling rate in frames per second.
        max_saved_frames: Maximum number of sampled frames to save to disk.
        output_dir: Directory where sample images will be stored.

    Returns:
        Dictionary containing video metadata and ingestion statistics.
    """
    video_path = Path(video_path).resolve()
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video file: {video_path}")

    # 1. Retrieve metadata
    source_fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / source_fps if source_fps > 0 else 0.0

    print("=" * 65)
    print(f"INGESTING: {video_path.name}")
    print("=" * 65)
    print(f"  Resolution      : {width} x {height}")
    print(f"  Source FPS      : {source_fps:.2f}")
    print(f"  Total Frames    : {total_frames}")
    print(f"  Duration        : {duration_sec:.2f} seconds")
    print(f"  Target Sampling : {target_fps:.1f} FPS")

    # Determine frame step interval for target sampling rate
    # If source is ~29.8 FPS and target is 5 FPS, step is ~5.96 frames
    step_interval = source_fps / target_fps if target_fps > 0 and source_fps > 0 else 1.0

    if output_dir is not None:
        video_output_dir = output_dir / video_path.stem
        video_output_dir.mkdir(parents=True, exist_ok=True)
    else:
        video_output_dir = None

    read_count = 0
    sampled_count = 0
    saved_frames = []
    next_sample_frame = 0.0

    # 2. Sequential frame reading & controlled sampling
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Check if current frame index matches or passes the next sampling point
        if read_count >= int(round(next_sample_frame)):
            sampled_count += 1
            timestamp_sec = read_count / source_fps if source_fps > 0 else 0.0

            # Save first N sampled frames for visual verification
            if video_output_dir is not None and len(saved_frames) < max_saved_frames:
                frame_filename = f"sample_{sampled_count:03d}_frame_{read_count:04d}_ts_{timestamp_sec:.2f}s.jpg"
                save_path = video_output_dir / frame_filename
                cv2.imwrite(str(save_path), frame)
                saved_frames.append(save_path)

            next_sample_frame += step_interval

        read_count += 1

    cap.release()

    effective_sampled_fps = sampled_count / duration_sec if duration_sec > 0 else 0.0

    print(f"  Frames Read     : {read_count} / {total_frames}")
    print(f"  Frames Sampled  : {sampled_count} (~{effective_sampled_fps:.2f} FPS)")
    print(f"  Saved for Review: {len(saved_frames)} frames")
    if saved_frames:
        for p in saved_frames:
            print(f"    -> {p.relative_to(video_path.parent.parent.parent) if video_path.parent.parent.parent in p.parents else p}")

    return {
        "video": video_path.name,
        "width": width,
        "height": height,
        "source_fps": source_fps,
        "total_frames": total_frames,
        "read_count": read_count,
        "duration_sec": duration_sec,
        "sampled_count": sampled_count,
        "effective_sampled_fps": effective_sampled_fps,
        "saved_frames": saved_frames,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Step 4.10.1: Video Ingestion and Frame Sampling Test"
    )
    parser.add_argument(
        "--target-fps",
        type=float,
        default=5.0,
        help="Target sampling rate in FPS (default: 5.0)",
    )
    parser.add_argument(
        "--max-save",
        type=int,
        default=5,
        help="Number of sampled frames to save per video (default: 5)",
    )
    args = parser.parse_args()

    tests_dir = Path(__file__).resolve().parent
    video_dir = tests_dir / "video_test"
    output_dir = tests_dir / "video_test" / "sampled_frames"

    video_files = sorted(
        path
        for path in video_dir.iterdir()
        if path.suffix.lower() in {".mp4", ".avi", ".mov", ".mkv"}
    )

    if not video_files:
        raise RuntimeError(f"No video files found in {video_dir}")

    print("=================================================================")
    print("STEP 4.10.1: VIDEO INGESTION & FRAME SAMPLING VERIFICATION")
    print("=================================================================")
    print(f"Found {len(video_files)} video(s) in {video_dir.name}/")

    results = []
    for video_file in video_files:
        stats = ingest_and_sample_video(
            video_file,
            target_fps=args.target_fps,
            max_saved_frames=args.max_save,
            output_dir=output_dir,
        )
        results.append(stats)

    print("\n" + "=" * 65)
    print("INGESTION SUMMARY TABLE")
    print("=" * 65)
    print(f"{'Video':<18} | {'Resolution':<11} | {'Src FPS':<8} | {'Duration':<9} | {'Sampled':<8} | {'Rate':<8}")
    print("-" * 65)
    for r in results:
        res_str = f"{r['width']}x{r['height']}"
        dur_str = f"{r['duration_sec']:.2f}s"
        rate_str = f"{r['effective_sampled_fps']:.1f} FPS"
        print(
            f"{r['video']:<18} | {res_str:<11} | {r['source_fps']:<8.2f} | {dur_str:<9} | {r['sampled_count']:<8} | {rate_str:<8}"
        )
    print("=" * 65)
    print(f"All {len(results)} videos successfully ingested and sampled.")


if __name__ == "__main__":
    main()
