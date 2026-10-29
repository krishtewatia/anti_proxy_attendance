"""Administrator edits on the pilot model: term dates, subject codes, timetable
flags, holidays and cancelled classes, and the pilot settings."""

from pathlib import Path

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.database import mongodb
from app.database.mongodb import init_indexes
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from app.seed import pilot_catalog
from app.services import organisation_service as org

COHORT = pilot_catalog.COHORT["cohort_id"]
TERM = pilot_catalog.TERM["term_id"]
SHEET = (Path(org.__file__).resolve().parent.parent / "seed" / pilot_catalog.TIMETABLE_FILE).read_text(
    encoding="utf-8-sig"
)
BASE = "/api/v1/admin/org"


@pytest.fixture(autouse=True)
async def fresh_db():
    mongodb._client = AsyncMongoMockClient()
    await init_indexes(mongodb.get_database())
    yield
    mongodb._client = AsyncMongoMockClient()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _admin() -> dict[str, str]:
    await create_user(
        user_id="admin_edits", email="admin_edits@org.test",
        password_hash=hash_password("EditsPass123!"), role="ADMIN",
    )
    return {"Authorization": f"Bearer {create_access_token(user_id='admin_edits', role='ADMIN')}"}


async def _with_timetable() -> str:
    db = mongodb.get_database()
    await org.seed_structure(db)
    version = await org.import_timetable(db, COHORT, SHEET, source_name="ds3.csv", actor_user_id="a")
    return version["version_id"]


async def _audit_actions() -> list[str]:
    return [doc["action"] async for doc in mongodb.get_database()["audit_events"].find({})]


@pytest.mark.anyio
async def test_term_dates_can_be_set_and_must_be_in_order():
    admin = await _admin()
    await org.seed_structure(mongodb.get_database())
    async with _client() as client:
        ok = await client.patch(f"{BASE}/terms/{TERM}", json={"start_date": "2026-07-20", "end_date": "2026-12-15"}, headers=admin)
        backwards = await client.patch(f"{BASE}/terms/{TERM}", json={"start_date": "2026-12-15", "end_date": "2026-07-20"}, headers=admin)
        missing = await client.patch(f"{BASE}/terms/1999-ODD", json={"start_date": "2026-07-20"}, headers=admin)
    assert ok.status_code == 200 and ok.json()["start_date"] == "2026-07-20"
    assert backwards.status_code == 400 and missing.status_code == 404
    assert "TERM_UPDATED" in await _audit_actions()


@pytest.mark.anyio
async def test_confirming_a_subject_code_clears_its_flag_on_every_slot():
    admin = await _admin()
    version_id = await _with_timetable()
    async with _client() as client:
        before = (await client.get(f"{BASE}/timetable/versions/{version_id}/slots", params={"flagged_only": "true"}, headers=admin)).json()
        assert sum(any(f["kind"] == "INCOMPLETE_CODE" for f in s["flags"]) for s in before) == 7

        fixed = await client.patch(
            f"{BASE}/subjects/AJAVA",
            json={"code": "BCSAI0512", "code_status": "CONFIRMED", "code_note": ""},
            headers=admin,
        )
        assert fixed.status_code == 200 and fixed.json()["code"] == "BCSAI0512"

        after = (await client.get(f"{BASE}/timetable/versions/{version_id}/slots", params={"flagged_only": "true"}, headers=admin)).json()
    # Advance Java's 3 theory slots lose the flag; Design Pattern and the lab keep theirs.
    assert sum(any(f["kind"] == "INCOMPLETE_CODE" for f in s["flags"]) for s in after) == 4
    assert not any(s["subject_key"] == "AJAVA" and any(f["kind"] == "INCOMPLETE_CODE" for f in s["flags"]) for s in after)
    assert "SUBJECT_UPDATED" in await _audit_actions()


@pytest.mark.anyio
async def test_subject_edits_are_checked():
    admin = await _admin()
    await org.seed_structure(mongodb.get_database())
    async with _client() as client:
        taken = await client.patch(f"{BASE}/subjects/DP", json={"code": "BCSE0502A"}, headers=admin)
        empty = await client.patch(f"{BASE}/subjects/DP", json={"name": " "}, headers=admin)
        bad_status = await client.patch(f"{BASE}/subjects/DP", json={"code_status": "MAYBE"}, headers=admin)
        missing = await client.patch(f"{BASE}/subjects/NOPE", json={"name": "x"}, headers=admin)
    assert (taken.status_code, empty.status_code, bad_status.status_code, missing.status_code) == (409, 400, 400, 404)


