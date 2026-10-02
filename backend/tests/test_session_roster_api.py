from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.database.users import create_user
from app.main import app
from app.schemas.session import SessionCreate
from app.security.jwt import create_access_token
from app.security.passwords import hash_password


@pytest.fixture(autouse=True)
async def setup_test_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await db["sessions"].delete_many({})
    await db["session_rosters"].delete_many({})
    await db["users"].delete_many({})
    yield
    await db["sessions"].delete_many({})
    await db["session_rosters"].delete_many({})
    await db["users"].delete_many({})


@pytest.fixture
async def teacher_auth_headers():
    await create_user(
        user_id="teacher_roster_test",
        email="teacher@rostertest.com",
        password_hash=hash_password("Password123!"),
        role="TEACHER",
    )
    token = create_access_token(user_id="teacher_roster_test", role="TEACHER")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def seeded_session():
    db = mongodb.get_database()
    session_doc = {
        "session_id": "session_api_001",
        "course_name": "DevOps",
        "classroom_id": "ROOM_101",
        "start_time": datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc),
        "end_time": datetime(2026, 9, 29, 11, 0, tzinfo=timezone.utc),
        "required_presence_percentage": 75.0,
        "status": "SCHEDULED",
        "created_by": "teacher_roster_test",
        "created_at": datetime.now(timezone.utc),
    }
    await db["sessions"].insert_one(session_doc)
    return session_doc


@pytest.mark.anyio
async def test_create_and_get_session_roster(teacher_auth_headers, seeded_session):
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/sessions/session_api_001/roster",
            headers=teacher_auth_headers,
            json={
                "identities": [
                    "person_01",
                    "person_02",
                    "person_03",
                ]
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body == {
            "session_id": "session_api_001",
            "identities": [
                "person_01",
                "person_02",
                "person_03",
            ],
        }

        response = await client.get(
            "/api/v1/sessions/session_api_001/roster",
            headers=teacher_auth_headers,
        )

        assert response.status_code == 200

        assert response.json() == {
            "session_id": "session_api_001",
            "identities": [
                "person_01",
                "person_02",
                "person_03",
            ],
        }


@pytest.mark.anyio
async def test_get_missing_session_roster_returns_404(teacher_auth_headers):
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/sessions/session_does_not_exist/roster",
            headers=teacher_auth_headers,
        )

        assert response.status_code == 404


@pytest.mark.anyio
async def test_session_roster_rejects_extra_fields(teacher_auth_headers, seeded_session):
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/sessions/session_api_001/roster",
            headers=teacher_auth_headers,
            json={
                "identities": ["person_01"],
                "unexpected": "field",
            },
        )

    assert response.status_code == 422
