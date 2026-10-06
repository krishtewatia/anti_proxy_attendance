"""Student Biometric Registration & ArcFace Embedding Integration Service."""

import base64
import json
import logging
import os
from pathlib import Path
import subprocess
import httpx

from app.database.biometric_profiles import upsert_biometric_profile
from app.database.student_profiles import update_biometric_status

logger = logging.getLogger(__name__)

VISION_HTTP_URL = os.getenv("VISION_SERVICE_URL", "http://127.0.0.1:8088")
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
VISION_VENV_PYTHON = PROJECT_ROOT / "vision-service" / ".venv" / "Scripts" / "python.exe"
VISION_EXTRACT_SCRIPT = PROJECT_ROOT / "vision-service" / "extract_photo_embedding.py"

from app.core.config import UPLOADS_DIR


def get_vision_service_urls() -> list[str]:
    configured = os.getenv("VISION_SERVICE_URL")
    urls = []
    if configured:
        urls.append(configured.rstrip("/"))
    for candidate in [
        "http://vision-service:8088",
        "http://127.0.0.1:8088",
        "http://localhost:8088",
    ]:
        if candidate not in urls:
            urls.append(candidate)
    return urls


async def extract_and_register_student_photo(
    identity: str,
    photo_base64: str,
    enrolled_by: str = "self",
    student_name: str | None = None,
    student_id: str | None = None,
) -> tuple[bool, str]:
    """Process student photo, persist original file, extract real ArcFace embedding, and sync with vision gallery."""
    try:
        raw_b64 = photo_base64.strip()
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]
        img_bytes = base64.b64decode(raw_b64)
    except Exception as exc:
        logger.error("Failed to decode base64 photo for %s: %s", identity, exc)
        return False, f"Invalid photo format: {exc}"

    # 1. Persist original student photograph to persistent local storage
    try:
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        photo_path = UPLOADS_DIR / f"{identity}.jpg"
        photo_path.write_bytes(img_bytes)
        logger.info("Persisted profile photo for student '%s' to %s", identity, photo_path)
    except Exception as io_err:
        logger.warning(
            "Could not persist student photo file on disk for '%s': %s", identity, io_err
        )

    embedding: list[float] | None = None
    extraction_source = "none"

    # 2. Try Vision Service HTTP Endpoints (with generous timeout for ONNX face detection)
    candidate_urls = get_vision_service_urls()
    for v_url in candidate_urls:
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(
                    f"{v_url}/extract-embedding",
                    content=img_bytes,
                    headers={"Content-Type": "image/jpeg"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "no_face":
                        return False, data.get(
                            "message",
                            "No face detected in photo. Please ensure face is clearly visible.",
                        )
                    if data.get("status") == "ok" and data.get("embedding"):
                        embedding = data["embedding"]
                        extraction_source = f"vision_http ({v_url})"
                        break
        except Exception as exc:
            logger.debug("Vision HTTP endpoint %s unreachable: %s", v_url, exc)
            continue

    # 3. Try Vision-Service VirtualEnv subprocess if HTTP failed
    if embedding is None and VISION_VENV_PYTHON.exists() and VISION_EXTRACT_SCRIPT.exists():
        try:
            import tempfile

            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(img_bytes)
                tmp_path = tmp.name

            proc = subprocess.run(
                [str(VISION_VENV_PYTHON), str(VISION_EXTRACT_SCRIPT), "--image-path", tmp_path],
                capture_output=True,
                text=True,
                timeout=25,
                check=False,
            )
            try:
                os.remove(tmp_path)
            except OSError:
                pass

            if proc.returncode == 0 and proc.stdout:
                parsed = json.loads(proc.stdout.strip())
                if parsed.get("status") == "no_face":
                    return False, parsed.get(
                        "message",
                        "No face detected in photo. Please ensure face is clearly visible.",
                    )
                if parsed.get("status") == "ok" and parsed.get("embedding"):
                    embedding = parsed["embedding"]
                    extraction_source = "vision_subprocess"
        except Exception as exc:
            logger.warning("Vision subprocess extraction failed: %s", exc)

    # NO FAKE FALLBACK: Biometric enrollment must only succeed if real face embedding is extracted
    if embedding is None:
        logger.error(
            "Failed to extract face embedding for student '%s'. Vision service unavailable or no face detected.",
            identity,
        )
        return (
            False,
            "Could not extract face embedding from uploaded photo. Please upload a clear frontal face image.",
        )

    # Upsert into biometric_profiles collection in MongoDB
    await upsert_biometric_profile(
        identity=identity,
        mean_embedding=embedding,
        sample_count=1,
        quality_score=0.95,
        enrolled_by=enrolled_by,
    )

    # Update student profile has_biometric flag
    await update_biometric_status(identity=identity, has_biometric=True)

    # Synchronize student into live vision service gallery
    enrolled_in_vision = False
    for v_url in candidate_urls:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                enroll_resp = await client.post(
                    f"{v_url}/enroll-student",
                    json={
                        "identity": identity,
                        "name": student_name or identity,
                        "student_id": student_id or identity,
                        "embedding": embedding,
                    },
                )
                if enroll_resp.status_code == 200:
                    enrolled_in_vision = True
                    logger.info(
                        "Successfully enrolled student '%s' into vision service at %s",
                        identity,
                        v_url,
                    )
                    break
        except Exception:
            continue

    if not enrolled_in_vision:
        for v_url in candidate_urls:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(f"{v_url}/reload-gallery")
                    break
            except Exception:
                pass

    logger.info("Student '%s' biometric profile registered via %s", identity, extraction_source)
    return True, f"Biometric registered via {extraction_source}"
