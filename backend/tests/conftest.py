"""Shared pytest fixtures for the backend suite."""

import json
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.database import mongodb
from app.database.cameras import create_camera_in_db

TEST_CAMERA_API_KEY = "test-camera-bound-key-2026"


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
                "source_type": "WEBRTC",
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
