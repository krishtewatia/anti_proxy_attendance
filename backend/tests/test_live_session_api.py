"""Tests for live attendance session snapshot endpoint (Step 2E.9).

Validates:
1. Teacher ownership and RBAC isolation (cross-teacher leakage forbidden).
2. Live presence states (INSIDE, OUTSIDE, NOT_SEEN).
3. Active accumulated duration calculation for unclosed ENTRY.
4. Camera operational health and staleness telemetry.
5. Bounded recent events feed.
6. Session states (UPCOMING, LIVE, ENDED).
"""

from datetime import datetime, timedelta, timezone
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
async def api_client(mock_db):
    app.dependency_overrides[get_database] = lambda: mock_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_live_snapshot_rbac_and_ownership(
    api_client: AsyncClient,
    mock_db,
) -> None:
    # 1. Create Teacher 1 (Owner) and Teacher 2 (Unrelated)
    t1_id = f"teacher_{uuid.uuid4().hex[:8]}"
    t2_id = f"teacher_{uuid.uuid4().hex[:8]}"

    await create_user(
        user_id=t1_id,
        email="teacher1@school.edu",
        password_hash=hash_password("pass123"),
        role="TEACHER",
    )
    await create_user(
        user_id=t2_id,
        email="teacher2@school.edu",
        password_hash=hash_password("pass123"),
        role="TEACHER",
    )

    token_t1 = create_access_token(user_id=t1_id, role="TEACHER")
    token_t2 = create_access_token(user_id=t2_id, role="TEACHER")

    # 2. Create Session owned by Teacher 1
    session_id = f"sess_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(minutes=15)
    end_time = now + timedelta(minutes=45)

    await mock_db["sessions"].insert_one({
        "session_id": session_id,
        "course_name": "Distributed Systems 401",
        "classroom_id": "ROOM_301",
        "start_time": start_time,
        "end_time": end_time,
        "required_presence_percentage": 70.0,
        "status": "SCHEDULED",
        "created_by": t1_id,
    })

    # 3. Owner (Teacher 1) queries live snapshot -> 200 OK
    resp_t1 = await api_client.get(
        f"/api/v1/sessions/{session_id}/live-snapshot",
        headers={"Authorization": f"Bearer {token_t1}"},
    )
    assert resp_t1.status_code == 200
    data = resp_t1.json()
    assert data["session_id"] == session_id
    assert data["session_state"] == "LIVE"
    assert data["course_name"] == "Distributed Systems 401"
    assert data["classroom_id"] == "ROOM_301"

    # 4. Another teacher (Teacher 2) queries Teacher 1's session -> 403 Forbidden
    resp_t2 = await api_client.get(
        f"/api/v1/sessions/{session_id}/live-snapshot",
        headers={"Authorization": f"Bearer {token_t2}"},
    )
    assert resp_t2.status_code == 403
    assert "own" in resp_t2.json()["detail"].lower()

    # 5. Non-existent session -> 404 Not Found
    resp_404 = await api_client.get(
        "/api/v1/sessions/nonexistent_session_id/live-snapshot",
        headers={"Authorization": f"Bearer {token_t1}"},
    )
    assert resp_404.status_code == 404


