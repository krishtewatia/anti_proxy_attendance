"""End-to-End Test for Demo 3 (Step 2E.9): Live Attendance Dashboard & System Status.

Validates the full walkthrough:
1. Teacher starts session in ROOM_101.
2. Vision/Phone camera connects and transmits heartbeat telemetry.
3. Student 1 walks in -> Live snapshot changes badge to INSIDE, accumulated presence ticks.
4. Student 1 walks out -> Live snapshot changes badge to OUTSIDE, presence interval closes.
5. Camera heartbeat lapses -> Snapshot reflects is_stale warning.
6. Other teacher queries -> 403 Forbidden (Ownership Isolation).
7. Session finalized -> Snapshot reflects ENDED state with final status parity.
"""

from datetime import datetime, timedelta, timezone
import json
import uuid

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.core.config import settings
from app.database import get_database, init_indexes, mongodb
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password


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
    monkeypatch.setattr(settings, "VISION_SERVICE_API_KEY", "vision-secret-key-demo3")
    monkeypatch.setattr(settings, "VISION_SERVICE_API_KEY_HASH", "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_demo3_full_live_attendance_walkthrough(
    api_client: AsyncClient,
    mock_db,
) -> None:
    # -------------------------------------------------------------------------
    # Phase 1: Setup Teacher, Session, and Roster
    # -------------------------------------------------------------------------
    teacher_id = f"teacher_{uuid.uuid4().hex[:8]}"
    other_teacher_id = f"teacher_other_{uuid.uuid4().hex[:8]}"

    await create_user(
        user_id=teacher_id,
        email="prof_smith@university.edu",
        password_hash=hash_password("TeacherPass123!"),
        role="TEACHER",
    )
    await create_user(
        user_id=other_teacher_id,
        email="prof_jones@university.edu",
        password_hash=hash_password("TeacherPass123!"),
        role="TEACHER",
    )

    teacher_token = create_access_token(user_id=teacher_id, role="TEACHER")
    other_teacher_token = create_access_token(user_id=other_teacher_id, role="TEACHER")

    session_id = f"sess_demo3_{uuid.uuid4().hex[:8]}"
    wall_now = datetime.now(timezone.utc)
    start_time = wall_now - timedelta(minutes=15)
    end_time = wall_now + timedelta(minutes=45)  # 60 min session (3600s)

    await mock_db["sessions"].insert_one({
        "session_id": session_id,
        "course_name": "CS401: Cloud Infrastructure",
        "classroom_id": "ROOM_101",
        "start_time": start_time,
        "end_time": end_time,
        "required_presence_percentage": 20.0,  # 12 minutes = 720 seconds required
        "status": "SCHEDULED",
        "created_by": teacher_id,
    })

    # Roster: student_01, student_02
    await mock_db["session_rosters"].insert_one({
        "session_id": session_id,
        "identities": ["student_01", "student_02"],
    })

    # Register Camera for ROOM_101
    camera_id = "CAM_ROOM_101_PHONE"
    await mock_db["cameras"].insert_one({
        "camera_id": camera_id,
        "classroom_id": "ROOM_101",
        "role": "BOTH",
        "source_type": "WEBRTC",
        "enabled": True,
        "status": "DISCONNECTED",
        "fps": 0.0,
        "last_seen": None,
    })

    # -------------------------------------------------------------------------
    # Phase 2: Camera Connects & Sends Heartbeat
    # -------------------------------------------------------------------------
    hb_resp = await api_client.post(
        f"/api/v1/cameras/{camera_id}/heartbeat",
        headers={"X-API-Key": "vision-secret-key-demo3"},
        json={
            "camera_id": camera_id,
            "state": "CONNECTED",
            "fps": 15.2,
            "dropped_frames": 0,
        },
    )
    assert hb_resp.status_code == 200

    # Teacher queries Live Dashboard Snapshot
    dash_resp1 = await api_client.get(
        f"/api/v1/sessions/{session_id}/live-snapshot",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert dash_resp1.status_code == 200
    snap1 = dash_resp1.json()

    assert snap1["session_state"] == "LIVE"
    assert not snap1["is_stale"]
    assert len(snap1["cameras"]) == 1
    assert snap1["cameras"][0]["status"] == "CONNECTED"
    assert snap1["cameras"][0]["fps"] == 15.2

    # Both students are NOT_SEEN
    st1_snap = next(s for s in snap1["students"] if s["identity"] == "student_01")
    st2_snap = next(s for s in snap1["students"] if s["identity"] == "student_02")
    assert st1_snap["state"] == "NOT_SEEN"
    assert st2_snap["state"] == "NOT_SEEN"

    # -------------------------------------------------------------------------
    # Phase 3: Student 1 walks in (Optical ENTRY Event at start_time + 2 min)
    # -------------------------------------------------------------------------
    t_entry = start_time + timedelta(minutes=2)
    ev_evidence_entry = {
        "peak_similarity": 0.96,
        "mean_similarity": 0.92,
        "supporting_frames": 3,
        "total_frames": 3,
        "consistency_pct": 100.0,
    }
    ev1_resp = await api_client.post(
        "/api/v1/events",
        headers={"X-API-Key": "vision-secret-key-demo3"},
        json={
            "event_id": f"ev_{uuid.uuid4().hex[:8]}",
            "camera_id": camera_id,
            "track_id": 101,
            "identity": "student_01",
            "direction": "ENTRY",
            "timestamp": t_entry.isoformat(),
            "evidence": ev_evidence_entry,
        },
    )
    assert ev1_resp.status_code == 201

    dash_resp2 = await api_client.get(
        f"/api/v1/sessions/{session_id}/live-snapshot",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert dash_resp2.status_code == 200
    snap2 = dash_resp2.json()

    st1_snap2 = next(s for s in snap2["students"] if s["identity"] == "student_01")
    # Student 1 is actively INSIDE!
    assert st1_snap2["state"] == "INSIDE"
    assert st1_snap2["no_exit_observed"] is True
    assert st1_snap2["presence_duration_seconds"] > 0
    assert st1_snap2["is_on_track"] is True

    # Recent events has the ENTRY event
    assert len(snap2["recent_events"]) == 1
    assert snap2["recent_events"][0]["identity"] == "student_01"
    assert snap2["recent_events"][0]["direction"] == "ENTRY"

    # -------------------------------------------------------------------------
    # Phase 4: Student 1 walks out (Optical EXIT Event at start_time + 14 min)
    # -------------------------------------------------------------------------
    t_exit = start_time + timedelta(minutes=14)  # 12 minutes duration = 720 seconds
    ev_evidence_exit = {
        "peak_similarity": 0.94,
        "mean_similarity": 0.90,
        "supporting_frames": 3,
        "total_frames": 3,
        "consistency_pct": 100.0,
    }
    ev2_resp = await api_client.post(
        "/api/v1/events",
        headers={"X-API-Key": "vision-secret-key-demo3"},
        json={
            "event_id": f"ev_{uuid.uuid4().hex[:8]}",
            "camera_id": camera_id,
            "track_id": 101,
            "identity": "student_01",
            "direction": "EXIT",
            "timestamp": t_exit.isoformat(),
            "evidence": ev_evidence_exit,
        },
    )
    assert ev2_resp.status_code == 201

    dash_resp3 = await api_client.get(
        f"/api/v1/sessions/{session_id}/live-snapshot",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert dash_resp3.status_code == 200
    snap3 = dash_resp3.json()

    st1_snap3 = next(s for s in snap3["students"] if s["identity"] == "student_01")
    # State is now OUTSIDE, closed interval = 12 min (720 seconds)
    assert st1_snap3["state"] == "OUTSIDE"
    assert st1_snap3["no_exit_observed"] is False
    assert st1_snap3["presence_duration_seconds"] == 720.0
    assert st1_snap3["presence_percentage"] == 20.0
    # 20.0% >= required 20.0% -> Projected status is PRESENT!
    assert st1_snap3["projected_status"] == "PRESENT"

    # -------------------------------------------------------------------------
    # Phase 5: Camera Lapses (Stale Condition)
    # -------------------------------------------------------------------------
    # Simulate camera heartbeat becoming stale (> 15s)
    stale_time = datetime.now(timezone.utc) - timedelta(seconds=45)
    await mock_db["cameras"].update_one(
        {"camera_id": camera_id},
        {"$set": {"last_seen": stale_time}},
    )

    dash_resp4 = await api_client.get(
        f"/api/v1/sessions/{session_id}/live-snapshot",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert dash_resp4.status_code == 200
    snap4 = dash_resp4.json()
    assert snap4["is_stale"] is True
    assert snap4["cameras"][0]["is_stale"] is True

    # -------------------------------------------------------------------------
    # Phase 6: Cross-Teacher Ownership Isolation
    # -------------------------------------------------------------------------
    leak_resp = await api_client.get(
        f"/api/v1/sessions/{session_id}/live-snapshot",
        headers={"Authorization": f"Bearer {other_teacher_token}"},
    )
    assert leak_resp.status_code == 403
    assert "own" in leak_resp.json()["detail"].lower()

    # -------------------------------------------------------------------------
    # Phase 7: Session Finalized -> Status ENDED
    # -------------------------------------------------------------------------
    fin_resp = await api_client.post(
        f"/api/v1/sessions/{session_id}/finalize",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert fin_resp.status_code == 200

    final_snap = await api_client.get(
        f"/api/v1/sessions/{session_id}/live-snapshot",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert final_snap.status_code == 200
    snap_final = final_snap.json()

    assert snap_final["session_state"] == "ENDED"
    assert snap_final["status"] == "COMPLETED"

    st1_fin = next(s for s in snap_final["students"] if s["identity"] == "student_01")
    assert st1_fin["projected_status"] == "PRESENT"

    st2_fin = next(s for s in snap_final["students"] if s["identity"] == "student_02")
    assert st2_fin["projected_status"] == "ABSENT"
