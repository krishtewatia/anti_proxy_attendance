#!/usr/bin/env python3
"""Minimal Standalone Camera Diagnostic Script for Anti-Proxy Attendance.

Tests physical camera devices directly with OpenCV, verifying:
1. Device opening
2. Backend compatibility (DirectShow vs MSMF)
3. Actual frame receipt
4. Resolution & FPS measurement
5. Safe and clean release of the hardware device

Usage:
    python vision-service/test_camera.py --camera-index 0
    python vision-service/test_camera.py --camera-index 0 --show
    python vision-service/test_camera.py --camera-index 1 --backend dshow
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Optional, Tuple
import cv2


def test_camera(
    device_index: int = 0,
    backend_name: str = "auto",
    requested_width: int = 640,
    requested_height: int = 480,
    frames_to_test: int = 15,
    show_window: bool = False,
) -> dict:
    print("\n" + "=" * 60)
    print("Camera diagnostic")
    print("=" * 60)
    print(f"Device index: {device_index}")

    # Determine backend
    backend_flag: Optional[int] = None
    resolved_backend_str = "Default"

    backend_name_lower = backend_name.lower()
    if sys.platform == "win32":
        if backend_name_lower in ("dshow", "directshow"):
            backend_flag = cv2.CAP_DSHOW
            resolved_backend_str = "DirectShow (cv2.CAP_DSHOW)"
        elif backend_name_lower in ("msmf", "media_foundation"):
            backend_flag = cv2.CAP_MSMF
            resolved_backend_str = "Media Foundation (cv2.CAP_MSMF)"
        elif backend_name_lower == "default":
            backend_flag = None
            resolved_backend_str = "Default"
        else:  # auto
            # Try DirectShow first on Windows, then MSMF
            backend_flag = cv2.CAP_DSHOW
            resolved_backend_str = "Auto (Testing DirectShow first)"
    else:
        resolved_backend_str = "Standard V4L2/Default"

    print(f"OpenCV backend: {resolved_backend_str}")

    cap = None
    try:
        if backend_flag is not None:
            cap = cv2.VideoCapture(device_index, backend_flag)
        else:
            cap = cv2.VideoCapture(device_index)

        # On Windows Auto, if DirectShow fails to open, try MSMF
        if sys.platform == "win32" and backend_name_lower == "auto" and (not cap or not cap.isOpened()):
            if cap:
                cap.release()
            cap = cv2.VideoCapture(device_index, cv2.CAP_MSMF)
            if cap and cap.isOpened():
                resolved_backend_str = "Media Foundation (cv2.CAP_MSMF)"
                print(f"Fell back to backend: {resolved_backend_str}")

    except Exception as exc:
        print(f"Camera opened: NO (Exception: {exc})")
        return {"opened": False, "frame_received": False, "error": str(exc)}

    if not cap or not cap.isOpened():
        print("Camera opened: NO")
        print("\nPossible causes:")
        print("  - Camera is already being used by another application (Teams, Zoom, Meet, OBS, Camera App).")
        print("  - Windows camera permission is disabled (Settings > Privacy & Security > Camera).")
        print("  - Invalid camera index (run: python vision-service/list_cameras.py).")
        print("  - USB webcam / phone is disconnected or phone webcam software is not running.")
        print("  - Camera driver is unavailable.")
        print("=" * 60 + "\n")
        return {"opened": False, "frame_received": False}

    print("Camera opened: YES")

    # Set requested resolution
    if requested_width and requested_height:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, requested_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, requested_height)

    # Attempt to read frames
    received_frames = 0
    first_frame_shape: Optional[Tuple[int, int]] = None
    start_time = time.time()

    for i in range(frames_to_test):
        ret, frame = cap.read()
        if ret and frame is not None and frame.size > 0:
            received_frames += 1
            if first_frame_shape is None:
                first_frame_shape = (frame.shape[1], frame.shape[0])

            if show_window:
                cv2.imshow(f"Camera Diagnostic - Device {device_index}", frame)
                if cv2.waitKey(30) & 0xFF == 27:  # ESC to exit
                    break
        else:
            time.sleep(0.05)

    elapsed = time.time() - start_time
    fps = (received_frames / elapsed) if elapsed > 0 else 0.0

    if received_frames > 0 and first_frame_shape is not None:
        print("Frame received: YES")
        print(f"Resolution: {first_frame_shape[0]}x{first_frame_shape[1]}")
        print(f"FPS: {fps:.1f}")
        print("=" * 60 + "\n")
        result = {
            "opened": True,
            "frame_received": True,
            "width": first_frame_shape[0],
            "height": first_frame_shape[1],
            "fps": round(fps, 1),
            "backend": resolved_backend_str,
        }
    else:
        print("Frame received: NO")
        print("\nPossible causes:")
        print("  - Hardware sensor is active but stream was preempted by another process.")
        print("  - USB bandwidth limitation or cable disconnection.")
        print("  - Driver initialization timeout.")
        print("=" * 60 + "\n")
        result = {
            "opened": True,
            "frame_received": False,
            "backend": resolved_backend_str,
        }

    # Clean release
    cap.release()
    if show_window:
        cv2.destroyAllWindows()

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Test and diagnose Windows camera connection")
    parser.add_argument("--camera-index", type=int, default=0, help="Camera device index (default: 0)")
    parser.add_argument(
        "--backend",
        choices=["auto", "dshow", "msmf", "default"],
        default="auto",
        help="OpenCV capture backend (default: auto)",
    )
    parser.add_argument("--width", type=int, default=640, help="Requested frame width (default: 640)")
    parser.add_argument("--height", type=int, default=480, help="Requested frame height (default: 480)")
    parser.add_argument("--frames", type=int, default=15, help="Number of frames to test (default: 15)")
    parser.add_argument("--show", action="store_true", help="Display camera window")
    args = parser.parse_args()

    test_camera(
        device_index=args.camera_index,
        backend_name=args.backend,
        requested_width=args.width,
        requested_height=args.height,
        frames_to_test=args.frames,
        show_window=args.show,
    )


if __name__ == "__main__":
    main()
