"""Pilot accounts: college email only once the structure exists, roll number
instead of a student ID, no teacher ID, and the photo notice a student accepts
before sending a photo of their face.

The vision service is stubbed and photos are placeholder bytes.
"""

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.database import mongodb
from app.database.mongodb import init_indexes
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from app.services import approval_service, organisation_service, student_deletion
from app.services.registration_rules import CONSENT_NOTICE_VERSION

PASSWORD = "PilotAccounts123!"
PHOTO_B64 = "cGxhY2Vob2xkZXIgcGhvdG8gYnl0ZXM="  # placeholder bytes, not an image of anyone
APPROVALS = "/api/v1/admin/approvals"


@pytest.fixture(autouse=True)
async def fresh_db(monkeypatch):
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await init_indexes(db)
    await db["academic_classes"].insert_one(
        {"class_id": "DS-B", "class_code": "DS-B", "branch": "Data Science", "section": "B"}
    )

    async def fake_refresh() -> bool:
        return True

    monkeypatch.setattr(student_deletion, "_refresh_vision_gallery", fake_refresh)
    monkeypatch.setattr(approval_service, "_refresh_vision_gallery", fake_refresh)
    yield
    mongodb._client = AsyncMongoMockClient()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _admin() -> dict[str, str]:
    await create_user(
        user_id="admin_pa", email="admin@pilot.test",
        password_hash=hash_password(PASSWORD), role="ADMIN",
    )
    return {"Authorization": f"Bearer {create_access_token(user_id='admin_pa', role='ADMIN')}"}


async def _pilot_structure() -> None:
    await organisation_service.seed_structure(mongodb.get_database())


def _student(roll: str, email: str, **extra) -> dict:
    return {
        "name": "Pilot Student",
        "email": email,
        "password": PASSWORD,
        "roll_number": roll,
        "class_code": "DS-B",
        **extra,
    }


def _teacher(email: str) -> dict:
    return {"name": "Pilot Teacher", "email": email, "password": PASSWORD}


