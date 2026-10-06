"""Shared pytest fixtures for the backend suite."""

import json

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
