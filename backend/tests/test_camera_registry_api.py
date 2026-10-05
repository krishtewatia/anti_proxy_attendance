"""Integration and unit tests for Camera Registry, RBAC, Credential Non-Leak, and Heartbeat."""

import json
from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.core.config import settings
from app.database import get_database, init_indexes, mongodb
from app.database.users import create_user
from app.main import app
from app.schemas.camera import CameraRole, CameraSourceType, CameraStatus, mask_rtsp_url
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from app.services.session_resolution_service import resolve_classroom_for_camera_db


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def mock_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await init_indexes(db)
    return db


@pytest.fixture
async def api_client(mock_db, monkeypatch):
    app.dependency_overrides[get_database] = lambda: mock_db

    monkeypatch.setattr(settings, "REQUIRE_CAMERA_AUTH", True)
    monkeypatch.setattr(settings, "VISION_SERVICE_API_KEY", "vision-secret-key-12345")
    monkeypatch.setattr(settings, "VISION_SERVICE_API_KEY_HASH", "")
    monkeypatch.setattr(
        settings,
        "VISION_CAMERA_KEYS",
        json.dumps({"CAM_BOUND_01": "camera-01-bound-secret"}),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def admin_auth(mock_db):
    admin_id = "admin_user_cam_01"
    await create_user(
        user_id=admin_id,
        email="admin_cam@university.edu",
        password_hash=hash_password("AdminPass123!"),
        role="ADMIN",
    )
    token = create_access_token(user_id=admin_id, role="ADMIN")
    return {"user_id": admin_id, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture
async def teacher_auth(mock_db):
    teacher_id = "teacher_cam_01"
    await create_user(
        user_id=teacher_id,
        email="teacher_cam@university.edu",
        password_hash=hash_password("TeacherPass123!"),
        role="TEACHER",
    )
    token = create_access_token(user_id=teacher_id, role="TEACHER")
    return {"user_id": teacher_id, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture
async def student_auth(mock_db):
    student_id = "student_cam_01"
    await create_user(
        user_id=student_id,
        email="student_cam@university.edu",
        password_hash=hash_password("StudentPass123!"),
        role="STUDENT",
    )
    token = create_access_token(user_id=student_id, role="STUDENT")
    return {"user_id": student_id, "headers": {"Authorization": f"Bearer {token}"}}


def test_mask_rtsp_url_utility():
    """Verify mask_rtsp_url cleanly replaces credentials."""
    assert mask_rtsp_url(None) is None
    assert mask_rtsp_url("") is None
    assert mask_rtsp_url("rtsp://192.168.1.10:554/live") == "rtsp://192.168.1.10:554/live"
    assert mask_rtsp_url("rtsp://admin:pass123@192.168.1.10:554/live") == "rtsp://admin:*****@192.168.1.10:554/live"
    assert mask_rtsp_url("rtsp://user:secret@localhost/stream") == "rtsp://user:*****@localhost/stream"


@pytest.mark.anyio
async def test_camera_crud_admin_and_rbac(mock_db, api_client, admin_auth, teacher_auth, student_auth):
    """Verify CRUD endpoints respect RBAC and enforce Admin permissions for mutations."""
    cam_payload = {
        "camera_id": "CAM_ROOM_301_ENTRY",
        "classroom_id": "ROOM_301",
        "role": "ENTRY",
        "source_type": "RTSP",
        "rtsp_url": "rtsp://admin:super_secret_password@10.0.0.50:554/h264",
        "secret_reference": "CAM_ROOM_301_SECRET",
        "enabled": True,
        "boundary_config": {
            "line_start": [0.0, 0.5],
            "line_end": [1.0, 0.5],
            "entry_side": "bottom",
            "deadband_px": 12.0,
        },
    }

    # 1. Non-admin cannot create camera
    res = await api_client.post("/api/v1/cameras", json=cam_payload, headers=teacher_auth["headers"])
    assert res.status_code == 403

    res = await api_client.post("/api/v1/cameras", json=cam_payload, headers=student_auth["headers"])
    assert res.status_code == 403

    # 2. Admin creates camera successfully
    res = await api_client.post("/api/v1/cameras", json=cam_payload, headers=admin_auth["headers"])
    assert res.status_code == 201
    data = res.json()
    assert data["camera_id"] == "CAM_ROOM_301_ENTRY"
    assert data["classroom_id"] == "ROOM_301"
    assert data["role"] == "ENTRY"

    # SECURITY: Credential non-leak check in response
    assert "super_secret_password" not in json.dumps(data)
    assert data["rtsp_url_masked"] == "rtsp://admin:*****@10.0.0.50:554/h264"
    assert "rtsp_url" not in data

    # SECURITY: Verify audit log recorded without credential leak
    audit = await mock_db["audit_events"].find_one({
        "resource_type": "CAMERA",
        "resource_id": "CAM_ROOM_301_ENTRY",
        "action": "CAMERA_CREATED",
    })
    assert audit is not None
    assert audit["actor_user_id"] == admin_auth["user_id"]
    assert "super_secret_password" not in json.dumps(audit["metadata"])
    assert audit["metadata"]["rtsp_url_masked"] == "rtsp://admin:*****@10.0.0.50:554/h264"

    # 3. Duplicate creation rejected with 409
    dup_res = await api_client.post("/api/v1/cameras", json=cam_payload, headers=admin_auth["headers"])
    assert dup_res.status_code == 409

    # 4. Teacher and Admin can view camera list
    res_list = await api_client.get("/api/v1/cameras", headers=teacher_auth["headers"])
    assert res_list.status_code == 200
    items = res_list.json()
    assert len(items) == 1
    assert items[0]["camera_id"] == "CAM_ROOM_301_ENTRY"
    assert "super_secret_password" not in json.dumps(items)

    # Student cannot list cameras
    res_stud = await api_client.get("/api/v1/cameras", headers=student_auth["headers"])
    assert res_stud.status_code == 403

    # 5. Admin updates camera (e.g. role and new RTSP URL)
    update_payload = {
        "role": "BOTH",
        "rtsp_url": "rtsp://operator:another_secret@10.0.0.50:554/live",
        "notes": "Upgraded to bidirectional doorway",
    }
    res_patch = await api_client.patch(
        "/api/v1/cameras/CAM_ROOM_301_ENTRY",
        json=update_payload,
        headers=admin_auth["headers"],
    )
    assert res_patch.status_code == 200
    updated_data = res_patch.json()
    assert updated_data["role"] == "BOTH"
    assert updated_data["notes"] == "Upgraded to bidirectional doorway"
    assert updated_data["rtsp_url_masked"] == "rtsp://operator:*****@10.0.0.50:554/live"
    assert "another_secret" not in json.dumps(updated_data)

    # 6. Admin deletes camera
    res_del = await api_client.delete("/api/v1/cameras/CAM_ROOM_301_ENTRY", headers=admin_auth["headers"])
    assert res_del.status_code == 200

    # Subsequent GET yields 404
    res_get = await api_client.get("/api/v1/cameras/CAM_ROOM_301_ENTRY", headers=admin_auth["headers"])
    assert res_get.status_code == 404


@pytest.mark.anyio
async def test_camera_heartbeat_and_telemetry(mock_db, api_client, admin_auth, teacher_auth):
    """Verify service-authenticated heartbeat recording and dashboard health telemetry."""
    # Pre-register two cameras
    cam_1 = {
        "camera_id": "CAM_ROOM_401_DOOR",
        "classroom_id": "ROOM_401",
        "role": "BOTH",
        "source_type": "RTSP",
    }
    cam_bound = {
        "camera_id": "CAM_BOUND_01",
        "classroom_id": "ROOM_401",
        "role": "ENTRY",
        "source_type": "RTSP",
    }
    await api_client.post("/api/v1/cameras", json=cam_1, headers=admin_auth["headers"])
    await api_client.post("/api/v1/cameras", json=cam_bound, headers=admin_auth["headers"])

    # 1. Heartbeat without API key -> 401
    res = await api_client.post(
        "/api/v1/cameras/CAM_ROOM_401_DOOR/heartbeat",
        json={"camera_id": "CAM_ROOM_401_DOOR", "state": "CONNECTED", "fps": 15.0},
    )
    assert res.status_code == 401

    # 2. Heartbeat with master Vision Service key -> 200 OK
    res = await api_client.post(
        "/api/v1/cameras/CAM_ROOM_401_DOOR/heartbeat",
        json={
            "camera_id": "CAM_ROOM_401_DOOR",
            "state": "CONNECTED",
            "fps": 24.5,
            "dropped_frames": 2,
            "metadata": {"resolution": "1920x1080"},
        },
        headers={"X-API-Key": "vision-secret-key-12345"},
    )
    assert res.status_code == 200
    hb_resp = res.json()
    assert hb_resp["status"] == "ok"
    assert hb_resp["camera_id"] == "CAM_ROOM_401_DOOR"
    assert hb_resp["state"] == "CONNECTED"

    # 3. Heartbeat with camera-specific bound key:
    # Allowed for CAM_BOUND_01
    res = await api_client.post(
        "/api/v1/cameras/CAM_BOUND_01/heartbeat",
        json={"camera_id": "CAM_BOUND_01", "state": "CONNECTED", "fps": 20.0},
        headers={"X-API-Key": "camera-01-bound-secret"},
    )
    assert res.status_code == 200

    # Forbidden when trying to report for CAM_ROOM_401_DOOR using CAM_BOUND_01's key
    res = await api_client.post(
        "/api/v1/cameras/CAM_ROOM_401_DOOR/heartbeat",
        json={"camera_id": "CAM_ROOM_401_DOOR", "state": "DEGRADED", "fps": 5.0},
        headers={"X-API-Key": "camera-01-bound-secret"},
    )
    assert res.status_code == 403

    # 4. Check Health endpoint for dashboard
    res_health = await api_client.get(
        "/api/v1/cameras/CAM_ROOM_401_DOOR/health",
        headers=teacher_auth["headers"],
    )
    assert res_health.status_code == 200
    hdata = res_health.json()
    assert hdata["camera_id"] == "CAM_ROOM_401_DOOR"
    assert hdata["status"] == "CONNECTED"
    assert hdata["fps"] == 24.5
    assert hdata["last_seen"] is not None


@pytest.mark.anyio
async def test_dynamic_camera_classroom_resolution(mock_db, api_client, admin_auth):
    """Verify resolve_classroom_for_camera_db dynamically resolves newly registered cameras."""
    custom_camera = {
        "camera_id": "CUSTOM_GATEWAY_SPECIAL_99",
        "classroom_id": "LECTURE_HALL_7",
        "role": "ENTRY",
        "source_type": "RTSP",
    }
    await api_client.post("/api/v1/cameras", json=custom_camera, headers=admin_auth["headers"])

    # Dynamic resolver finds it in db and caches it
    resolved = await resolve_classroom_for_camera_db("CUSTOM_GATEWAY_SPECIAL_99", db=mock_db)
    assert resolved == "LECTURE_HALL_7"
