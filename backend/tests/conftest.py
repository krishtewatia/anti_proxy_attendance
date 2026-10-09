"""Shared pytest fixtures for the backend suite."""

import copy
import json
import secrets
import time
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.database import mongodb
from app.database.cameras import create_camera_in_db

TEST_CAMERA_API_KEY = "test-camera-bound-key-2026"
TEST_RECOGNITION_KEY = "test-recognition-signing-key-2026"
TEST_SERVICE_KEY = "test-internal-service-key-2026"
FRAME_BYTES = b"placeholder frame bytes; the vision service call is stubbed in tests"


@pytest.fixture(autouse=True)
def uploads_in_a_temporary_directory(tmp_path_factory, monkeypatch):
    """Send every upload made by a test to a throwaway directory.

    Tests must never write photos into the repository, nor into the real
    uploads volume when the suite is run inside the backend container.
    """
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path_factory.mktemp("uploads")))


TEST_CLASS_CODE = "DS-B"


async def approve_account(user_id: str) -> None:
    """What an administrator's approval does to a registration, without the admin API."""
    await mongodb.get_database()["users"].update_one(
        {"user_id": user_id}, {"$set": {"status": "APPROVED"}}
    )


async def assign_teacher_classes(user_id: str, classes: tuple[str, ...] = (TEST_CLASS_CODE,)) -> None:
    """Give a teacher the classes an administrator would assign; sessions need one."""
    await mongodb.get_database()["teacher_profiles"].update_one(
        {"user_id": user_id},
        {
            "$set": {"user_id": user_id, "assigned_classes": list(classes)},
            "$setOnInsert": {"teacher_id": f"T-{user_id}", "assigned_subjects": []},
        },
        upsert=True,
    )


@pytest.fixture(autouse=True)
def fresh_registration_rate_limit():
    """Each test starts with an empty registration budget (the limiter is process-wide)."""
    from app.api.dependencies.rate_limiter import registration_rate_limiter

    registration_rate_limiter.reset()
    yield
    registration_rate_limiter.reset()


@pytest.fixture
def register_test_camera(monkeypatch):
    """Register cameras in the real camera registry and return their auth headers.

    Usage::

        headers = await register_test_camera("CAM_ROOM_101_DOOR", "ROOM_101")

    The camera document is written through ``create_camera_in_db`` and its
    API key is bound to that camera id, so requests are authenticated by the
    per-camera key path with ``REQUIRE_CAMERA_AUTH`` enabled. Pass ``db`` when
    the test overrides the ``get_database`` dependency with its own database.
    """
    bound_keys: dict[str, str] = {}
    monkeypatch.setattr(settings, "REQUIRE_CAMERA_AUTH", True)

    async def _register(camera_id: str, classroom_id: str, db=None) -> dict[str, str]:
        if db is None:
            db = mongodb.get_database()

        await create_camera_in_db(
            {
                "camera_id": camera_id,
                "classroom_id": classroom_id,
                "role": "BOTH",
                "source_type": "PHONE",
                "enabled": True,
            },
            db=db,
        )

        bound_keys[camera_id] = TEST_CAMERA_API_KEY
        monkeypatch.setattr(settings, "VISION_CAMERA_KEYS", json.dumps(bound_keys))

        return {"X-API-Key": TEST_CAMERA_API_KEY}

    return _register


