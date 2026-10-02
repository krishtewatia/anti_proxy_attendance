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
from app.services.session_enrollment import enroll_session_roster


@pytest.fixture
async def teacher_auth_headers():
    await create_user(
        user_id="teacher_finalization_test",
        email="teacher@finalize.com",
        password_hash=hash_password("Password123!"),
        role="TEACHER",
    )
    token = create_access_token(user_id="teacher_finalization_test", role="TEACHER")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
async def test_finalize_session_api(teacher_auth_headers):
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()

    await db["sessions"].delete_many({})
    await db["session_rosters"].delete_many({})
    await db["attendance_events"].delete_many({})
    await db["attendance_records"].delete_many({})
    await db["users"].delete_many({})

    # Re-provision teacher after deleting users
    await create_user(
        user_id="teacher_finalization_test",
        email="teacher@finalize.com",
        password_hash=hash_password("Password123!"),
        role="TEACHER",
    )

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
        created_by="teacher_finalization_test",
    )
    session_id = created_session["session_id"]

    await enroll_session_roster(
        session_id=session_id,
        identities=[
            "person_01",
            "person_02",
            "person_03",
        ],
    )

    events_collection = db["attendance_events"]

    await events_collection.insert_many(
        [
            {
                "event_id": "evt_fin_001",
                "camera_id": "cam_01",
                "track_id": 1,
                "identity": "person_01",
                "direction": "ENTRY",
                "timestamp": datetime(
                    2026,
                    9,
                    23,
                    10,
                    5,
                    tzinfo=timezone.utc,
                ),
                "evidence": {},
            },
            {
                "event_id": "evt_fin_002",
                "camera_id": "cam_01",
                "track_id": 1,
                "identity": "person_01",
                "direction": "EXIT",
                "timestamp": datetime(
                    2026,
                    9,
                    23,
                    10,
                    50,
                    tzinfo=timezone.utc,
                ),
                "evidence": {},
            },
        ]
    )

    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers=teacher_auth_headers,
        )

    assert response.status_code == 200

    body = response.json()

    assert body["session_id"] == session_id
    assert len(body["records"]) == 3

    records = {
        record["identity"]: record
        for record in body["records"]
    }

    assert records["person_01"]["status"] == "PRESENT"
    assert records["person_02"]["status"] == "ABSENT"
    assert records["person_03"]["status"] == "ABSENT"


@pytest.mark.anyio
async def test_finalize_missing_session_returns_404(teacher_auth_headers):
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await db["users"].delete_many({})
    await create_user(
        user_id="teacher_finalization_test",
        email="teacher@finalize.com",
        password_hash=hash_password("Password123!"),
        role="TEACHER",
    )

    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/sessions/session_does_not_exist/finalize",
            headers=teacher_auth_headers,
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


@pytest.mark.anyio
async def test_finalize_without_roster_returns_404(teacher_auth_headers):
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()

    await db["sessions"].delete_many({})
    await db["session_rosters"].delete_many({})
    await db["users"].delete_many({})
    await create_user(
        user_id="teacher_finalization_test",
        email="teacher@finalize.com",
        password_hash=hash_password("Password123!"),
        role="TEACHER",
    )

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
        created_by="teacher_finalization_test",
    )

    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/v1/sessions/{created_session['session_id']}/finalize",
            headers=teacher_auth_headers,
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Session roster not found"