@pytest.mark.anyio
async def test_a_confirm_flag_can_be_resolved_with_a_note_and_the_slot_is_unchanged():
    admin = await _admin()
    version_id = await _with_timetable()
    db = mongodb.get_database()
    slot = await db[org.SLOTS].find_one({"version_id": version_id, "row": 88})
    async with _client() as client:
        no_note = await client.post(f"{BASE}/timetable/slots/{slot['slot_id']}/flags/CONFIRM/resolve", json={"note": ""}, headers=admin)
        wrong_kind = await client.post(f"{BASE}/timetable/slots/{slot['slot_id']}/flags/NO_ROOM/resolve", json={"note": "x"}, headers=admin)
        done = await client.post(
            f"{BASE}/timetable/slots/{slot['slot_id']}/flags/CONFIRM/resolve",
            json={"note": "HOD confirmed: DevOps"},
            headers=admin,
        )
    assert no_note.status_code == 422 and wrong_kind.status_code == 404
    assert done.status_code == 200
    flag = done.json()["flags"][0]
    assert flag["resolved"] is True and flag["resolved_note"] == "HOD confirmed: DevOps"
    after = await db[org.SLOTS].find_one({"slot_id": slot["slot_id"]})
    assert (after["subject_key"], after["day"], after["start"], after["periods"]) == ("DCC", "WED", "13:30", 1)
    assert "TIMETABLE_FLAG_RESOLVED" in await _audit_actions()


@pytest.mark.anyio
async def test_holidays_and_cancelled_classes():
    admin = await _admin()
    await _with_timetable()
    class_id = f"{TERM}:{COHORT}:B:CN"
    async with _client() as client:
        holiday = await client.post(f"{BASE}/calendar", json={"cohort_id": COHORT, "date": "2026-11-09", "reason": "Diwali"}, headers=admin)
        cancelled = await client.post(
            f"{BASE}/calendar", json={"cohort_id": COHORT, "date": "2026-11-11", "reason": "Teacher on duty", "class_id": class_id}, headers=admin
        )
        twice = await client.post(f"{BASE}/calendar", json={"cohort_id": COHORT, "date": "2026-11-09", "reason": "again"}, headers=admin)
        bad_class = await client.post(
            f"{BASE}/calendar", json={"cohort_id": COHORT, "date": "2026-11-12", "reason": "x", "class_id": "nope"}, headers=admin
        )
        listed = (await client.get(f"{BASE}/calendar", params={"cohort_id": COHORT}, headers=admin)).json()
        removed = await client.delete(f"{BASE}/calendar/{holiday.json()['exception_id']}", headers=admin)
        left = (await client.get(f"{BASE}/calendar", headers=admin)).json()
    assert (holiday.status_code, cancelled.status_code, twice.status_code, bad_class.status_code) == (201, 201, 409, 404)
    assert [e["date"] for e in listed] == ["2026-11-09", "2026-11-11"]
    assert removed.status_code == 200 and [e["class_id"] for e in left] == [class_id]


@pytest.mark.anyio
async def test_settings_have_defaults_and_are_checked():
    admin = await _admin()
    async with _client() as client:
        defaults = (await client.get(f"{BASE}/settings", headers=admin)).json()
        changed = await client.put(f"{BASE}/settings", json={"edit_window_hours": 72, "college_email_domain": "@NIET.co.in"}, headers=admin)
        bad = [
            await client.put(f"{BASE}/settings", json=body, headers=admin)
            for body in ({"edit_window_hours": 0}, {"shortage_threshold_percent": 101}, {"college_email_domain": "not a domain"})
        ]
    assert defaults == {"college_email_domain": "niet.co.in", "edit_window_hours": 48, "shortage_threshold_percent": 75}
    assert changed.status_code == 200
    assert changed.json() == {"college_email_domain": "niet.co.in", "edit_window_hours": 72, "shortage_threshold_percent": 75}
    assert [r.status_code for r in bad] == [400, 400, 400]
    assert "SETTINGS_UPDATED" in await _audit_actions()


@pytest.mark.anyio
async def test_only_administrators_reach_the_edit_routes():
    await create_user(user_id="t1", email="t1@org.test", password_hash=hash_password("TeachPass123!"), role="TEACHER")
    teacher = {"Authorization": f"Bearer {create_access_token(user_id='t1', role='TEACHER')}"}
    async with _client() as client:
        for method, path in (
            ("PATCH", f"{BASE}/terms/{TERM}"),
            ("PATCH", f"{BASE}/subjects/CN"),
            ("POST", f"{BASE}/timetable/slots/x/flags/CONFIRM/resolve"),
            ("GET", f"{BASE}/calendar"),
            ("POST", f"{BASE}/calendar"),
            ("DELETE", f"{BASE}/calendar/x"),
            ("GET", f"{BASE}/settings"),
            ("PUT", f"{BASE}/settings"),
        ):
            for headers in ({}, teacher):
                response = await client.request(method, path, headers=headers, json={})
                assert response.status_code in (401, 403), (method, path, response.status_code)
