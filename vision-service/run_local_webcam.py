"""Standalone AI Face Recognition Attendance Service (Browser-Owned Webcam Architecture).

Operates as a high-performance vision inference server:
- Preloads InsightFace (SCRFD + ArcFace) and biometric student gallery into memory.
- Keeps HTTP server active on port 8088 for status, telemetry, frame processing, and live preview.
- Browser owns the physical webcam via navigator.mediaDevices.getUserMedia().
- Browser streams captured video frames to POST /process-frame.
- Detects faces (SCRFD) and recognizes enrolled student identities (ArcFace).
- Idempotently marks attendance in FastAPI backend / MongoDB.
- NEVER independently acquires or opens physical webcam devices, eliminating device contention.
"""

from __future__ import annotations

import argparse
import base64
import email
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
import urllib.parse

import cv2
import numpy as np
import requests

# Ensure vision-service root is in sys.path
SERVICE_ROOT = Path(__file__).resolve().parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from pipeline.live_cv_pipeline import (
    create_face_analysis,
    load_gallery,
    load_gallery_from_npz,
)

logger = logging.getLogger("vision_service")

# Standard student name & roll number catalog mapping
STUDENT_NAME_MAP: dict[str, str] = {
    "student1": "Rahul Sharma",
    "student2": "Aman Kumar",
    "student3": "Priya Singh",
    "student4": "Krish Tewatia",
    "person_01": "Rahul Sharma",
    "person_02": "Aman Kumar",
    "person_03": "Priya Singh",
    "person_04": "Krish Tewatia",
}

STUDENT_ID_MAP: dict[str, str] = {
    "student1": "DS202601",
    "student2": "DS202602",
    "student3": "DS202603",
    "student4": "DS202604",
    "person_01": "DS202601",
    "person_02": "DS202602",
    "person_03": "DS202603",
    "person_04": "DS202604",
}


