"""Benchmark CPU and throughput FPS for 1 vs 2 concurrent cameras."""

import os
import json
from pathlib import Path
import sys

SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from camera_worker import MultiCameraRunner
from pipeline.live_cv_pipeline import create_face_analysis, load_gallery

CLIP_1 = (
    Path(os.environ.get("VISION_FIXTURES_DIR") or "vision-fixtures-not-configured")
    / "video_test"
    / "person_1_vid.mp4"
)
CLIP_2 = (
    Path(os.environ.get("VISION_FIXTURES_DIR") or "vision-fixtures-not-configured")
    / "video_test"
    / "person_2_vid.mp4"
)
ENROLLMENT_DIR = (
    Path(os.environ.get("VISION_FIXTURES_DIR") or "vision-fixtures-not-configured")
    / "recognition_benchmark"
)


def main():
    print("=" * 70)
    print("Multi-Camera Pipeline Performance Benchmark (1 vs 2 Cameras)")
    print("=" * 70)

    print("[1/3] Initializing InsightFace models and gallery...")
    from pipeline.live_cv_pipeline import swap_scrfd_detector

    app = create_face_analysis(name="buffalo_l", det_size=(640, 640))
    swap_scrfd_detector(app, "0.5g")
    gallery = load_gallery(app, ENROLLMENT_DIR)
    print(f"Loaded gallery with {len(gallery)} identities.")

    camera_configs = [
        {
            "camera_id": "CAM_ROOM_101_DOOR_ENTRY",
            "classroom_id": "ROOM_101",
            "role": "ENTRY",
            "source_type": "FILE",
            "source_uri": str(CLIP_1),
            "target_fps": 30.0,
            "heartbeat_interval_sec": 999999.0,
        },
        {
            "camera_id": "CAM_ROOM_101_DOOR_EXIT",
            "classroom_id": "ROOM_101",
            "role": "EXIT",
            "source_type": "FILE",
            "source_uri": str(CLIP_2),
            "target_fps": 30.0,
            "heartbeat_interval_sec": 999999.0,
        },
    ]

    print("\n[2/3] Running Benchmark for 5 seconds per configuration...")
    benchmark_results = MultiCameraRunner.benchmark(
        camera_configs=camera_configs,
        app=app,
        gallery=gallery,
        duration_sec=5.0,
    )

    print("\n[3/3] Benchmark Results:")
    print("-" * 70)
    print(f"{'Metric':<30} | {'1 Camera':<18} | {'2 Cameras':<18}")
    print("-" * 70)

    b1 = benchmark_results.get("1_cameras", {})
    b2 = benchmark_results.get("2_cameras", {})

    print(
        f"{'Aggregate FPS':<30} | {b1.get('aggregate_fps', 0):<18} | {b2.get('aggregate_fps', 0):<18}"
    )
    print(
        f"{'Total Frames Processed':<30} | {b1.get('frames_processed', 0):<18} | {b2.get('frames_processed', 0):<18}"
    )
    print(
        f"{'CPU Utilization (%)':<30} | {b1.get('cpu_percent', 0):<18} | {b2.get('cpu_percent', 0):<18}"
    )
    print(
        f"{'Per-Camera Worker FPS':<30} | {str(b1.get('per_camera_fps', [])):<18} | {str(b2.get('per_camera_fps', [])):<18}"
    )
    print("-" * 70)

    # Save benchmark metrics to json
    out_path = SERVICE_ROOT / "docs" / "benchmarks" / "multi_camera_benchmark_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(benchmark_results, f, indent=2)
    print(f"\nSaved benchmark metrics to {out_path}")


if __name__ == "__main__":
    main()