@pytest.mark.anyio
async def test_live_snapshot_student_states_and_camera_health(
    api_client: AsyncClient,
    mock_db,
) -> None:
    teacher_id = f"teacher_{uuid.uuid4().hex[:8]}"
    await create_user(
        user_id=teacher_id,
        email="teacher_demo@school.edu",
        password_hash=hash_password("pass123"),
        role="TEACHER",
    )
    token = create_access_token(user_id=teacher_id, role="TEACHER")

    # Session: 10:00 to 11:00 (60 minutes = 3600 seconds)
    fixed_now = datetime(2026, 10, 15, 10, 30, 0, tzinfo=timezone.utc)
    start_time = datetime(2026, 10, 15, 10, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2026, 10, 15, 11, 0, 0, tzinfo=timezone.utc)
    session_id = f"sess_{uuid.uuid4().hex[:8]}"

    await mock_db["sessions"].insert_one({
        "session_id": session_id,
        "course_name": "Operating Systems",
        "classroom_id": "ROOM_101",
        "start_time": start_time,
        "end_time": end_time,
        "required_presence_percentage": 50.0,
        "status": "SCHEDULED",
        "created_by": teacher_id,
    })

    # Roster: Alice, Bob, Charlie
    await mock_db["session_rosters"].insert_one({
        "session_id": session_id,
        "identities": ["alice_01", "bob_02", "charlie_03"],
    })

    # Cameras in ROOM_101
    await mock_db["cameras"].insert_many([
        {
            "camera_id": "CAM_ROOM_101_DOOR",
            "classroom_id": "ROOM_101",
            "role": "BOTH",
            "source_type": "RTSP",
            "enabled": True,
            "status": "CONNECTED",
            "fps": 14.8,
            "last_seen": fixed_now - timedelta(seconds=2),  # fresh
        },
        {
            "camera_id": "CAM_ROOM_101_BACKUP",
            "classroom_id": "ROOM_101",
            "role": "ENTRY",
            "source_type": "WEBRTC",
            "enabled": True,
            "status": "DEGRADED",
            "fps": 4.2,
            "last_seen": fixed_now - timedelta(seconds=35),  # stale (> 15s)
        },
    ])

    # Events:
    # 1. Alice: ENTRY at 10:05. Currently INSIDE!
    #    Active duration: 10:05 to 10:30 (now) = 25 minutes = 1500 seconds.
    #    1500 / 3600 = 41.7%
    # 2. Bob: ENTRY at 10:05, EXIT at 10:25. Currently OUTSIDE!
    #    Closed duration: 20 minutes = 1200 seconds.
    # 3. Charlie: No events. NOT_SEEN!
    # 4. Dave (unrostered): ENTRY at 10:10.
    events = [
        {
            "event_id": "ev_1",
            "session_id": session_id,
            "classroom_id": "ROOM_101",
            "camera_id": "CAM_ROOM_101_DOOR",
            "identity": "alice_01",
            "direction": "ENTRY",
            "timestamp": datetime(2026, 10, 15, 10, 5, 0, tzinfo=timezone.utc),
            "confidence": 0.95,
        },
        {
            "event_id": "ev_2",
            "session_id": session_id,
            "classroom_id": "ROOM_101",
            "camera_id": "CAM_ROOM_101_DOOR",
            "identity": "bob_02",
            "direction": "ENTRY",
            "timestamp": datetime(2026, 10, 15, 10, 5, 0, tzinfo=timezone.utc),
            "confidence": 0.92,
        },
        {
            "event_id": "ev_3",
            "session_id": session_id,
            "classroom_id": "ROOM_101",
            "camera_id": "CAM_ROOM_101_DOOR",
            "identity": "bob_02",
            "direction": "EXIT",
            "timestamp": datetime(2026, 10, 15, 10, 25, 0, tzinfo=timezone.utc),
            "confidence": 0.94,
        },
        {
            "event_id": "ev_4",
            "session_id": session_id,
            "classroom_id": "ROOM_101",
            "camera_id": "CAM_ROOM_101_DOOR",
            "identity": "dave_04",
            "direction": "ENTRY",
            "timestamp": datetime(2026, 10, 15, 10, 10, 0, tzinfo=timezone.utc),
            "confidence": 0.88,
        },
    ]
    await mock_db[settings.EVENTS_COLLECTION].insert_many(events)

    import app.api.routes.sessions as sessions_mod
    orig_compute = sessions_mod.compute_session_live_snapshot

    async def patched_compute(session_doc, db, now=None):
        return await orig_compute(session_doc, db=db, now=fixed_now)

    sessions_mod.compute_session_live_snapshot = patched_compute

    try:
        resp = await api_client.get(
            f"/api/v1/sessions/{session_id}/live-snapshot",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        snap = resp.json()

        # Session state
        assert snap["session_state"] == "LIVE"
        assert not snap["is_stale"]

        # Cameras
        assert len(snap["cameras"]) == 2
        cam_door = next(c for c in snap["cameras"] if c["camera_id"] == "CAM_ROOM_101_DOOR")
        assert cam_door["status"] == "CONNECTED"
        assert not cam_door["is_stale"]
        assert cam_door["heartbeat_age_seconds"] == 2.0

        cam_backup = next(c for c in snap["cameras"] if c["camera_id"] == "CAM_ROOM_101_BACKUP")
        assert cam_backup["is_stale"]
        assert cam_backup["heartbeat_age_seconds"] == 35.0

        # Students
        students_by_id = {s["identity"]: s for s in snap["students"]}

        # Alice: INSIDE, active presence = 25m = 1500s
        alice = students_by_id["alice_01"]
        assert alice["is_rostered"] is True
        assert alice["state"] == "INSIDE"
        assert alice["no_exit_observed"] is True
        assert alice["presence_duration_seconds"] == 1500.0
        assert alice["presence_percentage"] == 41.7
        assert alice["is_on_track"] is True  # remaining 30m allows 1500 + 1800 = 3300s >= 1800s (50%)

        # Bob: OUTSIDE, presence = 20m = 1200s
        bob = students_by_id["bob_02"]
        assert bob["is_rostered"] is True
        assert bob["state"] == "OUTSIDE"
        assert bob["no_exit_observed"] is False
        assert bob["presence_duration_seconds"] == 1200.0
        assert bob["presence_percentage"] == 33.3

        # Charlie: NOT_SEEN, presence = 0s
        charlie = students_by_id["charlie_03"]
        assert charlie["is_rostered"] is True
        assert charlie["state"] == "NOT_SEEN"
        assert charlie["presence_duration_seconds"] == 0.0
        assert charlie["presence_percentage"] == 0.0

        # Dave: unrostered, INSIDE
        dave = students_by_id["dave_04"]
        assert dave["is_rostered"] is False
        assert dave["state"] == "INSIDE"
        assert dave["presence_duration_seconds"] == 1200.0  # 10:10 to 10:30 = 20m = 1200s

        # Recent events feed (bounded, newest first)
        assert len(snap["recent_events"]) == 4
        # Verify chronological order
        timestamps = [ev["timestamp"] for ev in snap["recent_events"]]
        assert timestamps == sorted(timestamps, reverse=True)

    finally:
        sessions_mod.compute_session_live_snapshot = orig_compute


@pytest.mark.anyio
async def test_live_snapshot_upcoming_and_ended_session(
    api_client: AsyncClient,
    mock_db,
) -> None:
    teacher_id = f"teacher_{uuid.uuid4().hex[:8]}"
    await create_user(
        user_id=teacher_id,
        email="teacher_states@school.edu",
        password_hash=hash_password("pass123"),
        role="TEACHER",
    )
    token = create_access_token(user_id=teacher_id, role="TEACHER")

    # Case A: Upcoming session (start_time in future)
    future_start = datetime.now(timezone.utc) + timedelta(hours=2)
    future_end = future_start + timedelta(hours=1)
    upcoming_sess_id = f"sess_up_{uuid.uuid4().hex[:8]}"

    await mock_db["sessions"].insert_one({
        "session_id": upcoming_sess_id,
        "course_name": "Calculus I",
        "classroom_id": "ROOM_202",
        "start_time": future_start,
        "end_time": future_end,
        "required_presence_percentage": 75.0,
        "status": "SCHEDULED",
        "created_by": teacher_id,
    })

    resp_up = await api_client.get(
        f"/api/v1/sessions/{upcoming_sess_id}/live-snapshot",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_up.status_code == 200
    assert resp_up.json()["session_state"] == "UPCOMING"

    # Case B: Completed session with finalized attendance records
    past_start = datetime.now(timezone.utc) - timedelta(hours=3)
    past_end = past_start + timedelta(hours=1)
    ended_sess_id = f"sess_end_{uuid.uuid4().hex[:8]}"

    await mock_db["sessions"].insert_one({
        "session_id": ended_sess_id,
        "course_name": "Calculus I Completed",
        "classroom_id": "ROOM_202",
        "start_time": past_start,
        "end_time": past_end,
        "required_presence_percentage": 75.0,
        "status": "COMPLETED",
        "created_by": teacher_id,
    })

    await mock_db["attendance_records"].insert_one({
        "attendance_id": "att_01",
        "session_id": ended_sess_id,
        "identity": "student_final_01",
        "presence_duration_seconds": 3000.0,
        "presence_percentage": 83.3,
        "required_presence_percentage": 75.0,
        "status": "PRESENT",
        "anomalies": [],
    })

    resp_end = await api_client.get(
        f"/api/v1/sessions/{ended_sess_id}/live-snapshot",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_end.status_code == 200
    end_data = resp_end.json()
    assert end_data["session_state"] == "ENDED"
    assert len(end_data["students"]) == 1
    assert end_data["students"][0]["identity"] == "student_final_01"
    assert end_data["students"][0]["projected_status"] == "PRESENT"
    assert end_data["students"][0]["presence_percentage"] == 83.3


@pytest.mark.anyio
async def test_live_snapshot_anomalies_and_all_cameras_stale(
    api_client: AsyncClient,
    mock_db,
) -> None:
    teacher_id = f"teacher_{uuid.uuid4().hex[:8]}"
    await create_user(
        user_id=teacher_id,
        email="teacher_anom@school.edu",
        password_hash=hash_password("pass123"),
        role="TEACHER",
    )
    token = create_access_token(user_id=teacher_id, role="TEACHER")

    fixed_now = datetime(2026, 10, 15, 10, 20, 0, tzinfo=timezone.utc)
    start_time = datetime(2026, 10, 15, 10, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2026, 10, 15, 11, 0, 0, tzinfo=timezone.utc)
    session_id = f"sess_anom_{uuid.uuid4().hex[:8]}"

    await mock_db["sessions"].insert_one({
        "session_id": session_id,
        "course_name": "Network Security",
        "classroom_id": "ROOM_STALE",
        "start_time": start_time,
        "end_time": end_time,
        "required_presence_percentage": 60.0,
        "status": "SCHEDULED",
        "created_by": teacher_id,
    })

    # Single camera that hasn't reported for 60 seconds (stale!)
    await mock_db["cameras"].insert_one({
        "camera_id": "CAM_STALE_01",
        "classroom_id": "ROOM_STALE",
        "role": "BOTH",
        "source_type": "RTSP",
        "enabled": True,
        "status": "CONNECTED",
        "fps": 10.0,
        "last_seen": fixed_now - timedelta(seconds=60),
    })

    # Student with EXIT without ENTRY anomaly
    await mock_db[settings.EVENTS_COLLECTION].insert_one({
        "event_id": "ev_unpaired_exit",
        "session_id": session_id,
        "classroom_id": "ROOM_STALE",
        "camera_id": "CAM_STALE_01",
        "identity": "ghost_student",
        "direction": "EXIT",
        "timestamp": datetime(2026, 10, 15, 10, 5, 0, tzinfo=timezone.utc),
        "confidence": 0.91,
    })

    import app.api.routes.sessions as sessions_mod
    orig_compute = sessions_mod.compute_session_live_snapshot

    async def patched_compute(session_doc, db, now=None):
        return await orig_compute(session_doc, db=db, now=fixed_now)

    sessions_mod.compute_session_live_snapshot = patched_compute

    try:
        resp = await api_client.get(
            f"/api/v1/sessions/{session_id}/live-snapshot",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        snap = resp.json()

        # Session state is LIVE, but camera is stale (>15s), so is_stale is True!
        assert snap["session_state"] == "LIVE"
        assert snap["is_stale"] is True
        assert snap["cameras"][0]["is_stale"] is True

        # Ghost student should have anomaly flag
        ghost = next(s for s in snap["students"] if s["identity"] == "ghost_student")
        assert "EXIT_WITHOUT_ENTRY" in ghost["anomalies"]
        assert ghost["state"] == "OUTSIDE"

    finally:
        sessions_mod.compute_session_live_snapshot = orig_compute


@pytest.mark.anyio
async def test_live_snapshot_overlapping_sessions_do_not_share_students(
    api_client: AsyncClient,
    mock_db,
) -> None:
    """Two overlapping sessions: each live view shows only its own events and marks."""
    teacher_id = f"teacher_{uuid.uuid4().hex[:8]}"
    await create_user(
        user_id=teacher_id,
        email="teacher_overlap@school.edu",
        password_hash=hash_password("pass123"),
        role="TEACHER",
    )
    headers = {"Authorization": f"Bearer {create_access_token(user_id=teacher_id, role='TEACHER')}"}

    now = datetime.now(timezone.utc)
    session_a = f"sess_overlap_a_{uuid.uuid4().hex[:8]}"
    session_b = f"sess_overlap_b_{uuid.uuid4().hex[:8]}"

    # Both sessions are live right now, so their time windows overlap
    for sess_id, classroom, start_offset in (
        (session_a, "ROOM_A", 20),
        (session_b, "ROOM_B", 10),
    ):
        await mock_db["sessions"].insert_one({
            "session_id": sess_id,
            "course_name": f"Course {classroom}",
            "classroom_id": classroom,
            "start_time": now - timedelta(minutes=start_offset),
            "end_time": now + timedelta(minutes=40),
            "required_presence_percentage": 50.0,
            "status": "ACTIVE",
            "created_by": teacher_id,
        })

    await mock_db[settings.EVENTS_COLLECTION].insert_many([
        {
            "event_id": "ev_overlap_a_entry",
            "session_id": session_a,
            "classroom_id": "ROOM_A",
            "identity": "student_only_in_a",
            "direction": "ENTRY",
            "timestamp": now - timedelta(minutes=5),
        },
        {
            "event_id": "ev_overlap_b_entry",
            "session_id": session_b,
            "classroom_id": "ROOM_B",
            "identity": "student_only_in_b",
            "direction": "ENTRY",
            "timestamp": now - timedelta(minutes=4),
        },
        # Inside both windows but belongs to no session
        {
            "event_id": "ev_overlap_unscoped_entry",
            "session_id": None,
            "identity": "student_unscoped",
            "direction": "ENTRY",
            "timestamp": now - timedelta(minutes=3),
        },
    ])

    # One-time recognition mark recorded in session B only
    await mock_db["attendance_records"].insert_one({
        "attendance_id": f"att_{session_b}_student_marked_in_b",
        "session_id": session_b,
        "identity": "student_marked_in_b",
        "status": "PRESENT",
        "marked_at": now - timedelta(minutes=2),
    })

    resp_a = await api_client.get(f"/api/v1/sessions/{session_a}/live-snapshot", headers=headers)
    resp_b = await api_client.get(f"/api/v1/sessions/{session_b}/live-snapshot", headers=headers)
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    snap_a = resp_a.json()
    snap_b = resp_b.json()

    assert snap_a["session_state"] == "LIVE"
    assert snap_b["session_state"] == "LIVE"

    assert [s["identity"] for s in snap_a["students"]] == ["student_only_in_a"]
    assert snap_a["students"][0]["state"] == "INSIDE"
    assert [e["event_id"] for e in snap_a["recent_events"]] == ["ev_overlap_a_entry"]

    assert [s["identity"] for s in snap_b["students"]] == ["student_only_in_b"]
    assert snap_b["students"][0]["state"] == "INSIDE"
    assert [e["event_id"] for e in snap_b["recent_events"]] == ["ev_overlap_b_entry"]
