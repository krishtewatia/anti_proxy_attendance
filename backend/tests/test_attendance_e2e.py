from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.database.sessions import create_session
from app.database.users import create_user
from app.main import app
from app.schemas.session import SessionCreate
from app.security.jwt import create_access_token
from app.security.passwords import hash_password


@pytest.mark.anyio
async def test_complete_attendance_flow(register_test_camera):
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()

    # Clean the test collections.
    await db["sessions"].delete_many({})
    await db["session_rosters"].delete_many({})
    await db["attendance_events"].delete_many({})
    await db["attendance_records"].delete_many({})
    await db["users"].delete_many({})

    camera_headers = await register_test_camera("cam_entrance", "ROOM_101")

    # Provision teacher user and bearer token
    await create_user(
        user_id="teacher_e2e_test",
        email="teacher@e2e.com",
        password_hash=hash_password("Password123!"),
        role="TEACHER",
    )
    teacher_token = create_access_token(user_id="teacher_e2e_test", role="TEACHER")
    auth_headers = {"Authorization": f"Bearer {teacher_token}"}

    session = SessionCreate(
        course_name="DevOps",
        classroom_id="ROOM_101",
        start_time=datetime(
            2026,
            9,
            23,
            10,
            0,
            tzinfo=timezone.utc,
        ),
        end_time=datetime(
            2026,
            9,
            23,
            11,
            0,
            tzinfo=timezone.utc,
        ),
        required_presence_percentage=75.0,
    )

    created_session = await create_session(
        session,
        created_by="teacher_e2e_test",
    )
    session_id = created_session["session_id"]

    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:

        # ---------------------------------------------------------
        # 1. Enroll session roster (Teacher Auth)
        # ---------------------------------------------------------

        roster_response = await client.post(
            f"/api/v1/sessions/{session_id}/roster",
            headers=auth_headers,
            json={
                "identities": [
                    "person_01",
                    "person_02",
                    "person_03",
                ]
            },
        )

        assert roster_response.status_code == 200

        # ---------------------------------------------------------
        # 2. Ingest actual vision events through the API (Camera / Internal)
        # ---------------------------------------------------------

        events_payload = [
            {
                "event_id": "evt_e2e_001",
                "camera_id": "cam_entrance",
                "track_id": 1,
                "identity": "person_01",
                "direction": "ENTRY",
                "timestamp": "2026-09-23T10:05:00Z",
                "evidence": {
                    "peak_similarity": 0.94,
                    "mean_similarity": 0.91,
                    "supporting_frames": 40,
                    "total_frames": 45,
                    "consistency_pct": 88.9,
                },
            },
            {
                "event_id": "evt_e2e_002",
                "camera_id": "cam_entrance",
                "track_id": 1,
                "identity": "person_01",
                "direction": "EXIT",
                "timestamp": "2026-09-23T10:55:00Z",
                "evidence": {
                    "peak_similarity": 0.95,
                    "mean_similarity": 0.93,
                    "supporting_frames": 42,
                    "total_frames": 45,
                    "consistency_pct": 93.3,
                },
            },
            {
                "event_id": "evt_e2e_003",
                "camera_id": "cam_entrance",
                "track_id": 2,
                "identity": "person_02",
                "direction": "ENTRY",
                "timestamp": "2026-09-23T10:15:00Z",
                "evidence": {
                    "peak_similarity": 0.88,
                    "mean_similarity": 0.85,
                    "supporting_frames": 30,
                    "total_frames": 40,
                    "consistency_pct": 75.0,
                },
            },
            {
                "event_id": "evt_e2e_004",
                "camera_id": "cam_entrance",
                "track_id": 2,
                "identity": "person_02",
                "direction": "EXIT",
                "timestamp": "2026-09-23T10:45:00Z",
                "evidence": {
                    "peak_similarity": 0.89,
                    "mean_similarity": 0.86,
                    "supporting_frames": 32,
                    "total_frames": 40,
                    "consistency_pct": 80.0,
                },
            },
        ]

        for payload in events_payload:
            response = await client.post(
                "/api/v1/events",
                json=payload,
                headers=camera_headers,
            )

            assert response.status_code == 201
            assert response.json()["status"] == "accepted"

        # ---------------------------------------------------------
        # 3. Finalize the session (Teacher Auth)
        # ---------------------------------------------------------

        finalize_response = await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers=auth_headers,
        )

        assert finalize_response.status_code == 200

        finalization = finalize_response.json()

        assert finalization["session_id"] == session_id
        assert len(finalization["records"]) == 3

        records = {
            record["identity"]: record
            for record in finalization["records"]
        }

        assert records["person_01"]["status"] == "PRESENT"
        assert records["person_01"]["presence_duration_seconds"] == 3000

        assert records["person_02"]["status"] == "ABSENT"
        assert records["person_02"]["presence_duration_seconds"] == 1800

        assert records["person_03"]["status"] == "ABSENT"
        assert records["person_03"]["presence_duration_seconds"] == 0

        # ---------------------------------------------------------
        # 4. Retrieve attendance through the API (Teacher Auth)
        # ---------------------------------------------------------

        attendance_response = await client.get(
            f"/api/v1/attendance/{session_id}",
            headers=auth_headers,
        )

        assert attendance_response.status_code == 200

        attendance = attendance_response.json()

        assert attendance["session_id"] == session_id
        assert len(attendance["records"]) == 3

        attendance_by_identity = {
            record["identity"]: record
            for record in attendance["records"]
        }

        assert attendance_by_identity["person_01"]["status"] == "PRESENT"
        assert attendance_by_identity["person_02"]["status"] == "ABSENT"
        assert attendance_by_identity["person_03"]["status"] == "ABSENT"

        # ---------------------------------------------------------
        # 5. Finalize the same session again (idempotency check)
        # ---------------------------------------------------------

        second_finalize_response = await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers=auth_headers,
        )

        assert second_finalize_response.status_code == 200

        second_finalization = second_finalize_response.json()

        assert len(second_finalization["records"]) == 3

        # The database must still contain exactly three records.
        stored_records = await db["attendance_records"].find(
            {"session_id": session_id}
        ).to_list(length=None)

        assert len(stored_records) == 3
