from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password


@pytest.fixture(autouse=True)
async def setup_test_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await db["sessions"].delete_many({})
    await db["users"].delete_many({})
    yield
    await db["sessions"].delete_many({})
    await db["users"].delete_many({})


@pytest.fixture
async def teacher_auth_headers():
    await create_user(
        user_id="teacher_session_test",
        email="teacher@sessiontest.com",
        password_hash=hash_password("Password123!"),
        role="TEACHER",
    )
    token = create_access_token(user_id="teacher_session_test", role="TEACHER")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
async def test_create_session_api(teacher_auth_headers):
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/sessions",
            headers=teacher_auth_headers,
            json={
                "course_name": "DevOps",
                "classroom_id": "ROOM_101",
                "start_time": "2026-09-29T10:00:00Z",
                "end_time": "2026-09-29T11:00:00Z",
                "required_presence_percentage": 75.0,
            },
        )

    assert response.status_code == 201

    body = response.json()

    assert body["session_id"].startswith("session_")
    assert body["course_name"] == "DevOps"
    assert body["classroom_id"] == "ROOM_101"
    assert body["start_time"] == "2026-09-29T10:00:00Z"
    assert body["end_time"] == "2026-09-29T11:00:00Z"
    assert body["required_presence_percentage"] == 75.0
    assert body["status"] == "SCHEDULED"


@pytest.mark.anyio
async def test_create_session_rejects_invalid_presence_percentage(teacher_auth_headers):
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/sessions",
            headers=teacher_auth_headers,
            json={
                "course_name": "DevOps",
                "classroom_id": "ROOM_101",
                "start_time": "2026-09-29T10:00:00Z",
                "end_time": "2026-09-29T11:00:00Z",
                "required_presence_percentage": 150.0,
            },
        )

    assert response.status_code == 422
