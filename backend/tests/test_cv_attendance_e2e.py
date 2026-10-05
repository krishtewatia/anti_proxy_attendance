"""End-to-End Test for Step 2C.10 Part 2: Real CV -> Attendance Demo.

Verifies the complete pipeline:
1. Teacher creates session for ROOM_101.
2. Teacher enrolls session roster (person_01, person_02, person_04).
3. Vision service emits realistic CV events through POST /api/v1/events.
4. Backend enriches events with resolved classroom_id and session_id.
5. Teacher finalizes the session via POST /api/v1/sessions/{session_id}/finalize.
6. Teacher retrieves attendance records via GET /api/v1/attendance/{session_id}.
7. Isolates un-enrolled identities (person_03) and correctly flags absent students (person_04).
"""

from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.core.config import settings
from app.database import get_database, mongodb
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password


@pytest.fixture(autouse=True)
def setup_test_db():
    mock_client = AsyncMongoMockClient()
    mongodb._client = mock_client
    db = mock_client[settings.DATABASE_NAME]

    app.dependency_overrides[get_database] = lambda: db
    yield
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_cv_to_attendance_e2e_flow():
    """Prove complete flow: CV events -> session resolution -> finalization -> attendance records."""
    db = mongodb.get_database()

    # Clean test collections
    await db["sessions"].delete_many({})
    await db["session_rosters"].delete_many({})
    await db[settings.EVENTS_COLLECTION].delete_many({})
    await db["attendance_records"].delete_many({})
    await db["users"].delete_many({})

    # 1. Provision Teacher user and auth header
    teacher_id = "teacher_cv_demo"
    await create_user(
        user_id=teacher_id,
        email="teacher.cv@university.edu",
        password_hash=hash_password("TeacherSecure2026!"),
        role="TEACHER",
    )
    token = create_access_token(user_id=teacher_id, role="TEACHER")
    auth_headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # ----------------------------------------------------------------------
        # Step A: Teacher creates controlled session in ROOM_101
        # ----------------------------------------------------------------------
        session_start = "2026-10-20T10:00:00Z"
        session_end = "2026-10-20T11:00:00Z"  # 1 hour = 3600 seconds

        create_session_resp = await client.post(
            "/api/v1/sessions",
            headers=auth_headers,
            json={
                "course_name": "CS401 - Advanced Computer Vision",
                "classroom_id": "ROOM_101",
                "start_time": session_start,
                "end_time": session_end,
                "required_presence_percentage": 70.0,
            },
        )
        assert create_session_resp.status_code == 201
        session_data = create_session_resp.json()
        session_id = session_data["session_id"]
        assert session_data["classroom_id"] == "ROOM_101"
        assert session_data["created_by"] == teacher_id

        # ----------------------------------------------------------------------
        # Step B: Teacher enrolls session roster: person_01, person_02, person_04
        # (person_03 is intentionally un-enrolled to test isolation)
        # (person_04 is enrolled but will have 0 events to test ABSENT behavior)
        # ----------------------------------------------------------------------
        roster_resp = await client.post(
            f"/api/v1/sessions/{session_id}/roster",
            headers=auth_headers,
            json={
                "identities": [
                    "person_01",
                    "person_02",
                    "person_04",
                ]
            },
        )
        assert roster_resp.status_code == 200
        roster_data = roster_resp.json()
        assert set(roster_data["identities"]) == {"person_01", "person_02", "person_04"}

        # ----------------------------------------------------------------------
        # Step C: Vision Service transmits realistic CV events via POST /api/v1/events
        # ----------------------------------------------------------------------
        cv_events = [
            # person_01 ENTRY (Track 7, 10:05:00 UTC)
            {
                "event_id": "evt_cv_p1_in",
                "camera_id": "CAM_ROOM_101_DOOR",
                "track_id": 7,
                "identity": "person_01",
                "direction": "ENTRY",
                "timestamp": "2026-10-20T10:05:00Z",
                "evidence": {
                    "peak_similarity": 0.4915,
                    "mean_similarity": 0.4561,
                    "supporting_frames": 5,
                    "total_frames": 5,
                    "consistency_pct": 100.0,
                    "margin_over_runner_up": 0.05,
                    "runner_up_identity": "person_03",
                },
            },
            # person_02 ENTRY (Track 9, 10:10:00 UTC)
            {
                "event_id": "evt_cv_p2_in",
                "camera_id": "CAM_ROOM_101_DOOR",
                "track_id": 9,
                "identity": "person_02",
                "direction": "ENTRY",
                "timestamp": "2026-10-20T10:10:00Z",
                "evidence": {
                    "peak_similarity": 0.6223,
                    "mean_similarity": 0.5875,
                    "supporting_frames": 3,
                    "total_frames": 4,
                    "consistency_pct": 75.0,
                    "margin_over_runner_up": 0.18,
                    "runner_up_identity": "person_01",
                },
            },
            # person_03 (NON-ROSTER) ENTRY (Track 40, 10:15:00 UTC)
            {
                "event_id": "evt_cv_p3_in",
                "camera_id": "CAM_ROOM_101_DOOR",
                "track_id": 40,
                "identity": "person_03",
                "direction": "ENTRY",
                "timestamp": "2026-10-20T10:15:00Z",
                "evidence": {
                    "peak_similarity": 0.5810,
                    "mean_similarity": 0.5520,
                    "supporting_frames": 4,
                    "total_frames": 4,
                    "consistency_pct": 100.0,
                },
            },
            # person_03 (NON-ROSTER) EXIT (Track 41, 10:45:00 UTC)
            {
                "event_id": "evt_cv_p3_out",
                "camera_id": "CAM_ROOM_101_DOOR",
                "track_id": 41,
                "identity": "person_03",
                "direction": "EXIT",
                "timestamp": "2026-10-20T10:45:00Z",
                "evidence": {
                    "peak_similarity": 0.5900,
                    "mean_similarity": 0.5610,
                    "supporting_frames": 4,
                    "total_frames": 4,
                    "consistency_pct": 100.0,
                },
            },
            # person_01 EXIT (Track 24, 10:55:00 UTC)
            {
                "event_id": "evt_cv_p1_out",
                "camera_id": "CAM_ROOM_101_DOOR",
                "track_id": 24,
                "identity": "person_01",
                "direction": "EXIT",
                "timestamp": "2026-10-20T10:55:00Z",
                "evidence": {
                    "peak_similarity": 0.4898,
                    "mean_similarity": 0.4556,
                    "supporting_frames": 3,
                    "total_frames": 4,
                    "consistency_pct": 75.0,
                },
            },
            # person_02 EXIT (Track 25, 10:55:00 UTC)
            {
                "event_id": "evt_cv_p2_out",
                "camera_id": "CAM_ROOM_101_DOOR",
                "track_id": 25,
                "identity": "person_02",
                "direction": "EXIT",
                "timestamp": "2026-10-20T10:55:00Z",
                "evidence": {
                    "peak_similarity": 0.6204,
                    "mean_similarity": 0.5937,
                    "supporting_frames": 4,
                    "total_frames": 5,
                    "consistency_pct": 80.0,
                },
            },
        ]

        for event_payload in cv_events:
            ev_resp = await client.post(
                "/api/v1/events",
                json=event_payload,
                headers={"X-API-Key": "test-vision-service-key-2026"},
            )
            assert ev_resp.status_code == 201
            assert ev_resp.json()["status"] == "accepted"

        # ----------------------------------------------------------------------
        # Step D: Verify Event Enrichment in MongoDB
        # camera_id -> classroom_id ("ROOM_101")
        # classroom_id + timestamp -> session_id
        # ----------------------------------------------------------------------
        stored_events = await db[settings.EVENTS_COLLECTION].find().to_list(length=None)
        assert len(stored_events) == 6

        for doc in stored_events:
            assert doc["classroom_id"] == "ROOM_101"
            assert doc["session_id"] == session_id

        # ----------------------------------------------------------------------
        # Step E: Teacher finalizes the session
        # ----------------------------------------------------------------------
        finalize_resp = await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers=auth_headers,
        )
        assert finalize_resp.status_code == 200
        finalize_data = finalize_resp.json()
        assert finalize_data["session_id"] == session_id
        assert len(finalize_data["records"]) == 3

        # ----------------------------------------------------------------------
        # Step F: Teacher queries GET /api/v1/attendance/{session_id}
        # ----------------------------------------------------------------------
        att_resp = await client.get(
            f"/api/v1/attendance/{session_id}",
            headers=auth_headers,
        )
        assert att_resp.status_code == 200
        att_data = att_resp.json()
        assert att_data["session_id"] == session_id

        records_by_id = {r["identity"]: r for r in att_data["records"]}

        # 1. Total records must be exactly 3 (only enrolled roster members)
        assert len(records_by_id) == 3

        # 2. Isolation: person_03 is NOT on the roster and MUST have no attendance record
        assert "person_03" not in records_by_id

        # 3. person_01 attendance verification
        # Present from 10:05 to 10:55 = 50 min = 3000 seconds
        # 3000s / 3600s = 83.33% presence >= 70.0% required -> PRESENT
        p1 = records_by_id["person_01"]
        assert p1["status"] == "PRESENT"
        assert p1["presence_duration_seconds"] == 3000.0
        assert round(p1["presence_percentage"], 2) == 83.33
        assert p1["required_presence_percentage"] == 70.0

        # 4. person_02 attendance verification
        # Present from 10:10 to 10:55 = 45 min = 2700 seconds
        # 2700s / 3600s = 75.0% presence >= 70.0% required -> PRESENT
        p2 = records_by_id["person_02"]
        assert p2["status"] == "PRESENT"
        assert p2["presence_duration_seconds"] == 2700.0
        assert round(p2["presence_percentage"], 2) == 75.0
        assert p2["required_presence_percentage"] == 70.0

        # 5. person_04 attendance verification
        # Enrolled on roster with 0 events -> ABSENT
        p4 = records_by_id["person_04"]
        assert p4["status"] == "ABSENT"
        assert p4["presence_duration_seconds"] == 0.0
        assert p4["presence_percentage"] == 0.0
        assert p4["required_presence_percentage"] == 70.0
