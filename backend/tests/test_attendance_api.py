from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.database.attendance import create_attendance
from app.database.users import create_user
from app.main import app
from app.schemas.attendance import (
    AttendanceInterval,
    AttendanceRecord,
)
from app.security.jwt import create_access_token
from app.security.passwords import hash_password


@pytest.fixture(autouse=True)
async def setup_test_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await db["sessions"].delete_many({})
    await db["attendance_records"].delete_many({})
    await db["users"].delete_many({})
    yield
    await db["sessions"].delete_many({})
    await db["attendance_records"].delete_many({})
    await db["users"].delete_many({})


@pytest.fixture
async def teacher_auth_headers():
    await create_user(
        user_id="teacher_att_api_test",
        email="teacher@attapi.com",
        password_hash=hash_password("Password123!"),
        role="TEACHER",
    )
    token = create_access_token(user_id="teacher_att_api_test", role="TEACHER")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
async def test_get_session_attendance(teacher_auth_headers):
    db = mongodb.get_database()
    await db["sessions"].insert_one({
        "session_id": "session_api_001",
        "created_by": "teacher_att_api_test",
        "created_at": datetime.now(timezone.utc),
    })

    record = AttendanceRecord(
        attendance_id="att_api_001",
        session_id="session_api_001",
        identity="person_01",
        presence_intervals=[
            AttendanceInterval(
                entry_time=datetime(
                    2026, 9, 29, 10, 0, tzinfo=timezone.utc
                ),
                exit_time=datetime(
                    2026, 9, 29, 10, 50, tzinfo=timezone.utc
                ),
            )
        ],
        presence_duration_seconds=3000,
        presence_percentage=83.33,
        required_presence_percentage=75.0,
        status="PRESENT",
    )

    await create_attendance(record)

    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/attendance/session_api_001",
            headers=teacher_auth_headers,
        )

    assert response.status_code == 200

    data = response.json()

    assert data["session_id"] == "session_api_001"
    assert len(data["records"]) == 1

    attendance = data["records"][0]

    assert attendance["attendance_id"] == "att_api_001"
    assert attendance["identity"] == "person_01"
    assert attendance["presence_duration_seconds"] == 3000
    assert attendance["presence_percentage"] == 83.33
    assert attendance["required_presence_percentage"] == 75.0
    assert attendance["status"] == "PRESENT"


@pytest.mark.anyio
async def test_get_session_attendance_empty(teacher_auth_headers):
    db = mongodb.get_database()
    await db["sessions"].insert_one({
        "session_id": "empty_session_001",
        "created_by": "teacher_att_api_test",
        "created_at": datetime.now(timezone.utc),
    })

    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/attendance/empty_session_001",
            headers=teacher_auth_headers,
        )

    assert response.status_code == 200

    data = response.json()

    assert data["session_id"] == "empty_session_001"
    assert data["records"] == []


@pytest.mark.anyio
async def test_get_session_attendance_nonexistent_returns_404(teacher_auth_headers):
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/attendance/nonexistent_session",
            headers=teacher_auth_headers,
        )

    assert response.status_code == 404
