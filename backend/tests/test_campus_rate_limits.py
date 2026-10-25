"""Rate limits that protect against abuse without blocking a classroom.

On campus Wi-Fi every student shares one public address. The per-address
limits are therefore only ceilings against floods; the tight limits are per
email, per roll number and per account. Everything here comes from one test
client, that is, one address. Names and numbers are made up.
"""

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.core.config import settings
from app.database import mongodb
from app.database.mongodb import init_indexes
from app.database.users import create_user
from app.main import app
from app.security.passwords import hash_password

PASSWORD = "CampusPass123!"


@pytest.fixture(autouse=True)
async def fresh_db():
    mongodb._client = AsyncMongoMockClient()
    await init_indexes(mongodb.get_database())
    yield
    mongodb._client = AsyncMongoMockClient()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _student(n: int, email: str | None = None, roll: str | None = None) -> dict:
    return {
        "name": f"Campus Student {n}",
        "email": email or f"campus{n}@college.test",
        "password": PASSWORD,
        "roll_number": roll or f"24013315{n:05d}",
        "branch": "Data Science",
        "section": "B",
    }


@pytest.mark.anyio
async def test_sixty_students_register_from_one_address():
    async with _client() as client:
        statuses = [
            (await client.post("/api/v1/students/register", json=_student(n))).status_code
            for n in range(60)
        ]
    assert statuses == [201] * 60
    assert await mongodb.get_database()["users"].count_documents({}) == 60


@pytest.mark.anyio
async def test_the_address_ceiling_still_stops_a_flood(monkeypatch):
    monkeypatch.setattr(settings, "REGISTRATION_RATE_LIMIT_PER_HOUR", 3)
    async with _client() as client:
        responses = [await client.post("/api/v1/students/register", json=_student(n)) for n in range(4)]
    assert [r.status_code for r in responses] == [201, 201, 201, 429]
    assert "one address" in responses[3].json()["detail"]
    assert int(responses[3].headers["Retry-After"]) > 0


@pytest.mark.anyio
async def test_attempts_are_limited_per_email_and_per_roll_number():
    async with _client() as client:
        same_email = [
            (await client.post("/api/v1/students/register", json=_student(n, email="target@college.test"))).status_code
            for n in range(100, 106)
        ]
        same_roll = [
            (await client.post("/api/v1/students/register", json=_student(n, roll="2401331599999"))).status_code
            for n in range(200, 206)
        ]
        teacher_email = [
            (
                await client.post(
                    "/api/v1/teachers/register",
                    json={"name": "Campus Teacher", "email": "t.target@college.test", "password": PASSWORD},
                )
            ).status_code
            for _ in range(6)
        ]
        other = await client.post("/api/v1/students/register", json=_student(300))
    # The first attempt registers; repeats are refused as duplicates until the
    # sixth attempt for the same email or roll number, which is rate limited.
    assert same_email == [201, 409, 409, 409, 409, 429]
    assert same_roll == [201, 409, 409, 409, 409, 429]
    assert teacher_email == [201, 409, 409, 409, 409, 429]
    # Other students on the same address are not affected.
    assert other.status_code == 201


@pytest.mark.anyio
async def test_photo_checks_are_limited_per_student_not_per_address(monkeypatch, stub_vision_embedding):
    monkeypatch.setattr(settings, "PHOTO_CHECKS_PER_HOUR", 2)
    async with _client() as client:
        tokens = []
        for n in (1, 2):
            await client.post("/api/v1/students/register", json=_student(n))
            login = await client.post("/api/v1/auth/login", json={"email": f"campus{n}@college.test", "password": PASSWORD})
            tokens.append({"Authorization": f"Bearer {login.json()['access_token']}"})
        check = {"photo_base64": "aGVsbG8="}
        first = [(await client.post("/api/v1/enrolment/photos/check", headers=tokens[0], json=check)).status_code for _ in range(3)]
        second = [(await client.post("/api/v1/enrolment/photos/check", headers=tokens[1], json=check)).status_code for _ in range(2)]
    assert first[2] == 429 and 429 not in first[:2]
    assert 429 not in second


@pytest.mark.anyio
async def test_a_class_with_typos_on_one_address_can_still_sign_in():
    password_hash = hash_password(PASSWORD)
    for n in range(60):
        await create_user(
            user_id=f"login_{n}", email=f"login{n}@college.test", password_hash=password_hash, role="STUDENT"
        )
    async with _client() as client:
        failures = [
            (await client.post("/api/v1/auth/login", json={"email": f"login{n}@college.test", "password": "wrong"})).status_code
            for n in range(60)
            for _ in range(2)
        ]
        signed_in = [
            (await client.post("/api/v1/auth/login", json={"email": f"login{n}@college.test", "password": PASSWORD})).status_code
            for n in range(60)
        ]
    assert set(failures) == {401}
    assert signed_in == [200] * 60


@pytest.mark.anyio
async def test_one_account_still_locks_after_five_failures():
    await create_user(
        user_id="locked", email="locked@college.test", password_hash=hash_password(PASSWORD), role="STUDENT"
    )
    async with _client() as client:
        attempts = [
            (await client.post("/api/v1/auth/login", json={"email": "locked@college.test", "password": "wrong"})).status_code
            for _ in range(6)
        ]
        correct = await client.post("/api/v1/auth/login", json={"email": "locked@college.test", "password": PASSWORD})
    assert attempts == [401] * 5 + [429]
    assert correct.status_code == 429
