#!/usr/bin/env python3
"""Local Camera Discovery Utility for Anti-Proxy Attendance System.

Discovers and tests all connected camera devices (built-in webcam, USB webcams,
and phone USB webcam tools like DroidCam/Iriun/Camo).

Usage:
  python vision-service/list_cameras.py
"""

from __future__ import annotations

import contextlib
import os
import sys
from typing import Any, List, Optional
import cv2


@contextlib.contextmanager
def suppress_c_stderr():
    """Suppress C-level driver/OpenCV stderr warnings during device probing."""
    try:
        null_fd = os.open(os.devnull, os.O_WRONLY)
        old_stderr = os.dup(2)
        os.dup2(null_fd, 2)
        os.close(null_fd)
        try:
            yield
        finally:
            os.dup2(old_stderr, 2)
            os.close(old_stderr)
    except Exception:
        yield


def get_available_cameras(max_probe: int = 6) -> List[dict[str, Any]]:
    """Scan and return a list of verified available camera devices.

    Returns:
      List of dicts: [
        {"index": int, "name": str, "width": int, "height": int, "backend": str},
        ...
      ]
    """
    os.environ["OPENCV_LOG_LEVEL"] = "OFF"
    os.environ["OPENCV_VIDEOIO_DEBUG"] = "0"
    import cv2

    friendly_names: list[str] = []
    if sys.platform == "win32":
        try:
            from pygrabber.dshow_graph import FilterGraph
            graph = FilterGraph()
            friendly_names = graph.get_input_devices()
        except Exception:
            friendly_names = []

    available: list[dict[str, Any]] = []

    # Probe indices 0 to max_probe
    probe_limit = max(len(friendly_names), max_probe)
    for idx in range(probe_limit):
        cap = None
        backend = "DEFAULT"

        with suppress_c_stderr():
            if sys.platform == "win32":
                cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                backend = "DirectShow"
                if not cap.isOpened():
                    cap = cv2.VideoCapture(idx, cv2.CAP_MSMF)
                    backend = "MSMF"
            else:
                cap = cv2.VideoCapture(idx)

        if cap is not None and cap.isOpened():
            ret, frame = False, None
            with suppress_c_stderr():
                # Read 2 test frames to allow sensor AGC/exposure lock
                cap.read()
                ret, frame = cap.read()

            if ret and frame is not None:
                h, w = frame.shape[:2]
                dev_name = (
                    friendly_names[idx]
                    if idx < len(friendly_names)
                    else f"Camera Device {idx}"
                )
                available.append({
                    "index": idx,
                    "name": dev_name,
                    "width": w,
                    "height": h,
                    "backend": backend,
                })
            cap.release()

    return available


def main() -> None:
    print("\n" + "=" * 60)
    print("COLLEGE ATTENDANCE SYSTEM — CAMERA DISCOVERY")
    print("=" * 60)

    # Probe indices 0 to 3 explicitly
    for idx in range(4):
        cap = None
        backend = "DirectShow"
        with suppress_c_stderr():
            if sys.platform == "win32":
                cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    cap = cv2.VideoCapture(idx, cv2.CAP_MSMF)
                    backend = "MSMF"
            else:
                cap = cv2.VideoCapture(idx)

        if cap is not None and cap.isOpened():
            ret, frame = False, None
            with suppress_c_stderr():
                cap.read()
                ret, frame = cap.read()
            if ret and frame is not None:
                h, w = frame.shape[:2]
                print(f"Index {idx} -> available ({w}x{h} via {backend})")
            else:
                print(f"Index {idx} -> unavailable (opened but no frames received)")
            cap.release()
        else:
            print(f"Index {idx} -> unavailable")

    cameras = get_available_cameras()

    if not cameras:
        print("\nCould not open any camera.\n")
        print("Please:")
        print("  - connect your webcam or USB phone camera")
        print("  - check Windows camera permissions (Settings > Privacy & Security > Camera)")
        print("  - verify the selected camera index")
        print("  - ensure another application is not exclusively using the camera\n")
        sys.exit(1)

    print("\nAvailable cameras summary:\n")
    for cam in cameras:
        print(f"  [{cam['index']}] {cam['name']} ({cam['width']}x{cam['height']} via {cam['backend']})")

    print("\nTo start attendance with a specific camera:")
    default_idx = cameras[0]["index"]
    print(f"  python vision-service/run_local_webcam.py --camera-index {default_idx}\n")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
