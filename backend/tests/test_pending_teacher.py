"""A teacher signs in straight after sign-up but can do nothing until an
administrator approves them and assigns their classes."""

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.database import mongodb
from app.database.mongodb import init_indexes
from app.main import app

PASSWORD = "PendingTeacher123!"


@pytest.fixture(autouse=True)
async def fresh_db():
    mongodb._client = AsyncMongoMockClient()
    await init_indexes(mongodb.get_database())
    yield
    mongodb._client = AsyncMongoMockClient()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _signed_in_teacher(client: AsyncClient) -> dict[str, str]:
    registered = await client.post(
        "/api/v1/teachers/register",
        json={"name": "Waiting Teacher", "email": "waiting@college.test", "password": PASSWORD},
    )
    assert registered.status_code == 201
    login = await client.post("/api/v1/auth/login", json={"email": "waiting@college.test", "password": PASSWORD})
    assert login.status_code == 200 and login.json()["user"]["role"] == "TEACHER"
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.anyio
async def test_a_pending_teacher_signs_in_but_every_teacher_route_is_refused():
    async with _client() as client:
        headers = await _signed_in_teacher(client)
        attempts = [
            await client.get("/api/v1/teachers/dashboard", headers=headers),
            await client.get("/api/v1/sessions", headers=headers),
            await client.post("/api/v1/sessions", headers=headers, json={"course_name": "x", "class_code": "DS-B", "subject": "ML"}),
            await client.post("/api/v1/sessions/any/start", headers=headers),
            await client.get("/api/v1/sessions/any/roster", headers=headers),
            await client.get("/api/v1/students/directory", headers=headers),
            await client.post("/api/v1/attendance/any/process-frame", headers=headers, files={"frame": ("f.jpg", b"x", "image/jpeg")}),
            await client.get("/api/v1/audit", headers=headers),
        ]
        password = await client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={"current_password": PASSWORD, "new_password": "PendingTeacher456!"},
        )
    for response in attempts:
        assert response.status_code == 403, (response.request.url, response.status_code)
        assert response.json()["detail"]["code"] == "teacher_pending"
    # Changing their own password is still possible.
    assert password.status_code == 200


@pytest.mark.anyio
async def test_an_approved_teacher_is_not_affected():
    db = mongodb.get_database()
    async with _client() as client:
        headers = await _signed_in_teacher(client)
        await db["users"].update_one({"email": "waiting@college.test"}, {"$set": {"status": "APPROVED"}})
        dashboard = await client.get("/api/v1/teachers/dashboard", headers=headers)
    assert dashboard.status_code == 200
