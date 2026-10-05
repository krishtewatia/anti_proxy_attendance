"""Standalone Local Webcam AI Face Recognition Attendance Agent.

Runs as a native Windows camera agent:
- Preloads InsightFace (SCRFD + ArcFace) and biometric student gallery into memory.
- Keeps HTTP preview server active on port 8088 for status, telemetry, and live MJPEG streaming.
- Automatically monitors attendance session state from the FastAPI backend.
- Opens the physical webcam ONLY when an active attendance session exists.
- Automatically releases the physical webcam when attendance ends, freeing it for other Windows apps.
- Re-opens camera dynamically if new sessions begin, safely resetting in-memory attendance tracking.
- Recovers gracefully with exponential backoff if the webcam is disconnected or busy.

Usage:
  python vision-service/run_local_webcam.py
  python vision-service/run_local_webcam.py --camera-index 0
  python vision-service/run_local_webcam.py --camera-index auto
  python vision-service/run_local_webcam.py --list-cameras
"""

from __future__ import annotations

import argparse
import atexit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import signal
import sys
import threading
import time
from typing import Any, Optional, Set
import cv2
import numpy as np
import requests

# Ensure vision-service root is in sys.path
SERVICE_ROOT = Path(__file__).resolve().parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

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
        self.camera_active: bool = False
        self.status_message: str = "Standby (Camera idle)"

    def update_frame(self, frame_bgr: np.ndarray) -> None:
        ret, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ret:
            with self.lock:
                self.latest_jpeg = buf.tobytes()
                self.last_frame_time = time.time()
                self.camera_active = True
                self.status_message = "Live attendance active"

    def clear_frame(self) -> None:
        with self.lock:
            self.latest_jpeg = None
            self.camera_active = False
            self.fps = 0.0
            self.status_message = "Standby (Camera released)"

    def get_frame(self) -> Optional[bytes]:
        with self.lock:
            return self.latest_jpeg

    def reset_session(self, session_id: Optional[str] = None) -> None:
        with self.lock:
            self.marked_identities.clear()
            self.active_session_id = session_id
            if self.pipeline:
                self.pipeline.session_marked_students.clear()
                self.pipeline.last_recognized_student = None
        logger.info("[SESSION] Attendance state reset. Active session: %s", session_id)


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
                    time.sleep(0.04)
                else:
                    # When camera is closed or waiting for session, sleep briefly
                    time.sleep(0.1)

        elif path in ("/status", "/health"):
            pipe = stream_state.pipeline
            with stream_state.lock:
                present_list = list(stream_state.marked_identities)
                active_sess = stream_state.active_session_id
                cam_name = stream_state.camera_name
                res_str = stream_state.resolution
                be_str = stream_state.backend_name
                cam_active = stream_state.camera_active
                last_ft = stream_state.last_frame_time
                fps_val = stream_state.fps
                st_msg = stream_state.status_message

            cam_connected = cam_active and ((time.time() - last_ft) < 3.0)

            data = {
                "status": "online",
                "camera_active": cam_active,
                "camera_connected": cam_connected,
                "fps": round(fps_val, 1) if cam_connected else 0.0,
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
                "status_message": st_msg,
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
            self.wfile.write(
                json.dumps({
                    "status": "reset",
                    "active_session_id": new_sess_id,
                    "present_count": 0,
                }).encode("utf-8")
            )
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


def start_preview_server(port: int = 8088) -> Optional[ThreadingHTTPServer]:
    """Start HTTP preview and control server on specified port with conflict check."""
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), WebcamHTTPHandler)
    except OSError as exc:
        logger.error(
            "Port %d is already in use by another process. "
            "Another vision agent is likely already running. (%s)",
            port,
            exc,
        )
        return None

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
    parser = argparse.ArgumentParser(
        description="AI Face Recognition Attendance System — Single Local Webcam Agent"
    )
    parser.add_argument(
        "--camera-index",
        default=os.getenv("CAMERA_INDEX", "auto"),
        help="OpenCV webcam device index (0, 1, 2, or 'auto' for auto-discovery)",
    )
    parser.add_argument(
        "--list-cameras",
        action="store_true",
        help="Discover and display all available cameras and exit",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Optional fixed attendance session ID (if omitted, automatically syncs with backend active session)",
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
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Seconds between backend active-session polls (default: 0.5s)",
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

    # Check available cameras on system for diagnostic log
    try:
        discovered = get_available_cameras()
        if discovered:
            logger.info("Discovered %d connected camera device(s):", len(discovered))
            for cam in discovered:
                logger.info("  [%d] %s (%dx%d via %s)", cam["index"], cam["name"], cam["width"], cam["height"], cam["backend"])
        else:
            logger.warning("No camera devices currently detected. Agent will attempt auto-probe when session begins.")
    except Exception as exc:
        logger.debug("Initial camera discovery probe skipped: %s", exc)

    # 2. Initialize Face Models (SCRFD + ArcFace) once at startup
    logger.info("Preloading InsightFace detection (SCRFD) and recognition (ArcFace) into memory...")
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

    # 5. Initialize One-Time Attendance Live Pipeline
    pipeline = LiveCVPipeline(
        app=app,
        gallery=gallery,
        source_id="WEBCAM_AGENT",
        camera_id="LOCAL_WEBCAM",
        similarity_threshold=0.50,
        min_supporting_frames=2,
        event_dispatcher=dispatcher,
    )
    pipeline.mode = "ONE_TIME_ATTENDANCE"
    stream_state.pipeline = pipeline

    # 6. Start HTTP Control & Preview Server
    server = start_preview_server(port=args.port)
    if server is None:
        logger.warning("Exiting duplicate vision agent instance.")
        sys.exit(0)

    # 7. Safe Cleanup Registration
    webcam_ref: list[Optional[WebcamVideoSource]] = [None]

    def _safe_cleanup():
        w = webcam_ref[0]
        if w is not None:
            try:
                w.close()
            except Exception:
                pass
            webcam_ref[0] = None
        stream_state.clear_frame()
        if args.show:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
        logger.info("Vision agent shutdown complete. Camera is released.")

    atexit.register(_safe_cleanup)

    def _handle_signal(sig, frame):
        logger.info("Received signal %s. Shutting down gracefully...", sig)
        _safe_cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Convert camera index argument
    configured_cam_index: Any = args.camera_index
    if str(configured_cam_index).isdigit():
        configured_cam_index = int(configured_cam_index)

    print("\n" + "=" * 60)
    print("AI FACE RECOGNITION ATTENDANCE AGENT ACTIVE")
    print(f"Configured Camera Index : {configured_cam_index}")
    print("Camera Device Status    : STANDBY (Closed until attendance starts)")
    print(f"Web Control / Preview   : http://localhost:{args.port}/preview.mjpg")
    print(f"Backend API URL         : {args.backend_url}")
    print("Standing by for teacher to start attendance session in ERP...")
    print("=" * 60 + "\n")

    current_session_id: Optional[str] = None
    retry_backoff: float = 1.0
    last_poll_time: float = 0.0
    last_fps_time: float = time.time()
    frames_in_second: int = 0
    consecutive_read_failures: int = 0

    try:
        while True:
            now = time.time()

            # -------------------------------------------------------------
            # STEP A: Poll backend active session (every ~0.5s)
            # -------------------------------------------------------------
            if now - last_poll_time > args.poll_interval:
                last_poll_time = now
                if not args.session_id:
                    active_meta = check_backend_active_session(args.backend_url)
                    if active_meta and active_meta.get("has_active_session"):
                        target_session_id = active_meta.get("session_id")
                    else:
                        target_session_id = None
                else:
                    target_session_id = args.session_id

                # Synchronize with stream_state (fast path or backend sync)
                if target_session_id != stream_state.active_session_id:
                    stream_state.reset_session(target_session_id)

            target_session_id = stream_state.active_session_id

            # -------------------------------------------------------------
            # STEP B: Attendance Session is ACTIVE -> Camera MUST be open
            # -------------------------------------------------------------
            if target_session_id is not None:
                # Check for session change (e.g. Session A ended and Session B started immediately)
                if current_session_id != target_session_id:
                    logger.info("[AGENT] Session changed to %s. Resetting camera and attendance state.", target_session_id)
                    current_session_id = target_session_id
                    if webcam_ref[0] is not None:
                        webcam_ref[0].close()
                        webcam_ref[0] = None
                        stream_state.clear_frame()

                # If camera is not yet open, open it now!
                if webcam_ref[0] is None or not webcam_ref[0].is_opened:
                    stream_state.status_message = "Connecting physical webcam..."
                    logger.info("[AGENT] Active session detected: %s. Opening physical webcam...", target_session_id)
                    try:
                        new_webcam = WebcamVideoSource(
                            device_index=configured_cam_index,
                            width=args.width,
                            height=args.height,
                        )
                        new_webcam.open()
                        webcam_ref[0] = new_webcam
                        stream_state.camera_active = True
                        stream_state.resolution = f"{new_webcam._actual_width}x{new_webcam._actual_height}"
                        stream_state.backend_name = new_webcam._backend_used
                        stream_state.camera_name = f"Camera {new_webcam._selected_index} ({new_webcam._backend_used})"
                        stream_state.status_message = "Live attendance active"
                        retry_backoff = 1.0
                        consecutive_read_failures = 0
                        logger.info(
                            "[AGENT] ✓ Camera READY: %s (%s). Face recognition started for session %s.",
                            stream_state.camera_name,
                            stream_state.resolution,
                            target_session_id,
                        )
                    except Exception as exc:
                        logger.warning(
                            "[AGENT] Could not open camera: %s. Retrying in %.1fs...",
                            exc,
                            retry_backoff,
                        )
                        stream_state.status_message = "Camera unavailable"
                        if webcam_ref[0] is not None:
                            webcam_ref[0].close()
                            webcam_ref[0] = None
                        stream_state.clear_frame()
                        time.sleep(retry_backoff)
                        retry_backoff = min(retry_backoff * 1.5, 5.0)
                        continue

                # Camera is open: read frame
                webcam = webcam_ref[0]
                vframe = webcam.read()
                if vframe is None or vframe.frame is None:
                    consecutive_read_failures += 1
                    if consecutive_read_failures >= 15:
                        logger.warning(
                            "[AGENT] 15 consecutive empty frames from camera. Releasing device to recover..."
                        )
                        webcam.close()
                        webcam_ref[0] = None
                        stream_state.clear_frame()
                        consecutive_read_failures = 0
                        time.sleep(1.0)
                        continue
                    time.sleep(0.02)
                    continue

                consecutive_read_failures = 0

                # Run face detection (SCRFD) + recognition (ArcFace)
                res = pipeline.process_frame(vframe)

                # Dispatch confirmed recognized students
                if res.tracks and args.dispatch:
                    for tr in res.tracks:
                        if tr.is_confirmed and tr.identity and tr.identity != "UNKNOWN":
                            with stream_state.lock:
                                already_marked = tr.identity in stream_state.marked_identities
                            if not already_marked:
                                ok = post_student_present_to_backend(
                                    backend_url=args.backend_url,
                                    identity=tr.identity,
                                    session_id=target_session_id,
                                )
                                if ok:
                                    with stream_state.lock:
                                        stream_state.marked_identities.add(tr.identity)

                # Render annotations and update MJPEG stream
                annotated = pipeline.render_annotated_frame(vframe.frame, res)
                stream_state.update_frame(annotated)

                # Calculate live FPS
                frames_in_second += 1
                t_now = time.time()
                if t_now - last_fps_time >= 1.0:
                    stream_state.fps = frames_in_second / (t_now - last_fps_time)
                    frames_in_second = 0
                    last_fps_time = t_now

                # Optional desktop GUI window
                if args.show:
                    cv2.imshow("Anti-Proxy Attendance — Live Webcam", annotated)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (27, ord("q")):
                        break

                time.sleep(0.01)

            # -------------------------------------------------------------
            # STEP C: NO Active Session -> Camera MUST be closed / released
            # -------------------------------------------------------------
            else:
                if webcam_ref[0] is not None and webcam_ref[0].is_opened:
                    logger.info("[AGENT] Attendance session finalized or inactive. Releasing physical webcam...")
                    webcam_ref[0].close()
                    webcam_ref[0] = None
                    stream_state.clear_frame()
                    current_session_id = None
                    if args.show:
                        try:
                            cv2.destroyAllWindows()
                        except Exception:
                            pass
                    logger.info("[AGENT] ✓ Physical webcam released cleanly. Standing by for next session.")

                # Idle sleep (zero camera capture, zero CPU consumption)
                time.sleep(0.3)

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Shutting down webcam agent...")
    finally:
        _safe_cleanup()


if __name__ == "__main__":
    main()