class _FakeVisionResponse:
    def __init__(self, payload: dict):
        self.status_code = 200
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeVisionClient:
    """Stands in for the vision service HTTP client used during biometric enrollment."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url: str, **kwargs):
        if url.endswith("/extract-embedding"):
            embedding = [0.0] * 512
            embedding[0] = 1.0  # unit-norm 512-d vector, the shape ArcFace returns
            return _FakeVisionResponse({"status": "ok", "embedding": embedding})
        return _FakeVisionResponse({"status": "ok"})


@pytest.fixture
def stub_vision_embedding(monkeypatch):
    """Stub the vision service's embedding call so no face photo is needed.

    No real person's photo is committed to the repo; registration tests upload
    a placeholder JPEG and this fixture answers ``/extract-embedding`` with a
    synthetic 512-d vector. Everything after extraction (biometric profile
    upsert, status flag, gallery sync call) still runs for real.
    """
    from app.services import student_biometric_service

    monkeypatch.setattr(
        student_biometric_service,
        "httpx",
        SimpleNamespace(AsyncClient=_FakeVisionClient),
    )


@pytest.fixture
def service_key_headers(monkeypatch):
    """Configure the internal service key and return headers that present it."""
    monkeypatch.setattr(settings, "VISION_SERVICE_API_KEY", TEST_SERVICE_KEY)
    monkeypatch.setattr(settings, "VISION_SERVICE_API_KEY_HASH", "")
    return {"X-API-Key": TEST_SERVICE_KEY}


@pytest.fixture
def sign_recognition(monkeypatch):
    """Configure the signing key and return a factory for signed recognition results.

    Mirrors what the vision service produces. Keyword overrides let a test
    build expired, mis-keyed or otherwise invalid results.
    """
    from app.services.recognition_service import compute_signature

    monkeypatch.setattr(settings, "RECOGNITION_SIGNING_KEY", TEST_RECOGNITION_KEY)

    def _sign(
        session_id: str,
        identity: str,
        *,
        confidence: float = 0.91,
        issued_at: int | None = None,
        ttl: int = 30,
        nonce: str | None = None,
        key: str = TEST_RECOGNITION_KEY,
        liveness: str = "passed",
    ) -> dict:
        issued = int(time.time()) if issued_at is None else int(issued_at)
        expires = issued + ttl
        token_nonce = nonce or secrets.token_hex(16)
        return {
            "session_id": session_id,
            "identity": identity,
            "confidence": confidence,
            "issued_at": issued,
            "expires_at": expires,
            "nonce": token_nonce,
            "liveness": liveness,
            "signature": compute_signature(
                key, session_id, identity, confidence, issued, expires, token_nonce, liveness
            ),
        }

    return _sign


class _VisionFrameStub:
    """Stands in for the internal vision service on the frame path."""

    def __init__(self, sign):
        self._sign = sign
        self.faces: list[dict] = []
        self.calls: int = 0
        self.error: Exception | None = None

    def recognized(
        self,
        session_id: str,
        identity: str,
        *,
        name: str | None = None,
        similarity: float = 0.91,
        recognition: dict | None | str = "signed",
        **token_overrides,
    ) -> dict:
        """A confirmed face. By default it carries a valid signed result for the session."""
        if recognition == "signed":
            recognition = self._sign(session_id, identity, confidence=similarity, **token_overrides)
        return {
            "bbox": [10, 10, 110, 110],
            "identity": identity,
            "student_id": identity,
            "name": name or identity,
            "similarity": similarity,
            "status": "recognized",
            "recognition": recognition,
        }

    @staticmethod
    def unknown(similarity: float = 0.2) -> dict:
        return {
            "bbox": [10, 10, 110, 110],
            "identity": None,
            "student_id": None,
            "name": "UNKNOWN",
            "similarity": similarity,
            "status": "unknown",
        }


@pytest.fixture
def vision_frames(monkeypatch, sign_recognition):
    """Stub the backend's call to the vision service and reset the frame rate limiters.

    Set ``vision_frames.faces`` to what the vision service should return for
    the next frame.
    """
    from app.api.dependencies.rate_limiter import (
        frame_session_rate_limiter,
        frame_teacher_rate_limiter,
    )

    stub = _VisionFrameStub(sign_recognition)

    async def _fake_forward(frame_bytes: bytes, content_type: str, session_id: str) -> dict:
        stub.calls += 1
        if stub.error is not None:
            raise stub.error
        return {
            "status": "ok",
            "frame_width": 640,
            "frame_height": 480,
            "faces": copy.deepcopy(stub.faces),
        }

    monkeypatch.setattr("app.api.routes.attendance.forward_frame_to_vision", _fake_forward)
    frame_session_rate_limiter.reset()
    frame_teacher_rate_limiter.reset()
    yield stub
    frame_session_rate_limiter.reset()
    frame_teacher_rate_limiter.reset()
