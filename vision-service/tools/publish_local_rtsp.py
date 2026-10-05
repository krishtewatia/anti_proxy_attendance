"""Local CCTV / RTSP Stream Simulation Tool.

Provides local developers with a documented, license-compliant way to simulate
physical CCTV / IP camera streams looping video files without physical hardware.

Tool Options and Licenses:
1. MediaMTX (bluenviron/mediamtx):
   - License: MIT License (Permissive, commercial and development friendly).
   - Usage: Standalone lightweight binary or docker container.
2. FFmpeg RTSP Streamer:
   - License: LGPL v2.1+ / GPL v2+.
   - Usage: Publishes looping MP4 to MediaMTX via RTSP.
3. Built-in Local Simulation Mode:
   - Python-native OpenCV loopback for automated CI/CD without external servers.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

SERVICE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CLIP = SERVICE_ROOT / "tests" / "video_test" / "person_1_vid.mp4"


def print_setup_instructions() -> None:
    print("=" * 72)
    print("Anti-Proxy Attendance System: Local CCTV / RTSP Simulation Guide")
    print("=" * 72)
    print("\nOption 1: MediaMTX (Recommended, MIT License)")
    print("  1. Download MediaMTX (single binary, no dependencies):")
    print("     https://github.com/bluenviron/mediamtx/releases")
    print("  2. Run the MediaMTX server:")
    print("     ./mediamtx.exe")
    print("     (Listening on rtsp://localhost:8554)")
    print("\nOption 2: Docker MediaMTX")
    print("     docker run --rm -it --network=host bluenviron/mediamtx:latest")
    print("\nPublishing a Looping Video Stream with FFmpeg:")
    print("     ffmpeg -re -stream_loop -1 -i tests/video_test/person_1_vid.mp4 \\")
    print("            -c:v libx264 -preset ultrafast -tune zerolatency -b:v 1M \\")
    print("            -f rtsp rtsp://localhost:8554/cam_room_101_door")
    print("=" * 72)


def publish_ffmpeg_stream(
    video_path: Path,
    rtsp_url: str = "rtsp://localhost:8554/cam_room_101_door",
    target_fps: int = 15,
) -> None:
    """Publish a looping MP4 to an RTSP endpoint using FFmpeg."""
    if not shutil.which("ffmpeg"):
        print("[ERROR] FFmpeg is not installed or not in PATH.")
        print_setup_instructions()
        sys.exit(1)

    if not video_path.exists():
        print(f"[ERROR] Video file not found: {video_path}")
        sys.exit(1)

    cmd = [
        "ffmpeg",
        "-re",
        "-stream_loop",
        "-1",
        "-i",
        str(video_path),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-tune",
        "zerolatency",
        "-r",
        str(target_fps),
        "-f",
        "rtsp",
        "-rtsp_transport",
        "tcp",
        rtsp_url,
    ]

    print(f"[INFO] Streaming {video_path.name} in continuous loop to {rtsp_url}...")
    print(f"[CMD] {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\n[INFO] Stopped streaming.")


def main():
    parser = argparse.ArgumentParser(
        description="Publish local looping video as simulated RTSP CCTV stream"
    )
    parser.add_argument(
        "--clip", type=str, default=str(DEFAULT_CLIP), help="Path to MP4 clip to loop"
    )
    parser.add_argument(
        "--url",
        type=str,
        default="rtsp://localhost:8554/cam_room_101_door",
        help="RTSP publish URL",
    )
    parser.add_argument("--fps", type=int, default=15, help="Framerate")
    parser.add_argument("--instructions", action="store_true", help="Print setup instructions")

    args = parser.parse_args()

    if args.instructions:
        print_setup_instructions()
        return

    publish_ffmpeg_stream(video_path=Path(args.clip), rtsp_url=args.url, target_fps=args.fps)


if __name__ == "__main__":
    main()
