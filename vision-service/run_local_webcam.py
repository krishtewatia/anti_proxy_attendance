"""Standalone Local Webcam AI Face Recognition Attendance Runner.

Captures directly from a single local camera (laptop built-in webcam or USB-connected phone),
runs InsightFace detection (SCRFD) + ArcFace recognition, marks students present one-time per session,
dispatches directly to the college attendance backend, and exposes an annotated MJPEG stream on port 8088.

Usage:
  python vision-service/run_local_webcam.py --camera-index 0
  python vision-service/run_local_webcam.py --camera-index 1
  python vision-service/run_local_webcam.py --list-cameras
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Optional, Set
import cv2
import numpy as np
import requests

# Ensure vision-service root is in sys.path
import sys

SERVICE_ROOT = Path(__file__).resolve().parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from camera.base import VideoFrame, VideoSourceType
from camera.webcam_source import WebcamVideoSource
from events.event_dispatcher import EventDispatcher
from list_cameras import get_available_cameras
from pipeline.live_cv_pipeline import (
    LiveCVPipeline,
    create_face_analysis,
    load_gallery,
    load_gallery_from_npz,
)

logger = logging.getLogger("run_local_webcam")


class WebcamStreamState:
    """Thread-safe holder for latest annotated frame, active session, and telemetry."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.latest_jpeg: Optional[bytes] = None
        self.pipeline: Optional[LiveCVPipeline] = None
        self.fps: float = 0.0
        self.last_frame_time: float = 0.0
        self.marked_identities: Set[str] = set()
        self.active_session_id: Optional[str] = None
        self.camera_name: str = "Webcam"
        self.resolution: str = "640x480"
        self.backend_name: str = "DirectShow"

    def update_frame(self, frame_bgr: np.ndarray) -> None:
        ret, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ret:
            with self.lock:
                self.latest_jpeg = buf.tobytes()
                self.last_frame_time = time.time()

    def get_frame(self) -> Optional[bytes]:
        with self.lock:
            return self.latest_jpeg

    def reset_session(self, session_id: Optional[str] = None) -> None:
        with self.lock:
            self.marked_identities.clear()
            if session_id:
                self.active_session_id = session_id
            if self.pipeline:
                self.pipeline.session_marked_students.clear()
                self.pipeline.last_recognized_student = None
        logger.info("[SESSION] Reset attendance state. Active session: %s", self.active_session_id)


stream_state = WebcamStreamState()


class WebcamHTTPHandler(BaseHTTPRequestHandler):
    """HTTP server exposing live annotated MJPEG stream and control endpoints."""

    def log_message(self, format: str, *args) -> None:
        pass

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?")[0].rstrip("/")

        if path in ("/preview.mjpg", "/preview.mjpeg", "/stream"):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header(
                "Content-Type", "multipart/x-mixed-replace; boundary=frame"
            )
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.end_headers()

            while True:
                jpeg = stream_state.get_frame()
                if jpeg is not None:
                    try:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(
                            f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
                        )
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                    except (BrokenPipeError, ConnectionResetError):
                        break
                time.sleep(0.05)

        elif path in ("/status", "/health"):
            pipe = stream_state.pipeline
            with stream_state.lock:
                present_list = list(stream_state.marked_identities)
                active_sess = stream_state.active_session_id
                cam_name = stream_state.camera_name
                res_str = stream_state.resolution
                be_str = stream_state.backend_name

            data = {
                "status": "online",
                "fps": round(stream_state.fps, 1),
                "camera_connected": (time.time() - stream_state.last_frame_time) < 3.0,
                "camera_name": cam_name,
                "resolution": res_str,
                "backend": be_str,
                "active_session_id": active_sess,
                "present_count": len(present_list),
                "present_students": present_list,
                "marked_students_count": len(present_list),
                "marked_students": present_list,
                "last_recognized": pipe.last_recognized_student if pipe else None,
                "last_recognized_student": pipe.last_recognized_student if pipe else None,
            }
            body = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        path = self.path.split("?")[0].rstrip("/")
        if path == "/reset":
            new_sess_id = None
            if self.headers.get("Content-Length"):
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    if length > 0:
                        body_data = json.loads(self.rfile.read(length).decode("utf-8"))
                        new_sess_id = body_data.get("session_id")
                except Exception:
                    pass
            stream_state.reset_session(new_sess_id)
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "reset", "present_count": 0}')
        elif path == "/extract-embedding":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                from extract_photo_embedding import extract_from_image_bytes
                res = extract_from_image_bytes(body)
            except Exception as exc:
                res = {"status": "error", "message": str(exc)}
            resp_bytes = json.dumps(res).encode("utf-8")
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)
        elif path == "/reload-gallery":
            if stream_state.pipeline:
                try:
                    stream_state.pipeline.gallery = load_gallery()
                except Exception:
                    pass
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "gallery_reloaded"}')
        else:
            self.send_response(404)
            self.end_headers()


