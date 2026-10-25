"""The admin registries: every student with the status the admin acts on,
organised by year, branch and section; teachers with their classes.

Names and numbers are made up; the vision service is stubbed.
"""

from types import SimpleNamespace

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.core.config import settings
from app.database import mongodb
from app.database.mongodb import init_indexes
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from app.services import approval_service, student_biometric_service, student_deletion
from app.services import organisation_service as org
from app.services.registration_rules import CONSENT_NOTICE_VERSION
from tests.test_enrolment_requests import COHORT, SHEET, TERM, _photo, _Vision

PASSWORD = "Registry123!"
CHOICES = {
    "DE-II": {"option": "PA", "group": "G2"},
    "DE-III": {"option": "DP", "group": "DP"},
    "DLDA": {"option": "DLDA", "group": "DL3"},
}


@pytest.fixture(autouse=True)
async def fresh_db(monkeypatch):
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await init_indexes(db)
    await org.seed_structure(db)
    await org.import_timetable(db, COHORT, SHEET, source_name="ds3.csv", actor_user_id="seed")

    async def fake_refresh() -> bool:
        return True

    monkeypatch.setattr(student_deletion, "_refresh_vision_gallery", fake_refresh)
    monkeypatch.setattr(approval_service, "_refresh_vision_gallery", fake_refresh)
    monkeypatch.setattr(student_biometric_service, "httpx", SimpleNamespace(AsyncClient=_Vision))
    monkeypatch.setattr(settings, "REGISTRATION_RATE_LIMIT_PER_HOUR", 100)
    yield
    mongodb._client = AsyncMongoMockClient()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _admin() -> dict[str, str]:
    await create_user(user_id="admin_reg", email="reg@niet.co.in", password_hash=hash_password(PASSWORD), role="ADMIN")
    return {"Authorization": f"Bearer {create_access_token(user_id='admin_reg', role='ADMIN')}"}


async def _student(client, roll, section=None, choices=None) -> dict:
    email = f"s{roll[-3:]}@niet.co.in"
    registered = await client.post(
        "/api/v1/students/register",
        json={"name": f"Student {roll[-3:]}", "email": email, "password": PASSWORD, "roll_number": roll},
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    request_id = None
    if section:
        sent = await client.post(
            "/api/v1/enrolment/requests",
            headers=headers,
            json={"cohort_id": COHORT, "section": section, "choices": choices or CHOICES,
                  "photos": [_photo("a1"), _photo("a2")], "consent_version": CONSENT_NOTICE_VERSION},
        )
        request_id = sent.json()["request_id"]
    return {"user_id": registered.json()["user_id"], "headers": headers, "request_id": request_id}


@pytest.mark.anyio
async def test_every_student_appears_with_the_status_to_act_on():
    admin = await _admin()
    async with _client() as client:
        approved = await _student(client, "2401331540701", "B")
        await client.post(f"/api/v1/admin/enrolment/requests/{approved['request_id']}/approve", headers=admin)
        changing = await _student(client, "2401331540702", "B")
        await client.post(f"/api/v1/admin/enrolment/requests/{changing['request_id']}/approve", headers=admin)
        await client.post(
            "/api/v1/enrolment/requests", headers=changing["headers"],
            json={"cohort_id": COHORT, "section": "B", "choices": {**CHOICES, "DLDA": {"option": "DLDA", "group": "DL1"}}},
        )
        await _student(client, "2401331540703", "C", {**CHOICES, "DE-II": {"option": "PA", "group": "G1"}})
        await _student(client, "2401331540704")
        everyone = (await client.get("/api/v1/admin/registry/students", headers=admin)).json()
        section_b = (await client.get("/api/v1/admin/registry/students", headers=admin, params={"cohort_id": COHORT, "section": "B"})).json()
        group_g1 = (await client.get("/api/v1/admin/registry/students", headers=admin, params={"set_code": "DE-II", "group": "G1"})).json()
        waiting = (await client.get("/api/v1/admin/registry/students", headers=admin, params={"status": "waiting"})).json()
        search = (await client.get("/api/v1/admin/registry/students", headers=admin, params={"q": "540704"})).json()
        as_student = await client.get("/api/v1/admin/registry/students", headers=approved["headers"])
    status = {s["roll_number"]: s["status"] for s in everyone["students"]}
    assert status == {
        "2401331540701": "APPROVED",
        "2401331540702": "CHANGE_WAITING",
        "2401331540703": "WAITING",
        "2401331540704": "NO_SETUP",
    }
    row = next(s for s in everyone["students"] if s["roll_number"] == "2401331540702")
    # A waiting change does not replace what is approved.
    assert row["choices"]["DLDA"]["group"] == "DL3" and row["section"] == "B" and row["year"] == 3
    assert everyone["counts"]["no_setup"] == 1
    cohort = everyone["counts"]["cohorts"][COHORT]
    assert cohort["sections"]["B"] == {"total": 2, "approved": 2, "waiting": 1}
    assert cohort["sections"]["C"] == {"total": 1, "approved": 0, "waiting": 1}
    assert [s["roll_number"] for s in section_b["students"]] == ["2401331540701", "2401331540702"]
    assert [s["roll_number"] for s in group_g1["students"]] == ["2401331540703"]
    assert [s["roll_number"] for s in waiting["students"]] == ["2401331540703"]
    assert [s["roll_number"] for s in search["students"]] == ["2401331540704"]
    assert as_student.status_code == 403
    assert "mean_embedding" not in str(everyone) and "template" not in str(everyone)


@pytest.mark.anyio
async def test_teachers_are_listed_with_the_classes_they_take():
    admin = await _admin()
    db = mongodb.get_database()
    await create_user(user_id="t_assigned", email="t1@niet.co.in", password_hash=hash_password(PASSWORD), role="TEACHER")
    await create_user(user_id="t_none", email="t2@niet.co.in", password_hash=hash_password(PASSWORD), role="TEACHER")
    await db[org.CLASSES].update_one({"class_id": f"{TERM}:{COHORT}:B:CN"}, {"$set": {"teacher_ids": ["t_assigned"]}})
    async with _client() as client:
        listed = (await client.get("/api/v1/admin/registry/teachers", headers=admin)).json()
        unauthenticated = await client.get("/api/v1/admin/registry/teachers")
    by_id = {t["user_id"]: t for t in listed["teachers"]}
    assert [c["subject_key"] for c in by_id["t_assigned"]["classes"]] == ["CN"]
    assert by_id["t_assigned"]["cohorts"] == [{"cohort_id": COHORT, "year": 3, "branch": "CSE-DS"}]
    assert by_id["t_none"]["classes"] == [] and by_id["t_none"]["approved"] is True
    assert unauthenticated.status_code == 401