class VisionServerState:
    """Thread-safe holder for vision inference models, latest frame, active session, and telemetry."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.app: Optional[Any] = None
        self.gallery: dict[str, np.ndarray] = {}
        self.backend_url: str = "http://127.0.0.1:8000"
        self.similarity_threshold: float = 0.50
        self.min_margin: float = 0.15
        self.latest_jpeg: Optional[bytes] = None
        self.fps: float = 0.0
        self.last_frame_time: float = 0.0
        self.marked_identities: Set[str] = set()
        self.active_session_id: Optional[str] = None
        self.camera_name: str = "Browser Webcam (getUserMedia)"
        self.resolution: str = "640x480"
        self.backend_name: str = "Browser MediaStream"
        self.camera_active: bool = False
        self.status_message: str = "Standby (Awaiting frames from browser)"
        self.last_recognized_student: Optional[str] = None
        self.frame_count: int = 0
        self.fps_frame_count: int = 0
        self.last_fps_calc_time: float = time.time()

    def update_frame(self, frame_bgr: np.ndarray) -> None:
        ret, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
        now = time.time()
        if ret:
            with self.lock:
                self.latest_jpeg = buf.tobytes()
                self.last_frame_time = now
                self.camera_active = True
                self.frame_count += 1
                self.fps_frame_count += 1
                if now - self.last_fps_calc_time >= 1.0:
                    self.fps = round(self.fps_frame_count / (now - self.last_fps_calc_time), 1)
                    self.fps_frame_count = 0
                    self.last_fps_calc_time = now

    def clear_frame(self) -> None:
        with self.lock:
            self.latest_jpeg = None
            self.camera_active = False
            self.fps = 0.0
            self.status_message = "Standby (Camera idle)"

    def get_frame(self) -> Optional[bytes]:
        with self.lock:
            return self.latest_jpeg

    def reset_session(self, session_id: Optional[str] = None) -> None:
        with self.lock:
            self.marked_identities.clear()
            self.active_session_id = session_id
            self.last_recognized_student = None
        logger.info("[SESSION] Attendance state reset. Active session: %s", session_id)


stream_state = VisionServerState()


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
        resp = requests.post(url, json=payload, timeout=2.5)
        if resp.status_code == 200:
            data = resp.json()
            st = data.get("status")
            name = data.get("student_name", identity)
            if st == "marked":
                logger.info(
                    "[ATTENDANCE] ✓ %s marked PRESENT (Identity: %s, Session: %s)",
                    name,
                    identity,
                    session_id or "ACTIVE",
                )
            elif st == "already_present":
                logger.debug("[ATTENDANCE] %s is already marked present", name)
            return True
        elif resp.status_code == 404:
            logger.debug("[ATTENDANCE] Cannot mark attendance: No active session on backend.")
            return False
        else:
            logger.warning("Backend mark error (%d): %s", resp.status_code, resp.text)
            return False
    except Exception as exc:
        logger.warning("Could not dispatch attendance to backend: %s", exc)
        return False


def check_backend_active_session(backend_url: str) -> Optional[dict]:
    """Query FastAPI backend to see if an attendance session is currently active."""
    try:
        url = f"{backend_url.rstrip('/')}/api/v1/attendance/active-session"
        resp = requests.get(url, timeout=1.5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def parse_request_image_and_session(
    headers: Any,
    path: str,
    body: bytes,
) -> tuple[Optional[np.ndarray], Optional[str]]:
    """Robustly parse incoming image frame (Multipart, raw bytes, or JSON base64) and session ID."""
    content_type = headers.get("Content-Type", "")
    session_id = None

    if "?" in path:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
        if "session_id" in qs:
            session_id = qs["session_id"][0]
    if not session_id:
        session_id = headers.get("X-Session-Id")

    img_bgr = None

    # Case 1: JSON payload with base64 image
    if "application/json" in content_type:
        try:
            data = json.loads(body.decode("utf-8"))
            session_id = session_id or data.get("session_id")
            raw_b64 = data.get("image") or data.get("frame") or ""
            if "," in raw_b64:
                raw_b64 = raw_b64.split(",", 1)[1]
            if raw_b64:
                img_bytes = base64.b64decode(raw_b64)
                img_bgr = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
        except Exception:
            return None, None

    # Case 2: Multipart Form Data
    elif "multipart/form-data" in content_type:
        try:
            msg_bytes = f"Content-Type: {content_type}\r\n\r\n".encode("latin1") + body
            msg = email.message_from_bytes(msg_bytes)
            for part in msg.walk():
                cd = part.get("Content-Disposition", "")
                name = ""
                for segment in cd.split(";"):
                    segment = segment.strip()
                    if segment.startswith("name="):
                        name = segment.split("=")[1].strip("\"'")
                if name == "session_id":
                    session_id = part.get_payload().strip()
                elif name in ("frame", "image", "file") or part.get_content_type().startswith(
                    "image/"
                ):
                    payload = part.get_payload(decode=True)
                    if payload:
                        img_bgr = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
        except Exception:
            pass

    # Case 3: Raw image bytes (JPEG / PNG)
    else:
        try:
            if body:
                img_bgr = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
        except Exception:
            pass

    return img_bgr, session_id


class VisionHTTPHandler(BaseHTTPRequestHandler):
    """HTTP server exposing live annotated MJPEG stream, telemetry, and frame-processing endpoints."""

    def log_message(self, format: str, *args) -> None:
        pass

    def _send_cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        allow_origin = "*"
        if origin:
            if "localhost:3000" in origin or "127.0.0.1:3000" in origin:
                allow_origin = origin
            elif "localhost" in origin or "127.0.0.1" in origin:
                allow_origin = origin
            else:
                allow_origin = origin
        self.send_header("Access-Control-Allow-Origin", allow_origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE, HEAD")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, X-Session-Id, X-Access-Token, Accept, Origin, Cache-Control, X-Requested-With",
        )
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Max-Age", "86400")

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?")[0].rstrip("/")

        if path in ("/preview.mjpg", "/preview.mjpeg", "/stream"):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.end_headers()

            while True:
                jpeg = stream_state.get_frame()
                if jpeg is not None:
                    try:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                    except (BrokenPipeError, ConnectionResetError):
                        break
                    time.sleep(0.04)
                else:
                    time.sleep(0.1)

        elif path in ("/status", "/health"):
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
                last_rec = stream_state.last_recognized_student

            cam_connected = cam_active and ((time.time() - last_ft) < 5.0)

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
                "last_recognized": last_rec,
                "last_recognized_student": last_rec,
                "status_message": st_msg,
            }
            body = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        path = self.path.split("?")[0].rstrip("/")

        # Endpoint 1: Process frame from browser
        if path == "/process-frame":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length <= 0:
                self._send_json({"status": "error", "message": "Empty frame body"}, status=400)
                return

            body = self.rfile.read(content_length)
            img_bgr, req_session_id = parse_request_image_and_session(self.headers, self.path, body)

            if img_bgr is None:
                self._send_json(
                    {"status": "error", "message": "Failed to decode image frame"}, status=400
                )
                return

            # Determine target session ID
            target_sess = req_session_id or stream_state.active_session_id

            # Run InsightFace face detection (SCRFD) & recognition (ArcFace)
            app = stream_state.app
            gallery = stream_state.gallery
            sim_thresh = stream_state.similarity_threshold
            min_marg = stream_state.min_margin
            b_url = stream_state.backend_url

            faces = app.get(img_bgr) if app is not None else []

            if not faces:
                stream_state.update_frame(img_bgr)
                self._send_json(
                    {
                        "status": "ok",
                        "detected_faces": 0,
                        "recognized": False,
                        "identity": None,
                        "student_name": None,
                        "status_message": "No face detected",
                    }
                )
                return

            # Select most salient face (largest bounding box)
            best_face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
            feat = getattr(best_face, "normed_embedding", None)
            if feat is None and hasattr(best_face, "embedding"):
                feat = best_face.embedding / (np.linalg.norm(best_face.embedding) + 1e-10)

            best_ident = None
            best_score = -1.0
            runner_up = -1.0

            if feat is not None and gallery:
                for ident, g_feat in gallery.items():
                    score = float(np.dot(feat, g_feat))
                    if score > best_score:
                        runner_up = best_score
                        best_score = score
                        best_ident = ident
                    elif score > runner_up:
                        runner_up = score

            margin = best_score - runner_up if runner_up > 0 else best_score
            is_confirmed = (best_score >= sim_thresh) and (margin >= min_marg)

            bx1, by1, bx2, by2 = [int(v) for v in best_face.bbox]

            if is_confirmed and best_ident:
                student_name = STUDENT_NAME_MAP.get(best_ident, best_ident)
                student_id = STUDENT_ID_MAP.get(best_ident, "")

                with stream_state.lock:
                    already_marked = best_ident in stream_state.marked_identities
                    stream_state.last_recognized_student = student_name

                # If new recognition and active session, dispatch to backend
                if not already_marked and target_sess:
                    ok = post_student_present_to_backend(
                        backend_url=b_url,
                        identity=best_ident,
                        session_id=target_sess,
                    )
                    if ok:
                        with stream_state.lock:
                            stream_state.marked_identities.add(best_ident)

                # Annotate preview with green recognition box
                cv2.rectangle(img_bgr, (bx1, by1), (bx2, by2), (0, 220, 0), 2)
                cv2.putText(
                    img_bgr,
                    f"{student_name} ({best_score:.2f})",
                    (bx1, max(24, by1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 220, 0),
                    2,
                )
                stream_state.update_frame(img_bgr)

                self._send_json(
                    {
                        "status": "ok",
                        "detected_faces": len(faces),
                        "recognized": True,
                        "identity": best_ident,
                        "student_name": student_name,
                        "student_id": student_id,
                        "similarity": round(best_score, 4),
                        "margin": round(margin, 4),
                        "already_marked": already_marked,
                        "status_message": f"{student_name} marked present",
                        "box": [bx1, by1, bx2, by2],
                    }
                )
            else:
                # Face detected but unconfirmed identity
                cv2.rectangle(img_bgr, (bx1, by1), (bx2, by2), (0, 200, 255), 2)
                cv2.putText(
                    img_bgr,
                    "Scanning...",
                    (bx1, max(24, by1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 200, 255),
                    2,
                )
                stream_state.update_frame(img_bgr)

                self._send_json(
                    {
                        "status": "ok",
                        "detected_faces": len(faces),
                        "recognized": False,
                        "identity": "UNKNOWN",
                        "student_name": None,
                        "similarity": round(best_score, 4) if best_score > 0 else 0.0,
                        "status_message": "Scanning for enrolled student...",
                        "box": [bx1, by1, bx2, by2],
                    }
                )

        # Endpoint 2: Reset Session State
        elif path == "/reset":
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
            self._send_json(
                {
                    "status": "reset",
                    "active_session_id": new_sess_id,
                    "present_count": 0,
                }
            )

        # Endpoint 3: Extract photo embedding (Student enrollment)
        elif path == "/extract-embedding":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                from extract_photo_embedding import extract_from_image_bytes

                res = extract_from_image_bytes(body)
            except Exception as exc:
                res = {"status": "error", "message": str(exc)}
            self._send_json(res)

        # Endpoint 4: Reload Gallery
        elif path == "/reload-gallery":
            try:
                npz_path = SERVICE_ROOT / "gallery.npz"
                if npz_path.exists():
                    stream_state.gallery = load_gallery_from_npz(npz_path)
            except Exception:
                pass
            self._send_json(
                {"status": "gallery_reloaded", "enrolled_count": len(stream_state.gallery)}
            )

        else:
            self.send_response(404)
            self.end_headers()

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_preview_server(port: int = 8088) -> Optional[ThreadingHTTPServer]:
    """Start HTTP preview, status, and frame processing server on specified port."""
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), VisionHTTPHandler)
    except OSError as exc:
        logger.error(
            "Port %d is already in use by another process. (%s)",
            port,
            exc,
        )
        return None

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    logger.info("Vision Server listening on http://0.0.0.0:%d/process-frame", port)
    return server


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Face Recognition Attendance System — Browser-Owned Webcam Vision Server"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("VISION_PORT", "8088")),
        help="HTTP server port (default: 8088)",
    )
    parser.add_argument(
        "--backend-url",
        default=os.getenv("BACKEND_URL", "http://127.0.0.1:8000"),
        help="FastAPI backend URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--gallery-npz",
        default=os.getenv("GALLERY_NPZ_PATH", str(SERVICE_ROOT / "gallery.npz")),
        help="Path to precomputed gallery .npz file (default: vision-service/gallery.npz)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Seconds between backend active-session polls (default: 1.0s)",
    )
    args, _ = parser.parse_known_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 1. Preload Face Analysis (SCRFD + ArcFace)
    logger.info("Preloading InsightFace detection (SCRFD) and recognition (ArcFace) into memory...")
    app = create_face_analysis()

    # 2. Load Biometric Gallery
    npz_path = Path(args.gallery_npz)
    if npz_path.exists():
        logger.info("Loading precomputed gallery from %s", npz_path)
        gallery = load_gallery_from_npz(npz_path)
    else:
        bench_dir = SERVICE_ROOT / "tests" / "recognition_benchmark"
        logger.info("Gallery .npz not found; computing from %s", bench_dir)
        gallery = load_gallery(app, bench_dir)

    logger.info(
        "Biometric gallery ready with %d enrolled identities: %s",
        len(gallery),
        list(gallery.keys()),
    )

    # Store in server state
    stream_state.app = app
    stream_state.gallery = gallery
    stream_state.backend_url = args.backend_url
    stream_state.similarity_threshold = 0.50
    stream_state.min_margin = 0.15

    # 3. Start HTTP Server
    server = start_preview_server(port=args.port)
    if server is None:
        logger.warning("Port %d busy. Exiting duplicate vision server instance.", args.port)
        sys.exit(0)

    def _shutdown(sig=None, frame=None):
        logger.info("Shutting down vision server...")
        try:
            server.shutdown()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    print("\n" + "=" * 65)
    print("AI FACE RECOGNITION ATTENDANCE SERVER ACTIVE")
    print("Architecture            : BROWSER-OWNED WEBCAM")
    print("Physical Webcam Access  : Direct from Chrome via getUserMedia()")
    print("Frame Processing API    : http://localhost:{}/process-frame".format(args.port))
    print("Server Status API       : http://localhost:{}/status".format(args.port))
    print("Backend API URL         : {}".format(args.backend_url))
    print("Models Preloaded        : SCRFD + ArcFace (buffalo_l)")
    print("Biometric Gallery       : {} enrolled students".format(len(gallery)))
    print("Standing by for camera frames from browser...")
    print("=" * 65 + "\n")

    # Main thread idle loop: synchronizes active session with backend and serves frames
    last_poll = 0.0
    try:
        while True:
            now = time.time()
            if now - last_poll >= args.poll_interval:
                last_poll = now
                active_meta = check_backend_active_session(args.backend_url)
                if active_meta and active_meta.get("has_active_session"):
                    sess_id = active_meta.get("session_id")
                    if sess_id != stream_state.active_session_id:
                        stream_state.reset_session(sess_id)
                else:
                    if stream_state.active_session_id is not None:
                        stream_state.reset_session(None)
            time.sleep(0.5)
    except KeyboardInterrupt:
        _shutdown()


if __name__ == "__main__":
    main()
