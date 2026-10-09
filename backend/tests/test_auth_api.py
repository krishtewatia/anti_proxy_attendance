import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.main import app
from app.security.jwt import decode_access_token
from tests.conftest import approve_account


@pytest.fixture(autouse=True)
async def setup_test_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await db["users"].delete_many({})
    yield
    await db["users"].delete_many({})


@pytest.mark.anyio
async def test_register_teacher_api_success():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "teacher.api@example.com",
                "password": "validPassword123!",
                "role": "TEACHER",
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["user_id"].startswith("user_")
    assert body["email"] == "teacher.api@example.com"
    assert body["role"] == "TEACHER"
    assert body["is_active"] is True
    assert "password_hash" not in body
    assert "password" not in body


@pytest.mark.anyio
async def test_register_student_api_success():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "student.api@example.com",
                "password": "validPassword123!",
                "role": "STUDENT",
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "student.api@example.com"
    assert body["role"] == "STUDENT"
    assert body["is_active"] is True


@pytest.mark.anyio
async def test_register_normalizes_email_to_lowercase():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "MixedCase.User@Example.COM",
                "password": "validPassword123!",
                "role": "TEACHER",
            },
        )

    assert response.status_code == 201
    assert response.json()["email"] == "mixedcase.user@example.com"


@pytest.mark.anyio
async def test_register_admin_rejected_by_validation():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "admin@example.com",
                "password": "validPassword123!",
                "role": "ADMIN",
            },
        )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_register_duplicate_email_returns_409():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First registration
        res1 = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "duplicate.api@example.com",
                "password": "validPassword123!",
                "role": "TEACHER",
            },
        )
        assert res1.status_code == 201

        # Second registration with same email
        res2 = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "DUPLICATE.API@example.com",
                "password": "anotherPassword456!",
                "role": "STUDENT",
            },
        )

    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"]


@pytest.mark.anyio
async def test_register_rejects_short_password():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "shortpass@example.com",
                "password": "short",
                "role": "TEACHER",
            },
        )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_login_api_success():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register user
        reg_res = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "login.user@example.com",
                "password": "correctSecretPassword123!",
                "role": "TEACHER",
            },
        )
        assert reg_res.status_code == 201
        registered_id = reg_res.json()["user_id"]

        # A new registration cannot log in until an administrator approves it
        pending_res = await client.post(
            "/api/v1/auth/login",
            json={"email": "login.user@example.com", "password": "correctSecretPassword123!"},
        )
        assert pending_res.status_code == 403
        assert pending_res.json()["detail"]["code"] == "account_pending"
        assert "awaiting admin approval" in pending_res.json()["detail"]["message"]
        await approve_account(registered_id)

        # Login
        login_res = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "LOGIN.USER@example.com",
                "password": "correctSecretPassword123!",
            },
        )

    assert login_res.status_code == 200
    body = login_res.json()
    assert body["token_type"] == "bearer"
    assert "access_token" in body
    assert body["user"]["user_id"] == registered_id
    assert body["user"]["email"] == "login.user@example.com"
    assert body["user"]["role"] == "TEACHER"

    claims = decode_access_token(body["access_token"])
    assert claims["sub"] == registered_id
    assert claims["role"] == "TEACHER"


@pytest.mark.anyio
async def test_login_api_wrong_password_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "user.wrongpass@example.com",
                "password": "correctPassword123!",
                "role": "STUDENT",
            },
        )

        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "user.wrongpass@example.com",
                "password": "wrongPassword123!",
            },
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.anyio
async def test_login_api_unknown_email_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "nonexistent.user@example.com",
                "password": "anyPassword123!",
            },
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"
    assert response.headers.get("www-authenticate") == "Bearer"
