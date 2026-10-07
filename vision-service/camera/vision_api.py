"""Internal HTTP API of the vision service.

Called only by the backend over the internal network. Every route except
/health requires the shared service key. The service recognizes faces in a
single frame, returns signed recognition results, and extracts embeddings at
enrollment. It never marks attendance and never serves a browser.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import threading
import time
from typing import Any, Optional

from aiohttp import web
import numpy as np

from camera.liveness import (
    DEFAULT_LIVENESS_MODE,
    STATUS_LIVE,
    STATUS_SPOOF,
    LivenessChecker,
    evaluate_liveness_gate,
)
from camera.recognition_signing import sign_recognition

logger = logging.getLogger(__name__)


GALLERY_REFRESH_SECONDS = 30.0


def make_cors_headers(origin: Optional[str] = None) -> dict[str, str]:
    """No CORS headers: the service is called only by the backend, never by a browser."""
    return {}


@web.middleware
async def service_auth_middleware(request: web.Request, handler):
    """Require the shared service key on every route except the liveness probe.

    Fail closed: if no key is configured, nothing but /health is served.
    """
    if request.path != "/health":
        expected = os.getenv("VISION_SERVICE_API_KEY", "").strip()
        presented = request.headers.get("X-API-Key", "").strip()
        if (
            not expected
            or not presented
            or not hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))
        ):
            logger.warning("Rejected unauthenticated request to %s", request.path)
            return web.json_response({"error": "unauthorized"}, status=401)

    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception:
        logger.exception("Error processing request %s", request.path)
        return web.json_response({"error": "internal error"}, status=500)


class VisionApiServer:
    """Key-protected internal HTTP API: frame recognition, embedding extraction, gallery sync."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8088,
        backend_url: Optional[str] = None,
        similarity_threshold: float = 0.50,
        min_margin: float = 0.15,
        liveness_mode: str = DEFAULT_LIVENESS_MODE,
        liveness_checker: Optional[LivenessChecker] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.backend_url = backend_url
        self.similarity_threshold = similarity_threshold
        self.min_margin = min_margin
        # Liveness gate: runs on a recognized face before its result is signed.
        self.liveness_mode = liveness_mode
        self.liveness_checker = liveness_checker

        self._face_app: Optional[Any] = None
        self.latest_frame_time: float = 0.0
        self.active_session_id: Optional[str] = None
        self.last_recognized_student: Optional[str] = None

        self.gallery: dict[str, np.ndarray] = {}
        # Names and student ids come only from the backend's student records
        # (gallery sync and enrollment calls); nothing is built in.
        self.student_names: dict[str, str] = {}
        self.student_ids: dict[str, str] = {}
        self._last_gallery_sync: float = 0.0

        # Every route below except /health requires the service key.
        self.app = web.Application(
            middlewares=[service_auth_middleware], client_max_size=32 * 1024 * 1024
        )
        self.app.router.add_post("/process-frame", self._handle_process_frame)
        self.app.router.add_post("/reset", self._handle_reset)
        self.app.router.add_post("/extract-embedding", self._handle_extract_embedding)
        self.app.router.add_post("/enroll-student", self._handle_enroll_student)
        self.app.router.add_post("/reload-gallery", self._handle_reload_gallery)
        self.app.router.add_get("/gallery", self._handle_get_gallery)
        self.app.router.add_get("/status", self._handle_status)
        self.app.router.add_get("/health", self._handle_health)

        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event = threading.Event()

    def _is_authorized(self, request: web.Request) -> bool:
        """Requests reaching a handler already passed service_auth_middleware."""
        return True

    async def _handle_reset(self, request: web.Request) -> web.Response:
        new_sess_id = None
        try:
            data = await request.json()
            new_sess_id = data.get("session_id")
        except Exception:
            pass
        self.active_session_id = new_sess_id
        self.last_recognized_student = None
        return web.json_response(
            {"status": "reset", "active_session_id": new_sess_id, "present_count": 0},
        )

    def set_face_app(self, face_app: Any) -> None:
        """Use an already loaded InsightFace FaceAnalysis instance."""
        self._face_app = face_app

    def _get_app(self) -> Any:
        if self._face_app is None:
            try:
                from pipeline.live_cv_pipeline import create_face_analysis

                self._face_app = create_face_analysis()
            except Exception as exc:
                logger.warning("Could not initialize face analysis: %s", exc)
        return self._face_app

    def _get_gallery(self) -> dict[str, np.ndarray]:
        """The gallery holds only what the backend sent; nothing is loaded from a file."""
        return self.gallery

    async def _sync_from_backend(self, backend_url: str) -> bool:
        import aiohttp

        url = f"{backend_url.rstrip('/')}/api/v1/attendance/vision-gallery"
        try:
            service_key = os.getenv("VISION_SERVICE_API_KEY", "").strip()
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={"X-API-Key": service_key},
                    timeout=aiohttp.ClientTimeout(total=4.0),
                ) as resp:
                    self._last_gallery_sync = time.time()
                    if resp.status == 200:
                        data = await resp.json()
                        gallery_list = data.get("gallery", [])
                        new_gallery = {}
                        new_names = {}
                        new_ids = {}
                        for item in gallery_list:
                            ident = item.get("identity")
                            name = item.get("name") or ident
                            stu_id = item.get("student_id") or ident
                            emb = item.get("embedding")
                            if ident and emb:
                                vec = np.array(emb, dtype=np.float32)
                                norm = np.linalg.norm(vec)
                                if norm > 1e-6:
                                    vec = vec / norm
                                new_gallery[ident] = vec
                                new_names[ident] = name
                                new_ids[ident] = stu_id
                        self.gallery = new_gallery
                        self.student_names = new_names
                        self.student_ids = new_ids
                        logger.info(
                            "Successfully synced %d identities from backend", len(gallery_list)
                        )
                        return True
        except Exception as exc:
            self._last_gallery_sync = time.time()
            logger.warning("Could not sync gallery from backend (%s): %s", url, exc)
        return False

    def _backend_url(self) -> str:
        return self.backend_url or os.getenv("BACKEND_URL", "http://backend:8000")

    async def _refresh_gallery_if_stale(self) -> None:
        """Re-sync from the backend when the gallery is empty or older than the refresh window."""
        age = time.time() - self._last_gallery_sync
        if age >= GALLERY_REFRESH_SECONDS or (not self.gallery and age >= 2.0):
            await self._sync_from_backend(self._backend_url())

    async def _handle_extract_embedding(self, request: web.Request) -> web.Response:
        import base64
        import cv2
        import numpy as np

        origin = request.headers.get("Origin")
        cors_headers = make_cors_headers(origin)

        content_type = request.content_type or ""
        img_bgr = None

        if "application/json" in content_type:
            try:
                data = await request.json()
                raw_b64 = data.get("image") or data.get("photo_base64") or data.get("frame") or ""
                if "," in raw_b64:
                    raw_b64 = raw_b64.split(",", 1)[1]
                if raw_b64:
                    img_bytes = base64.b64decode(raw_b64)
                    img_bgr = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
            except Exception as exc:
                logger.warning("Failed decoding json image: %s", exc)
        elif "multipart/form-data" in content_type:
            try:
                reader = await request.multipart()
                while True:
                    part = await reader.next()
                    if part is None:
                        break
                    if part.name in ("image", "file", "photo", "frame"):
                        raw_bytes = await part.read()
                        img_bgr = cv2.imdecode(np.frombuffer(raw_bytes, np.uint8), cv2.IMREAD_COLOR)
            except Exception as exc:
                logger.warning("Failed decoding multipart image: %s", exc)
        else:
            try:
                raw_bytes = await request.read()
                if raw_bytes:
                    img_bgr = cv2.imdecode(np.frombuffer(raw_bytes, np.uint8), cv2.IMREAD_COLOR)
            except Exception as exc:
                logger.warning("Failed decoding raw image: %s", exc)

        if img_bgr is None:
            return web.json_response(
                {"status": "error", "message": "Failed to decode image data"},
                status=400,
                headers=cors_headers,
            )

        app = self._get_app()
        if app is None:
            return web.json_response(
                {"status": "error", "message": "InsightFace models not loaded"},
                status=503,
                headers=cors_headers,
            )

        faces = app.get(img_bgr)
        if not faces:
            return web.json_response(
                {
                    "status": "no_face",
                    "message": "No face detected in photo. Please ensure face is clearly visible.",
                },
                status=200,
                headers=cors_headers,
            )

        best_face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        feat = getattr(best_face, "normed_embedding", None)
        if feat is None and hasattr(best_face, "embedding"):
            feat = best_face.embedding / (np.linalg.norm(best_face.embedding) + 1e-10)

        if feat is None:
            return web.json_response(
                {"status": "error", "message": "Failed to extract embedding vector"},
                status=500,
                headers=cors_headers,
            )

        det_score = float(best_face.det_score) if hasattr(best_face, "det_score") else 1.0

        return web.json_response(
            {
                "status": "ok",
                "embedding": feat.tolist(),
                "det_score": det_score,
                "bbox": [int(v) for v in best_face.bbox],
            },
            headers=cors_headers,
        )

    async def _handle_enroll_student(self, request: web.Request) -> web.Response:
        origin = request.headers.get("Origin")
        cors_headers = make_cors_headers(origin)
        try:
            data = await request.json()
            identity = data.get("identity")
            name = data.get("name") or identity
            student_id = data.get("student_id") or identity
            embedding = data.get("embedding")
            if not identity or not embedding:
                return web.json_response(
                    {"status": "error", "message": "Missing identity or embedding"},
                    status=400,
                    headers=cors_headers,
                )

            vec = np.array(embedding, dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm > 1e-6:
                vec = vec / norm

            self.gallery[identity] = vec
            self.student_names[identity] = name
            self.student_ids[identity] = student_id

            logger.info(
                "Enrolled student %s (%s) into live gallery. Total identities: %d",
                name,
                identity,
                len(self.gallery),
            )
            return web.json_response(
                {
                    "status": "ok",
                    "enrolled": identity,
                    "name": name,
                    "total_gallery": len(self.gallery),
                },
                headers=cors_headers,
            )
        except Exception as exc:
            logger.exception("Enroll student failed: %s", exc)
            return web.json_response(
                {"status": "error", "message": str(exc)}, status=500, headers=cors_headers
            )

    async def _handle_reload_gallery(self, request: web.Request) -> web.Response:
        origin = request.headers.get("Origin")
        cors_headers = make_cors_headers(origin)
        try:
            data = None
            try:
                data = await request.json()
            except Exception:
                pass

            if data and "gallery" in data:
                for item in data["gallery"]:
                    ident = item.get("identity")
                    name = item.get("name") or ident
                    stu_id = item.get("student_id") or ident
                    emb = item.get("embedding")
                    if ident and emb:
                        vec = np.array(emb, dtype=np.float32)
                        norm = np.linalg.norm(vec)
                        if norm > 1e-6:
                            vec = vec / norm
                        self.gallery[ident] = vec
                        self.student_names[ident] = name
                        self.student_ids[ident] = stu_id
                return web.json_response(
                    {
                        "status": "gallery_reloaded",
                        "enrolled_count": len(self.gallery),
                        "identities": list(self.gallery.keys()),
                    },
                    headers=cors_headers,
                )

            synced = await self._sync_from_backend(self._backend_url())
            return web.json_response(
                {
                    "status": "gallery_reloaded",
                    "synced_from_backend": synced,
                    "enrolled_count": len(self.gallery),
                    "identities": list(self.gallery.keys()),
                },
                headers=cors_headers,
            )
        except Exception as exc:
            logger.exception("Reload gallery error: %s", exc)
            return web.json_response(
                {"status": "error", "message": str(exc)}, status=500, headers=cors_headers
            )

    async def _handle_get_gallery(self, request: web.Request) -> web.Response:
        origin = request.headers.get("Origin")
        cors_headers = make_cors_headers(origin)
        gallery = self._get_gallery()
        items = [
            {
                "identity": k,
                "name": self.student_names.get(k, k),
                "student_id": self.student_ids.get(k, k),
            }
            for k in gallery.keys()
        ]
        return web.json_response(
            {
                "count": len(items),
                "students": items,
            },
            headers=cors_headers,
        )

    async def _handle_process_frame(self, request: web.Request) -> web.Response:
        import base64
        import cv2
        import numpy as np

        origin = request.headers.get("Origin")
        headers = make_cors_headers(origin)
        content_type = request.content_type or ""
        req_session_id = request.query.get("session_id") or request.headers.get("X-Session-Id")
        img_bgr = None

        if "application/json" in content_type:
            try:
                data = await request.json()
                req_session_id = req_session_id or data.get("session_id")
                raw_b64 = data.get("image") or data.get("frame") or ""
                if "," in raw_b64:
                    raw_b64 = raw_b64.split(",", 1)[1]
                if raw_b64:
                    img_bytes = base64.b64decode(raw_b64)
                    img_bgr = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
            except Exception:
                pass
        elif "multipart/form-data" in content_type:
            try:
                reader = await request.multipart()
                while True:
                    part = await reader.next()
                    if part is None:
                        break
                    if part.name == "session_id":
                        req_session_id = (await part.text()).strip()
                    elif part.name in ("frame", "image", "file"):
                        raw_bytes = await part.read()
                        img_bgr = cv2.imdecode(np.frombuffer(raw_bytes, np.uint8), cv2.IMREAD_COLOR)
            except Exception:
                pass
        else:
            try:
                raw_bytes = await request.read()
                if raw_bytes:
                    img_bgr = cv2.imdecode(np.frombuffer(raw_bytes, np.uint8), cv2.IMREAD_COLOR)
            except Exception:
                pass

        if img_bgr is None:
            return web.json_response(
                {"status": "error", "message": "Failed to decode image frame"},
                status=400,
                headers=headers,
            )

        target_sess = req_session_id or self.active_session_id
        frame_h, frame_w = img_bgr.shape[:2]

        app = self._get_app()
        await self._refresh_gallery_if_stale()
        gallery = self._get_gallery()
        signing_key = os.getenv("RECOGNITION_SIGNING_KEY", "").strip()

        if app is None:
            return web.json_response(
                {"status": "error", "message": "Vision pipeline not initialized"},
                status=503,
                headers=headers,
            )

        faces = app.get(img_bgr)
        self.latest_frame_time = time.time()
        if not faces:
            return web.json_response(
                {
                    "status": "ok",
                    "detected_faces": 0,
                    "recognized": False,
                    "identity": None,
                    "student_name": None,
                    "student_id": None,
                    "similarity": 0.0,
                    "margin": 0.0,
                    "already_marked": False,
                    "status_message": "No face detected",
                    "box": None,
                    "frame_width": frame_w,
                    "frame_height": frame_h,
                    "faces": [],
                },
                headers=headers,
            )

        sim_thresh = self.similarity_threshold
        min_marg = self.min_margin

        faces_output = []

        for face in faces:
            bx1, by1, bx2, by2 = [int(v) for v in face.bbox]
            feat = getattr(face, "normed_embedding", None)
            if feat is None and hasattr(face, "embedding"):
                feat = face.embedding / (np.linalg.norm(face.embedding) + 1e-10)

            best_ident = None
            best_score = -1.0
            runner_up = -1.0

            if feat is not None and gallery:
                for ident, g_feat in gallery.items():
                    score = float(np.dot(feat, g_feat))
                    ident_stu_id = self.student_ids.get(ident, ident)
                    ident_stu_name = self.student_names.get(ident, ident)
                    if score > best_score:
                        if best_ident:
                            prev_id = self.student_ids.get(best_ident, best_ident)
                            prev_name = self.student_names.get(best_ident, best_ident)
                            if ident_stu_id != prev_id and ident_stu_name != prev_name:
                                runner_up = best_score
                        best_score = score
                        best_ident = ident
                    elif score > runner_up:
                        if best_ident:
                            best_id = self.student_ids.get(best_ident, best_ident)
                            best_name = self.student_names.get(best_ident, best_ident)
                            if ident_stu_id != best_id and ident_stu_name != best_name:
                                runner_up = score

            margin = best_score - runner_up if runner_up > 0 else best_score
            is_confirmed = (best_score >= sim_thresh) and (margin >= min_marg)
            det_score = float(getattr(face, "det_score", 1.0))

            if is_confirmed and best_ident:
                student_name = self.student_names.get(best_ident, best_ident)
                student_id = self.student_ids.get(best_ident, best_ident)
                self.last_recognized_student = student_name

                conf_pct = round(best_score * 100, 1)

                # Liveness gate, before anything is signed. A face that fails it
                # in enforce mode never produces a signed result.
                decision = evaluate_liveness_gate(
                    self.liveness_mode, self.liveness_checker, img_bgr, face.bbox
                )
                liveness = decision.result
                liveness_info = {
                    "status": liveness.status,
                    "score": round(liveness.score, 3) if liveness.score is not None else None,
                    "mode": self.liveness_mode,
                }
                if liveness.status != STATUS_LIVE:
                    # Identifiers and the score only: never image data or embeddings.
                    logger.warning(
                        "Liveness %s: session=%s identity=%s score=%s reason=%s mode=%s signed=%s",
                        liveness.status,
                        target_sess,
                        best_ident,
                        liveness_info["score"],
                        liveness.reason,
                        self.liveness_mode,
                        decision.allow_signing,
                    )

                if not decision.allow_signing:
                    faces_output.append(
                        {
                            "bbox": [bx1, by1, bx2, by2],
                            "identity": best_ident,
                            "student_id": student_id,
                            "name": student_name,
                            "similarity": round(best_score, 4),
                            "confidence_percent": conf_pct,
                            "det_score": round(det_score, 3),
                            "status": (
                                "spoof"
                                if liveness.status == STATUS_SPOOF
                                else "liveness_unavailable"
                            ),
                            "already_marked": False,
                            "liveness": liveness_info,
                        }
                    )
                    continue

                # This service never marks attendance. It returns a signed result
                # bound to the session; the backend verifies it and decides.
                recognition = None
                if target_sess and signing_key:
                    recognition = sign_recognition(
                        session_id=target_sess,
                        identity=best_ident,
                        confidence=best_score,
                        key=signing_key,
                        liveness=decision.attestation,
                    )

                faces_output.append(
                    {
                        "bbox": [bx1, by1, bx2, by2],
                        "identity": best_ident,
                        "student_id": student_id,
                        "name": student_name,
                        "similarity": round(best_score, 4),
                        "confidence_percent": conf_pct,
                        "det_score": round(det_score, 3),
                        "status": "recognized",
                        "already_marked": False,
                        "liveness": liveness_info,
                        "recognition": recognition,
                    }
                )

            else:
                conf_pct = round(best_score * 100, 1) if best_score > 0 else 0.0
                faces_output.append(
                    {
                        "bbox": [bx1, by1, bx2, by2],
                        "identity": None,
                        "student_id": None,
                        "name": "UNKNOWN",
                        "similarity": round(best_score, 4) if best_score > 0 else 0.0,
                        "confidence_percent": conf_pct,
                        "det_score": round(det_score, 3),
                        "status": "unknown",
                        "already_marked": False,
                    }
                )

        recognized_faces = [f for f in faces_output if f["status"] == "recognized"]
        if recognized_faces:
            top_face = max(recognized_faces, key=lambda f: f["similarity"])
            return web.json_response(
                {
                    "status": "ok",
                    "detected_faces": len(faces),
                    "recognized": True,
                    "identity": top_face["identity"],
                    "student_name": top_face["name"],
                    "student_id": top_face["student_id"],
                    "similarity": top_face["similarity"],
                    "margin": round(margin, 4),
                    "already_marked": top_face["already_marked"],
                    "status_message": f"{top_face['name']} recognized",
                    "box": top_face["bbox"],
                    "frame_width": frame_w,
                    "frame_height": frame_h,
                    "faces": faces_output,
                },
                headers=headers,
            )
        else:
            primary_face = faces_output[0]
            return web.json_response(
                {
                    "status": "ok",
                    "detected_faces": len(faces),
                    "recognized": False,
                    "identity": "UNKNOWN",
                    "student_name": None,
                    "student_id": None,
                    "similarity": primary_face["similarity"],
                    "margin": 0.0,
                    "already_marked": False,
                    "status_message": "Scanning for enrolled student...",
                    "box": primary_face["bbox"],
                    "frame_width": frame_w,
                    "frame_height": frame_h,
                    "faces": faces_output,
                },
                headers=headers,
            )

    async def _handle_status(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "online",
                "service": "vision-api",
                "active_session_id": self.active_session_id,
                "gallery_size": len(self.gallery),
                "models_loaded": self._face_app is not None,
                "liveness_mode": self.liveness_mode,
                "liveness_model_loaded": self.liveness_checker is not None,
                "last_recognized_student": self.last_recognized_student,
                "last_frame_age_seconds": (
                    round(time.time() - self.latest_frame_time, 2)
                    if self.latest_frame_time > 0
                    else None
                ),
            }
        )

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "healthy", "service": "vision-api"})

    def start_background(self) -> None:
        """Start the API server in a background daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        ready_event = threading.Event()

        def run_server():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            async def _start():
                self._runner = web.AppRunner(self.app)
                await self._runner.setup()
                self._site = web.TCPSite(self._runner, self.host, self.port)
                await self._site.start()
                logger.info("Vision API listening on http://%s:%d", self.host, self.port)
                ready_event.set()

                async def _delayed_sync():
                    await asyncio.sleep(2.0)
                    await self._sync_from_backend(self._backend_url())

                self._loop.create_task(_delayed_sync())

            self._loop.run_until_complete(_start())
            try:
                self._loop.run_forever()
            finally:
                self._loop.run_until_complete(self._cleanup())
                self._loop.close()

        self._thread = threading.Thread(target=run_server, daemon=True, name="VisionApiServer")
        self._thread.start()
        ready_event.wait(timeout=5.0)

    async def _cleanup(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()

    def stop(self) -> None:
        """Stop the background API server and release resources."""
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