def start_preview_server(port: int = 8088) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", port), WebcamHTTPHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    logger.info("Live Webcam MJPEG preview stream listening on http://0.0.0.0:%d/preview.mjpg", port)
    return server


def check_backend_active_session(backend_url: str) -> Optional[dict]:
    """Query FastAPI backend to see if an attendance session is currently active."""
    try:
        url = f"{backend_url.rstrip('/')}/api/v1/attendance/active-session"
        resp = requests.get(url, timeout=1.5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("has_active_session"):
                return data
    except Exception:
        pass
    return None


def post_student_present_to_backend(
    backend_url: str,
    identity: str,
    session_id: Optional[str] = None,
) -> bool:
    """Post confirmed student presence to the FastAPI attendance mark endpoint."""
    url = f"{backend_url.rstrip('/')}/api/v1/attendance/mark"
    payload = {"identity": identity}
    if session_id:
        payload["session_id"] = session_id

    try:
        resp = requests.post(url, json=payload, timeout=2.0)
        if resp.status_code == 200:
            data = resp.json()
            st = data.get("status")
            name = data.get("student_name", identity)
            if st == "marked":
                logger.info("[ATTENDANCE] ✓ %s marked PRESENT (Identity: %s, Session: %s)", name, identity, session_id or "ACTIVE")
            elif st == "already_present":
                logger.debug("[ATTENDANCE] %s is already marked present", name)
            return True
        elif resp.status_code == 404:
            logger.debug("[ATTENDANCE] Cannot mark attendance: No active session running on backend.")
            return False
        else:
            logger.warning("Backend mark error (%d): %s", resp.status_code, resp.text)
            return False
    except Exception as exc:
        logger.warning("Could not dispatch attendance to backend: %s", exc)
        return False


def main() -> None:
    import atexit
    import signal

    parser = argparse.ArgumentParser(
        description="AI Face Recognition Attendance System — Single Local Webcam Runner"
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        default=None,
        help="OpenCV webcam device index (0 for built-in, 1 or 2 for USB phone webcam)",
    )
    parser.add_argument(
        "--list-cameras",
        action="store_true",
        help="Discover and display all available cameras and exit",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Target attendance session ID (if omitted, automatically targets the active session)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("VISION_PORT", "8088")),
        help="HTTP preview server port (default: 8088)",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=640,
        help="Requested camera capture width (default: 640)",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=480,
        help="Requested camera capture height (default: 480)",
    )
    parser.add_argument(
        "--backend-url",
        default=os.getenv("BACKEND_URL", "http://127.0.0.1:8000"),
        help="FastAPI backend URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--gallery-npz",
        default=os.getenv("GALLERY_NPZ_PATH", str(SERVICE_ROOT / "gallery.npz")),
        help="Path to precomputed gallery.npz (default: vision-service/gallery.npz)",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Display OpenCV desktop window showing live camera stream",
    )
    parser.add_argument(
        "--dispatch",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Dispatch confirmed attendance events to FastAPI backend (default: True)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 1. Camera Discovery / List Mode
    if args.list_cameras:
        from list_cameras import main as list_main
        list_main()
        return

    # Check available cameras on system
    discovered = get_available_cameras()
    if not discovered:
        print("\n" + "=" * 60)
        print("Could not open camera.")
        print("")
        print("Please:")
        print("  - connect your webcam or USB phone camera")
        print("  - check Windows camera permissions (Settings > Privacy & Security > Camera)")
        print("  - verify the selected camera index (run: python vision-service/list_cameras.py)")
        print("  - ensure another application is not exclusively locking the camera")
        print("=" * 60 + "\n")
        sys.exit(1)

    # Determine selected camera index
    if args.camera_index is None:
        selected_index = discovered[0]["index"]
        selected_cam_name = discovered[0]["name"]
        selected_backend = discovered[0].get("backend", "DirectShow")
        logger.info("Auto-selected first available camera: [%d] %s", selected_index, selected_cam_name)
    else:
        selected_index = args.camera_index
        matched = next((c for c in discovered if c["index"] == selected_index), None)
        if matched:
            selected_cam_name = matched["name"]
            selected_backend = matched.get("backend", "DirectShow")
            logger.info("Selected camera [%d]: %s", selected_index, selected_cam_name)
        else:
            selected_cam_name = f"Camera Device {selected_index}"
            selected_backend = "DirectShow"
            logger.warning(
                "Camera index %d was not in detected list %s. Attempting direct open...",
                selected_index,
                [c["index"] for c in discovered],
            )

    stream_state.camera_name = selected_cam_name
    stream_state.backend_name = selected_backend
    if args.session_id:
        stream_state.active_session_id = args.session_id

    # 2. Initialize Face Models
    logger.info("Initializing InsightFace detection (SCRFD) and recognition (ArcFace)...")
    app = create_face_analysis()

    # 3. Load Biometric Gallery
    npz_path = Path(args.gallery_npz)
    if npz_path.exists():
        logger.info("Loading precomputed gallery from %s", npz_path)
        gallery = load_gallery_from_npz(npz_path)
    else:
        bench_dir = SERVICE_ROOT / "tests" / "recognition_benchmark"
        logger.info("Gallery .npz not found; computing from %s", bench_dir)
        gallery = load_gallery(app, bench_dir)

    logger.info("Gallery ready with %d enrolled student identities: %s", len(gallery), list(gallery.keys()))

    # 4. Setup Event Dispatcher to FastAPI
    dispatcher = None
    if args.dispatch:
        api_key = os.getenv("VISION_SERVICE_API_KEY", "test_vision_api_key_for_smoke_test_12345")
        dispatcher = EventDispatcher(
            backend_url=args.backend_url,
            api_key=api_key,
            timeout=3.0,
            raise_on_failure=False,
            dedup_by_track=False,
        )

    # 5. Initialize One-Time Attendance Pipeline
    pipeline = LiveCVPipeline(
        app=app,
        gallery=gallery,
        source_id=f"WEBCAM_{selected_index}",
        camera_id="LOCAL_WEBCAM",
        similarity_threshold=0.50,
        min_supporting_frames=2,
        event_dispatcher=dispatcher,
    )
    pipeline.mode = "ONE_TIME_ATTENDANCE"
    stream_state.pipeline = pipeline

    # 6. Start HTTP Preview Server
    start_preview_server(port=args.port)

    # 7. Open Physical Webcam
    webcam = WebcamVideoSource(
        device_index=selected_index,
        source_id=f"WEBCAM_{selected_index}",
        width=args.width,
        height=args.height,
    )

    def _safe_cleanup():
        try:
            webcam.close()
        except Exception:
            pass
        if args.show:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass

    atexit.register(_safe_cleanup)

    try:
        webcam.open()
    except Exception as exc:
        print("\n" + "=" * 60)
        print("Could not open camera.")
        print("")
        print(f"Error: {exc}")
        print("")
        print("Please:")
        print("  - connect your webcam or USB phone camera")
        print("  - check Windows camera permissions (Settings > Privacy & Security > Camera)")
        print("  - verify the selected camera index (run: python vision-service/list_cameras.py)")
        print("  - ensure another application is not exclusively locking the camera")
        print("=" * 60 + "\n")
        sys.exit(1)

    stream_state.resolution = f"{webcam._actual_width}x{webcam._actual_height}"

    print("\n" + "=" * 60)
    print("AI FACE RECOGNITION ATTENDANCE SYSTEM ACTIVE")
    print(f"Camera Device Index : {selected_index} ({selected_cam_name})")
    print(f"Captured Resolution : {stream_state.resolution}")
    print(f"Web Preview Stream  : http://localhost:{args.port}/preview.mjpg")
    print(f"Backend API URL     : {args.backend_url}")
    print("Stand in front of the camera to be marked PRESENT.")
    print("=" * 60 + "\n")

    frame_count = 0
    consecutive_empty = 0
    t0 = time.time()
    last_session_check = 0.0

    try:
        while True:
            vframe = webcam.read()
            if vframe is None or vframe.frame is None:
                consecutive_empty += 1
                if consecutive_empty > 60:
                    logger.warning("Camera stream interrupted: No frames received for 60 consecutive cycles.")
                    consecutive_empty = 0
                time.sleep(0.01)
                continue

            consecutive_empty = 0
            now = time.time()

            # Periodically sync active session from FastAPI backend if not fixed via CLI
            if not args.session_id and (now - last_session_check > 2.0):
                last_session_check = now
                active_meta = check_backend_active_session(args.backend_url)
                if active_meta:
                    sess_id = active_meta["session_id"]
                    if stream_state.active_session_id != sess_id:
                        logger.info("[ACTIVE SESSION] Detected active session: %s (%s - %s)", sess_id, active_meta.get("class_code"), active_meta.get("subject"))
                        stream_state.reset_session(sess_id)
                else:
                    if stream_state.active_session_id is not None:
                        logger.info("[ACTIVE SESSION] Attendance session ended. Resetting vision state.")
                        stream_state.reset_session(None)

            # Process frame through face recognition pipeline
            res = pipeline.process_frame(vframe)

            # Direct FastAPI attendance registration
            if res.tracks and args.dispatch:
                target_sess = args.session_id or stream_state.active_session_id
                if target_sess:
                    for tr in res.tracks:
                        if tr.is_confirmed and tr.identity and tr.identity != "UNKNOWN":
                            with stream_state.lock:
                                already_marked = tr.identity in stream_state.marked_identities
                            if not already_marked:
                                ok = post_student_present_to_backend(
                                    backend_url=args.backend_url,
                                    identity=tr.identity,
                                    session_id=target_sess,
                                )
                                if ok:
                                    with stream_state.lock:
                                        stream_state.marked_identities.add(tr.identity)

            # Render clean teacher-friendly video annotations
            annotated = pipeline.render_annotated_frame(vframe.frame, res)
            stream_state.update_frame(annotated)

            # Optional local OpenCV window
            if args.show:
                cv2.imshow("Anti-Proxy Attendance — Live Webcam", annotated)
                key = cv2.waitKey(1) & 0xFF
                if key == 27 or key == ord("q"):
                    break

            frame_count += 1
            if frame_count % 30 == 0:
                stream_state.fps = 30.0 / (now - t0 + 1e-6)
                t0 = now
                detected_faces = len(res.tracks) if res.tracks else 0
                candidates = [t.identity for t in res.tracks if t.identity and t.identity != "UNKNOWN"] if res.tracks else []
                logger.info(
                    "[DEV LOG] Frame: %d | Res: %s | FPS: %.1f | Faces: %d | Candidate: %s | Marked: %d | Session: %s",
                    frame_count,
                    stream_state.resolution,
                    stream_state.fps,
                    detected_faces,
                    candidates if candidates else "none",
                    len(stream_state.marked_identities),
                    stream_state.active_session_id or "NO_ACTIVE_SESSION",
                )

    except KeyboardInterrupt:
        logger.info("Shutting down webcam runner...")
    finally:
        _safe_cleanup()


if __name__ == "__main__":
    main()
