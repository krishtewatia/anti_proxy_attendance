"""End-to-End Acceptance Test for Step 2E.8:
Two Cameras (ENTRY and EXIT) Feeding One Attendance Session.

Verifies Acceptance Criteria:
1. Two cameras (ENTRY and EXIT) feed one session and produce correct attendance.
2. Killing / restarting stream transitions camera state (CONNECTED -> DEGRADED -> CONNECTED) visible via API.
3. EXIT without ENTRY is handled safely and flagged for review.
4. Camera telemetry states are visible via API endpoints.
"""

from datetime import datetime, timezone
import json
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.core.config import settings
from app.database import get_database, init_indexes, mongodb
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from tests.conftest import assign_teacher_classes


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def e2e_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await init_indexes(db)
    return db


@pytest.fixture
async def e2e_client(e2e_db, monkeypatch):
    app.dependency_overrides[get_database] = lambda: e2e_db

    monkeypatch.setattr(settings, "REQUIRE_CAMERA_AUTH", True)
    monkeypatch.setattr(settings, "VISION_SERVICE_API_KEY", "vision-e2e-master-key")
    monkeypatch.setattr(settings, "VISION_SERVICE_API_KEY_HASH", "")
    monkeypatch.setattr(settings, "VISION_CAMERA_KEYS", "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def admin_token(e2e_db):
    user_id = "admin_multi_cam_01"
    await create_user(
        user_id=user_id,
        email="admin_multicam@university.edu",
        password_hash=hash_password("AdminPass123!"),
        role="ADMIN",
    )
    token = create_access_token(user_id=user_id, role="ADMIN")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def teacher_token(e2e_db):
    user_id = "teacher_multi_cam_01"
    await create_user(
        user_id=user_id,
        email="teacher_multicam@university.edu",
        password_hash=hash_password("TeacherPass123!"),
        role="TEACHER",
    )
    await assign_teacher_classes(user_id)
    token = create_access_token(user_id=user_id, role="TEACHER")
    return {"user_id": user_id, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.mark.anyio
async def test_two_cameras_entry_and_exit_feed_one_session_attendance(
    e2e_db, e2e_client, admin_token, teacher_token
):
    """
    Scenario:
    1. Register CAM_ROOM_101_ENTRY (role: ENTRY) and CAM_ROOM_101_EXIT (role: EXIT).
    2. Create attendance session for ROOM_101 from 10:00 to 11:00 UTC with roster [student_01, student_02].
    3. Both cameras report CONNECTED heartbeats.
    4. Student 01 crosses CAM_ROOM_101_ENTRY at 10:05 (ENTRY) and CAM_ROOM_101_EXIT at 10:55 (EXIT).
    5. Student 02 only crosses CAM_ROOM_101_EXIT at 10:40 (EXIT without ENTRY).
    6. Finalize attendance session.
    7. Verify Student 01 is PRESENT (50 mins = 83.33%).
    8. Verify Student 02 has EXIT_WITHOUT_ENTRY anomaly and is flagged for review.
    9. Verify stream disruption (DEGRADED) and recovery (CONNECTED) is tracked via API.
    """
    # --------------------------------------------------------------------------
    # Step 1: Register Two Cameras in Camera Registry
    # --------------------------------------------------------------------------
    entry_cam_payload = {
        "camera_id": "CAM_ROOM_101_ENTRY",
        "classroom_id": "ROOM_101",
        "role": "ENTRY",
        "source_type": "RTSP",
        "rtsp_url": "rtsp://admin:secret123@192.168.1.10:554/stream_entry",
        "enabled": True,
    }
    exit_cam_payload = {
        "camera_id": "CAM_ROOM_101_EXIT",
        "classroom_id": "ROOM_101",
        "role": "EXIT",
        "source_type": "RTSP",
        "rtsp_url": "rtsp://admin:secret456@192.168.1.11:554/stream_exit",
        "enabled": True,
    }
    r_entry = await e2e_client.post("/api/v1/cameras", json=entry_cam_payload, headers=admin_token)
    assert r_entry.status_code == 201
    r_exit = await e2e_client.post("/api/v1/cameras", json=exit_cam_payload, headers=admin_token)
    assert r_exit.status_code == 201

    # --------------------------------------------------------------------------
    # Step 2: Create Classroom Session & Roster
    # --------------------------------------------------------------------------
    session_payload = {
        "course_name": "Distributed Systems",
        "classroom_id": "ROOM_101",
        "class_code": "DS-B",
        "start_time": "2026-10-01T10:00:00Z",
        "end_time": "2026-10-01T11:00:00Z",
        "required_presence_percentage": 75.0,
    }
    r_sess = await e2e_client.post(
        "/api/v1/sessions",
        json=session_payload,
        headers=teacher_token["headers"],
    )
    assert r_sess.status_code == 201
    session_id = r_sess.json()["session_id"]

    roster_payload = {
        "identities": ["student_01", "student_02"],
    }
    r_roster = await e2e_client.post(
        f"/api/v1/sessions/{session_id}/roster",
        json=roster_payload,
        headers=teacher_token["headers"],
    )
    assert r_roster.status_code == 200

    # --------------------------------------------------------------------------
    # Step 3: Service-Authenticated Camera Heartbeats (State Visible via API)
    # --------------------------------------------------------------------------
    vision_headers = {"X-API-Key": "vision-e2e-master-key"}
    await e2e_client.post(
        "/api/v1/cameras/CAM_ROOM_101_ENTRY/heartbeat",
        json={"camera_id": "CAM_ROOM_101_ENTRY", "state": "CONNECTED", "fps": 25.0},
        headers=vision_headers,
    )
    await e2e_client.post(
        "/api/v1/cameras/CAM_ROOM_101_EXIT/heartbeat",
        json={"camera_id": "CAM_ROOM_101_EXIT", "state": "CONNECTED", "fps": 25.0},
        headers=vision_headers,
    )

    # Check health API
    h_entry = await e2e_client.get(
        "/api/v1/cameras/CAM_ROOM_101_ENTRY/health",
        headers=teacher_token["headers"],
    )
    assert h_entry.status_code == 200
    assert h_entry.json()["status"] == "CONNECTED"
    assert h_entry.json()["fps"] == 25.0

    # --------------------------------------------------------------------------
    # Step 4: Dispatch Multi-Camera Perception Events
    # --------------------------------------------------------------------------
    # Event 1: Student 01 enters via CAM_ROOM_101_ENTRY at 10:05
    evt_entry_01 = {
        "event_id": "evt_entry_01",
        "camera_id": "CAM_ROOM_101_ENTRY",
        "track_id": 101,
        "identity": "student_01",
        "direction": "ENTRY",
        "timestamp": "2026-10-01T10:05:00Z",
        "evidence": {
            "peak_similarity": 0.85,
            "mean_similarity": 0.82,
            "supporting_frames": 4,
            "total_frames": 4,
            "consistency_pct": 100.0,
        },
    }
    r_evt1 = await e2e_client.post("/api/v1/events", json=evt_entry_01, headers=vision_headers)
    assert r_evt1.status_code == 201

    # Event 2: Student 02 exits via CAM_ROOM_101_EXIT at 10:40 (no prior ENTRY)
    evt_exit_02 = {
        "event_id": "evt_exit_02",
        "camera_id": "CAM_ROOM_101_EXIT",
        "track_id": 102,
        "identity": "student_02",
        "direction": "EXIT",
        "timestamp": "2026-10-01T10:40:00Z",
        "evidence": {
            "peak_similarity": 0.80,
            "mean_similarity": 0.78,
            "supporting_frames": 3,
            "total_frames": 3,
            "consistency_pct": 100.0,
        },
    }
    r_evt2 = await e2e_client.post("/api/v1/events", json=evt_exit_02, headers=vision_headers)
    assert r_evt2.status_code == 201

    # Event 3: Student 01 exits via CAM_ROOM_101_EXIT at 10:55
    evt_exit_01 = {
        "event_id": "evt_exit_01",
        "camera_id": "CAM_ROOM_101_EXIT",
        "track_id": 103,
        "identity": "student_01",
        "direction": "EXIT",
        "timestamp": "2026-10-01T10:55:00Z",
        "evidence": {
            "peak_similarity": 0.84,
            "mean_similarity": 0.81,
            "supporting_frames": 4,
            "total_frames": 4,
            "consistency_pct": 100.0,
        },
    }
    r_evt3 = await e2e_client.post("/api/v1/events", json=evt_exit_01, headers=vision_headers)
    assert r_evt3.status_code == 201

    # --------------------------------------------------------------------------
    # Step 5: Finalize Session and Validate Combined Two-Camera Attendance
    # --------------------------------------------------------------------------
    r_fin = await e2e_client.post(
        f"/api/v1/sessions/{session_id}/finalize",
        headers=teacher_token["headers"],
    )
    assert r_fin.status_code == 200

    r_att = await e2e_client.get(
        f"/api/v1/attendance/{session_id}",
        headers=teacher_token["headers"],
    )
    assert r_att.status_code == 200
    att_data = r_att.json()
    records = {rec["identity"]: rec for rec in att_data["records"]}

    # Student 01 entered at 10:05 via ENTRY cam and exited at 10:55 via EXIT cam:
    # 50 minutes = 3000 seconds / 3600 seconds = 83.33% >= 75.0% -> PRESENT!
    assert "student_01" in records
    rec1 = records["student_01"]
    assert rec1["status"] == "PRESENT"
    assert rec1["presence_duration_seconds"] == 3000.0
    assert abs(rec1["presence_percentage"] - 83.33) < 0.1

    # Student 02 had EXIT without ENTRY:
    # Safely handled without crash, flagged for review
    assert "student_02" in records
    rec2 = records["student_02"]
    assert rec2["requires_review"] is True
    assert "EXIT_WITHOUT_ENTRY" in rec2["anomalies"]

    # --------------------------------------------------------------------------
    # Step 6: Stream Disruption & Auto-Recovery State Tracking
    # --------------------------------------------------------------------------
    # Stream drops -> DEGRADED
    await e2e_client.post(
        "/api/v1/cameras/CAM_ROOM_101_ENTRY/heartbeat",
        json={"camera_id": "CAM_ROOM_101_ENTRY", "state": "DEGRADED", "fps": 0.0},
        headers=vision_headers,
    )
    h_degraded = await e2e_client.get(
        "/api/v1/cameras/CAM_ROOM_101_ENTRY/health",
        headers=teacher_token["headers"],
    )
    assert h_degraded.json()["status"] == "DEGRADED"

    # Stream recovers -> CONNECTED
    await e2e_client.post(
        "/api/v1/cameras/CAM_ROOM_101_ENTRY/heartbeat",
        json={"camera_id": "CAM_ROOM_101_ENTRY", "state": "CONNECTED", "fps": 24.0},
        headers=vision_headers,
    )
    h_recovered = await e2e_client.get(
        "/api/v1/cameras/CAM_ROOM_101_ENTRY/health",
        headers=teacher_token["headers"],
    )
    assert h_recovered.json()["status"] == "CONNECTED"
    assert h_recovered.json()["fps"] == 24.0
