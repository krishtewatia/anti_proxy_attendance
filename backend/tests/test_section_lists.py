"""The official section list: reading it, matching it against students'
setups, and approving only the requests that agree with it.

Names, emails and roll numbers here are made up. The vision service is
stubbed and photos are placeholder image headers.
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
from app.services import section_list_service as lists
from app.services.registration_rules import CONSENT_NOTICE_VERSION
from tests.test_enrolment_requests import COHORT, SHEET, _photo, _Vision

PASSWORD = "SectionList123!"
BASE = "/api/v1/admin/enrolment/section-lists"
HEADER = "Roll No,Name,Email,Section,DE-II,DE-III,DLDA\n"
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
    refreshes = []

    async def fake_refresh() -> bool:
        refreshes.append("reload")
        return True

    monkeypatch.setattr(student_deletion, "_refresh_vision_gallery", fake_refresh)
    monkeypatch.setattr(approval_service, "_refresh_vision_gallery", fake_refresh)
    monkeypatch.setattr(student_biometric_service, "httpx", SimpleNamespace(AsyncClient=_Vision))
    # These tests register more students in a minute than the public sign-up limit allows.
    monkeypatch.setattr(settings, "REGISTRATION_RATE_LIMIT_PER_MINUTE", 100)
    yield refreshes
    mongodb._client = AsyncMongoMockClient()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _admin() -> dict[str, str]:
    await create_user(
        user_id="admin_lists", email="lists@niet.co.in", password_hash=hash_password(PASSWORD), role="ADMIN"
    )
    return {"Authorization": f"Bearer {create_access_token(user_id='admin_lists', role='ADMIN')}"}


async def _student(client, roll, email, name="Asha Example", section="B", choices=None, send=True) -> dict:
    registered = await client.post(
        "/api/v1/students/register",
        json={"name": name, "email": email, "password": PASSWORD, "roll_number": roll},
    )
    assert registered.status_code == 201, registered.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    request_id = None
    if send:
        sent = await client.post(
            "/api/v1/enrolment/requests",
            headers=headers,
            json={
                "cohort_id": COHORT, "section": section, "choices": choices or CHOICES,
                "photos": [_photo("a1"), _photo("a2")], "consent_version": CONSENT_NOTICE_VERSION,
            },
        )
        assert sent.status_code == 201, sent.text
        request_id = sent.json()["request_id"]
    return {"user_id": registered.json()["user_id"], "headers": headers, "request_id": request_id}


async def _upload(client, admin, text, dry_run=False):
    return await client.post(
        f"{BASE}/{COHORT}",
        params={"dry_run": str(dry_run).lower(), "source_name": "ds3_b.csv"},
        content=text.encode(),
        headers={**admin, "Content-Type": "text/csv"},
    )


@pytest.mark.anyio
async def test_the_list_is_read_with_header_aliases_and_every_way_of_writing_a_group():
    admin = await _admin()
    text = (
        "﻿ROLL NUMBER, student name ,Email ID,section,de ii,DE-III,DLDA Group\n"
        "2401331540001,Asha Example,a1@niet.co.in,b,PA G2,DP,DL3\n"
        "2401331540002,Ravi Example,a2@NIET.co.in,B,pa-g1,PROD/G3,dl1\n"
        "2401331540003,Meera Example,a3@niet.co.in,C,AJ,PROD G2,DL4\n"
        ",,,,,,\n"
    )
    async with _client() as client:
        dry = await _upload(client, admin, text, dry_run=True)
        stored_after_dry = (await client.get(f"{BASE}/{COHORT}", headers=admin)).json()
        stored = await _upload(client, admin, text)
        summary = (await client.get(f"{BASE}/{COHORT}", headers=admin)).json()
    assert dry.status_code == 200 and dry.json()["errors"] == [] and dry.json()["row_count"] == 3
    assert dry.json()["stored"] is False and stored_after_dry["exists"] is False
    assert stored.json()["stored"] is True and stored.json()["per_section"] == {"B": 2, "C": 1}
    assert summary["exists"] and summary["row_count"] == 3 and "rows" not in summary
    doc = await mongodb.get_database()[lists.LISTS].find_one({})
    assert doc["rows"][1]["choices"] == {
        "DE-II": {"option": "PA", "group": "G1"},
        "DE-III": {"option": "PROD", "group": "G3"},
        "DLDA": {"option": "DLDA", "group": "DL1"},
    }
    assert doc["rows"][2]["choices"]["DE-II"] == {"option": "AJ", "group": "AJ"}
    assert doc["rows"][1]["email"] == "a2@niet.co.in"


@pytest.mark.anyio
async def test_a_list_with_errors_is_reported_and_not_stored():
    admin = await _admin()
    text = HEADER + (
        "2401331540001,A,a1@niet.co.in,B,PA G2,DP,DL3\n"
        "2401331540001,B,a2@niet.co.in,B,PA G2,DP,DL3\n"
        "24013-31540,C,a3@niet.co.in,B,PA G2,DP,DL3\n"
        "2401331540004,D,d@gmail.com,B,PA G2,DP,DL3\n"
        "2401331540005,E,e@niet.co.in,Z,PA G2,DP,DL3\n"
        "2401331540006,F,f@niet.co.in,B,AJ G1,G4,DL9\n"
    )
    async with _client() as client:
        result = await _upload(client, admin, text)
        missing = await _upload(client, admin, "roll_no,name,email,section\n2401331540001,A,a@niet.co.in,B\n")
        too_big = await _upload(client, admin, HEADER + "x" * (lists.MAX_LIST_BYTES + 1))
    body = result.json()
    assert body["stored"] is False and body["row_count"] == 1
    messages = {e["row"]: e["message"] for e in body["errors"]}
    assert "also on row 2" in messages[3]
    assert "not 8 to 20 digits" in messages[4]
    assert "not a @niet.co.in address" in messages[5]
    assert "section 'Z'" in messages[6]
    assert all(s in messages[7] for s in ("DE-II", "DE-III", "DLDA"))
    assert missing.status_code == 400 and "de2" in missing.json()["detail"]
    assert too_big.status_code == 400
    assert await mongodb.get_database()[lists.LISTS].count_documents({}) == 0


@pytest.mark.anyio
async def test_the_report_puts_everyone_in_one_category():
    admin = await _admin()
    db = mongodb.get_database()
    async with _client() as client:
        match = await _student(client, "2401331540101", "s101@niet.co.in", name="Asha  example")
        await _student(client, "2401331540102", "s102@niet.co.in", choices={**CHOICES, "DE-II": {"option": "PA", "group": "G1"}})
        await _student(client, "2401331540103", "other.address@niet.co.in")
        await _student(client, "2401331540104", "s104@niet.co.in", send=False)
        await _student(client, "2401331540105", "s105@niet.co.in")  # not on the list
        approved = await _student(client, "2401331540106", "s106@niet.co.in")
        await client.post(f"/api/v1/admin/enrolment/requests/{approved['request_id']}/approve", headers=admin)
        text = HEADER + "".join(
            f"{roll},Asha Example,{email},B,PA G2,DP,DL3\n"
            for roll, email in (
                ("2401331540101", "s101@niet.co.in"),
                ("2401331540102", "s102@niet.co.in"),
                ("2401331540103", "s103@niet.co.in"),
                ("2401331540104", "s104@niet.co.in"),
                ("2401331540106", "s106@niet.co.in"),
                ("2401331540199", "s199@niet.co.in"),
            )
        )
        await _upload(client, admin, text)
        report = (await client.get(f"{BASE}/{COHORT}/report", headers=admin)).json()
        section_c = (await client.get(f"{BASE}/{COHORT}/report", headers=admin, params={"section": "C"})).json()
    by_roll = {r["roll_no"]: r for r in report["rows"]}
    assert by_roll["2401331540101"]["category"] == "MATCH"
    assert by_roll["2401331540101"]["warnings"] == []  # spacing and case of a name are not a difference
    assert by_roll["2401331540101"]["request"]["request_id"] == match["request_id"]
    assert by_roll["2401331540102"]["category"] == "DIFFERENT"
    assert by_roll["2401331540102"]["differences"] == ["DE-II: list PA G2, student PA G1"]
    assert by_roll["2401331540103"]["category"] == "EMAIL_DIFFERS"
    assert by_roll["2401331540104"]["category"] == "NO_REQUEST"
    assert by_roll["2401331540105"]["category"] == "NOT_ON_LIST"
    assert by_roll["2401331540106"]["category"] == "APPROVED_AGREES"
    assert by_roll["2401331540199"]["category"] == "NOT_REGISTERED"
    assert sum(report["counts"].values()) == 7 == len(report["rows"])
    assert section_c["rows"] == []
    # Audit entries hold counts only, never names or emails.
    audits = [a async for a in db["audit_events"].find({"action": "SECTION_LIST_UPLOADED"})]
    assert audits and "@" not in str(audits[0]["metadata"]) and "Asha" not in str(audits[0]["metadata"])


@pytest.mark.anyio
async def test_only_matching_requests_are_approved_and_all_or_nothing(fresh_db):
    admin = await _admin()
    db = mongodb.get_database()
    async with _client() as client:
        one = await _student(client, "2401331540201", "s201@niet.co.in")
        two = await _student(client, "2401331540202", "s202@niet.co.in")
        differs = await _student(client, "2401331540203", "s203@niet.co.in", section="C")
        text = HEADER + "".join(
            f"{roll},Asha Example,s{roll[-3:]}@niet.co.in,B,PA G2,DP,DL3\n"
            for roll in ("2401331540201", "2401331540202", "2401331540203")
        )
        await _upload(client, admin, text)
        refused = await client.post(
            f"{BASE}/{COHORT}/approve-matching", headers=admin,
            json={"request_ids": [one["request_id"], differs["request_id"]]},
        )
        # A request that changed after the report was loaded no longer matches.
        await client.delete("/api/v1/enrolment/requests/current", headers=two["headers"])
        stale = await client.post(
            f"{BASE}/{COHORT}/approve-matching", headers=admin, json={"request_ids": [two["request_id"]]}
        )
        approved = await client.post(
            f"{BASE}/{COHORT}/approve-matching", headers=admin, json={"request_ids": [one["request_id"]]}
        )
        as_student = await client.post(
            f"{BASE}/{COHORT}/approve-matching", headers=one["headers"], json={"request_ids": [one["request_id"]]}
        )
    assert refused.status_code == 409 and refused.json()["detail"]["not_matching"] == [differs["request_id"]]
    assert stale.status_code == 409
    assert approved.status_code == 200 and approved.json()["done"] == [one["request_id"]]
    assert as_student.status_code == 403
    assert (await db["users"].find_one({"user_id": one["user_id"]}))["status"] == "APPROVED"
    assert (await db["users"].find_one({"user_id": differs["user_id"]}))["status"] == "PENDING"
    audit = await db["audit_events"].find_one({"action": "ENROLMENT_APPROVED"})
    assert audit["metadata"]["via"] == "section_list"
    assert await db["audit_events"].count_documents({"action": "ENROLMENT_APPROVED"}) == 1
    assert fresh_db == ["reload"]


@pytest.mark.anyio
async def test_the_list_is_admin_only_and_can_be_deleted():
    admin = await _admin()
    async with _client() as client:
        student = await _student(client, "2401331540301", "s301@niet.co.in", send=False)
        await _upload(client, admin, HEADER + "2401331540301,A,s301@niet.co.in,B,PA G2,DP,DL3\n")
        template = await client.get(f"{BASE}/template.csv", headers=admin)
        blocked = [
            await client.get(f"{BASE}/{COHORT}/report", headers=student["headers"]),
            await client.get(f"{BASE}/{COHORT}", headers=student["headers"]),
            await client.post(f"{BASE}/{COHORT}", headers=student["headers"], content=b"x"),
            await client.get(f"{BASE}/{COHORT}/report"),
        ]
        deleted = await client.delete(f"{BASE}/{COHORT}", headers=admin)
        again = await client.delete(f"{BASE}/{COHORT}", headers=admin)
        no_list = await client.get(f"{BASE}/{COHORT}/report", headers=admin)
    assert template.text.startswith("roll_no,name,email,section,de2,de3,dlda")
    assert [r.status_code for r in blocked] == [403, 403, 403, 401]
    assert (deleted.status_code, again.status_code, no_list.status_code) == (200, 404, 404)