async def _login(client: AsyncClient, email: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.anyio
async def test_any_address_is_accepted_until_the_structure_exists():
    async with _client() as client:
        rules = (await client.get("/api/v1/auth/registration-rules")).json()
        student = await client.post("/api/v1/students/register", json=_student("2401331540001", "a@gmail.com"))
    assert rules["college_email_domain"] is None
    assert rules["consent_notice"]["version"] == CONSENT_NOTICE_VERSION
    assert student.status_code == 201


@pytest.mark.anyio
async def test_once_the_structure_exists_only_the_college_domain_registers():
    await _pilot_structure()
    async with _client() as client:
        rules = (await client.get("/api/v1/auth/registration-rules")).json()
        refused = [
            await client.post("/api/v1/students/register", json=_student("2401331540001", "a@gmail.com")),
            await client.post("/api/v1/teachers/register", json=_teacher("t@gmail.com")),
            await client.post("/api/v1/auth/register", json={"email": "x@niet.co.in.evil.test", "password": PASSWORD, "role": "STUDENT"}),
        ]
        accepted = [
            await client.post("/api/v1/students/register", json=_student("2401331540001", "a.student@niet.co.in")),
            await client.post("/api/v1/teachers/register", json=_teacher("A.Teacher@NIET.co.in")),
        ]
    assert rules["college_email_domain"] == "niet.co.in"
    assert [r.status_code for r in refused] == [400, 400, 400]
    assert "@niet.co.in" in refused[0].json()["detail"]
    assert [r.status_code for r in accepted] == [201, 201]
    assert await mongodb.get_database()["users"].count_documents({}) == 2


@pytest.mark.anyio
async def test_the_domain_follows_the_setting_and_applies_to_administrators_too():
    admin = await _admin()
    await _pilot_structure()
    async with _client() as client:
        await client.put("/api/v1/admin/org/settings", json={"college_email_domain": "niet.edu"}, headers=admin)
        old_domain = await client.post("/api/v1/students/register", json=_student("2401331540011", "r1@niet.co.in"))
        new_domain = await client.post("/api/v1/students/register", json=_student("2401331540011", "r1@niet.edu"))
        by_admin = await client.post("/api/v1/admin/teachers", json=_teacher("t@gmail.com"), headers=admin)
    assert (old_domain.status_code, new_domain.status_code, by_admin.status_code) == (400, 201, 400)


@pytest.mark.anyio
async def test_students_are_known_by_a_unique_roll_number_and_get_an_internal_id():
    async with _client() as client:
        first = await client.post("/api/v1/students/register", json=_student(" 2401331540142 ", "s1@pilot.test"))
        same_roll = await client.post("/api/v1/students/register", json=_student("2401331540142", "s2@pilot.test"))
        unsafe = await client.post("/api/v1/students/register", json=_student("../etc", "s3@pilot.test"))
        second = await client.post("/api/v1/students/register", json=_student("2401331540143", "s4@pilot.test"))
    assert first.status_code == 201
    body = first.json()
    assert body["roll_number"] == "2401331540142"
    assert body["student_id"].startswith("stu_") and body["identity"] == body["student_id"]
    assert same_roll.status_code == 409 and "2401331540142" in same_roll.json()["detail"]
    assert unsafe.status_code == 422
    assert second.status_code == 201 and second.json()["student_id"] != body["student_id"]


@pytest.mark.anyio
async def test_teachers_need_no_teacher_id():
    async with _client() as client:
        first = await client.post("/api/v1/teachers/register", json=_teacher("t1@pilot.test"))
        second = await client.post("/api/v1/teachers/register", json=_teacher("t2@pilot.test"))
    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json()["teacher_id"].startswith("tch_")
    assert first.json()["teacher_id"] != second.json()["teacher_id"]
    assert first.json()["department"] == "CSE-DS"


@pytest.mark.anyio
async def test_a_student_photo_needs_the_current_notice_accepted(stub_vision_embedding):
    db = mongodb.get_database()
    async with _client() as client:
        without = await client.post(
            "/api/v1/students/register", json=_student("2401331540021", "r1@pilot.test", photo_base64=PHOTO_B64)
        )
        old_notice = await client.post(
            "/api/v1/students/register",
            json=_student("2401331540021", "r1@pilot.test", photo_base64=PHOTO_B64, consent_version="older"),
        )
        with_notice = await client.post(
            "/api/v1/students/register",
            json=_student("2401331540021", "r1@pilot.test", photo_base64=PHOTO_B64, consent_version=CONSENT_NOTICE_VERSION),
        )
    assert (without.status_code, old_notice.status_code) == (400, 400)
    assert "notice" in without.json()["detail"]
    assert with_notice.status_code == 201 and with_notice.json()["has_biometric"] is True
    # Nothing was left behind by the refused attempts.
    assert await db["users"].count_documents({}) == 1
    consent = await db["consents"].find_one({"user_id": with_notice.json()["user_id"]})
    assert consent["notice_version"] == CONSENT_NOTICE_VERSION and consent["accepted_at"]


@pytest.mark.anyio
async def test_a_student_accepts_the_notice_before_changing_their_photo(stub_vision_embedding):
    admin = await _admin()
    db = mongodb.get_database()
    async with _client() as client:
        # No photo at sign-up: no notice needed yet.
        registered = await client.post("/api/v1/students/register", json=_student("2401331540022", "r2@pilot.test"))
        assert registered.status_code == 201
        await client.post(f"{APPROVALS}/{registered.json()['user_id']}/approve", headers=admin, json={})
        student = await _login(client, "r2@pilot.test")

        before = (await client.get("/api/v1/students/consent", headers=student)).json()
        refused = await client.post("/api/v1/students/photo", headers=student, json={"photo_base64": PHOTO_B64})
        stale = await client.post("/api/v1/students/consent", headers=student, json={"version": "older"})
        accepted = await client.post("/api/v1/students/consent", headers=student, json={"version": CONSENT_NOTICE_VERSION})
        again = await client.post("/api/v1/students/consent", headers=student, json={"version": CONSENT_NOTICE_VERSION})
        uploaded = await client.post("/api/v1/students/photo", headers=student, json={"photo_base64": PHOTO_B64})
        as_admin = await client.get("/api/v1/students/consent", headers=admin)

    assert before["accepted"] is False and before["notice"]["points"]
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "consent_required"
    assert stale.status_code == 409
    assert accepted.status_code == 200 and accepted.json()["accepted"] is True
    assert again.status_code == 200 and await db["consents"].count_documents({}) == 1
    assert uploaded.status_code == 200 and uploaded.json()["status"] == "pending_review"
    assert as_admin.status_code == 403
    assert await db["audit_events"].count_documents({"action": "CONSENT_ACCEPTED"}) == 2


@pytest.mark.anyio
async def test_an_administrator_adding_a_photo_needs_no_student_notice(stub_vision_embedding):
    admin = await _admin()
    async with _client() as client:
        created = await client.post(
            "/api/v1/admin/students", headers=admin, json=_student("2401331540023", "r3@pilot.test", photo_base64=PHOTO_B64)
        )
    assert created.status_code == 201 and created.json()["has_biometric"] is True
    assert created.json()["student_id"].startswith("stu_")


@pytest.mark.anyio
async def test_deleting_a_student_deletes_their_consent(stub_vision_embedding):
    admin = await _admin()
    db = mongodb.get_database()
    async with _client() as client:
        registered = await client.post(
            "/api/v1/students/register",
            json=_student("2401331540024", "r4@pilot.test", photo_base64=PHOTO_B64, consent_version=CONSENT_NOTICE_VERSION),
        )
        user_id = registered.json()["user_id"]
        assert await db["consents"].count_documents({"user_id": user_id}) == 1
        deleted = await client.delete(f"/api/v1/admin/students/{user_id}", headers=admin)
    assert deleted.status_code == 200
    assert await db["consents"].count_documents({"user_id": user_id}) == 0


@pytest.mark.anyio
async def test_administrator_edits_keep_the_roll_number_and_domain_rules():
    admin = await _admin()
    async with _client() as client:
        one = (await client.post("/api/v1/students/register", json=_student("2401331540025", "r5@niet.co.in"))).json()
        await client.post("/api/v1/students/register", json=_student("2401331540026", "r6@niet.co.in"))
        await _pilot_structure()
        edit = f"/api/v1/admin/students/{one['user_id']}"
        taken = await client.patch(edit, headers=admin, json={"roll_number": "2401331540026"})
        unsafe = await client.patch(edit, headers=admin, json={"roll_number": "24013-AB"})
        own_case = await client.patch(edit, headers=admin, json={"roll_number": " 2401331540025 "})
        outside = await client.patch(edit, headers=admin, json={"email": "r5@gmail.com"})
    assert (taken.status_code, unsafe.status_code) == (409, 400)
    assert own_case.status_code == 200
    assert outside.status_code == 400 and "@niet.co.in" in outside.json()["detail"]


@pytest.mark.anyio
async def test_a_roll_number_is_digits_only_and_not_tied_to_the_email():
    await _pilot_structure()
    async with _client() as client:
        real = await client.post("/api/v1/students/register", json=_student("2401331540142", "anyname@niet.co.in"))
        refused = [
            await client.post("/api/v1/students/register", json=_student(roll, f"x{i}@niet.co.in"))
            for i, roll in enumerate(("0241CSDS030", "2401-3315", "1234567", "1" * 21))
        ]
    assert real.status_code == 201 and real.json()["roll_number"] == "2401331540142"
    assert [r.status_code for r in refused] == [422, 422, 422, 422]


@pytest.mark.anyio
async def test_eight_digits_is_the_shortest_roll_number():
    async with _client() as client:
        shortest = await client.post("/api/v1/students/register", json=_student("12345678", "y@niet.co.in"))
    assert shortest.status_code == 201
