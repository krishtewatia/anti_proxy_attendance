"""Teachers on the timetable: assignment, the teacher's timetable, and sessions
started from timetable slots, with all four sections running at once.

Names and numbers are made up; the vision service is stubbed.
"""

from datetime import date, timedelta

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.database import mongodb
from app.database.mongodb import init_indexes
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from app.services import organisation_service as org
from tests.test_enrolment_requests import COHORT, SHEET

MONDAY = date(2026, 11, 2)
DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]
PASSWORD = "Teaching123!"


@pytest.fixture(autouse=True)
async def fresh_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await init_indexes(db)
    await org.seed_structure(db)
    version = await org.import_timetable(db, COHORT, SHEET, source_name="ds3.csv", actor_user_id="seed")
    await org.activate_version(db, version["version_id"], MONDAY, actor_user_id="seed")
    yield
    mongodb._client = AsyncMongoMockClient()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth(user_id: str, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id=user_id, role=role)}"}


async def _user(user_id: str, role: str, status: str = "APPROVED") -> dict[str, str]:
    await create_user(
        user_id=user_id, email=f"{user_id}@niet.co.in", password_hash=hash_password(PASSWORD), role=role, status=status
    )
    return _auth(user_id, role)


async def _students(section: str, count: int, status: str = "APPROVED") -> list[str]:
    """Students of a section, enrolled in every class of that section."""
    db = mongodb.get_database()
    class_ids = [c["class_id"] async for c in db[org.CLASSES].find({"cohort_id": COHORT, "audience.section": section})]
    identities = []
    for n in range(count):
        user_id = f"u_{section}{n}_{status[0]}"
        identity = f"stu_{section.lower()}{n}{status[0].lower()}"
        await create_user(user_id=user_id, email=f"{user_id}@niet.co.in", password_hash="x", role="STUDENT", status=status)
        await db["student_profiles"].insert_one(
            {"user_id": user_id, "identity": identity, "student_id": identity, "name": f"Student {section}{n}",
             "roll_number": f"24013315{ord(section):03d}{n:02d}", "email": f"{user_id}@niet.co.in"}
        )
        await db["enrolments"].insert_one(
            {"user_id": user_id, "identity": identity, "term_id": "2026-27-ODD", "cohort_id": COHORT,
             "section": section, "choices": {}, "class_ids": class_ids}
        )
        identities.append(identity)
    return identities


async def _common_slots() -> tuple[str, str, dict[str, dict]]:
    """A day and start time at which all four sections have a class, and those slots."""
    db = mongodb.get_database()
    by_time: dict[tuple[str, str], dict[str, dict]] = {}
    async for slot in db[org.SLOTS].find({"audience.kind": "SECTION"}):
        by_time.setdefault((slot["day"], slot["start"]), {})[slot["audience"]["section"]] = slot
    day, start = next(k for k, v in sorted(by_time.items()) if set(v) == {"A", "B", "C", "D"})
    return day, start, by_time[(day, start)]


@pytest.mark.anyio
async def test_assigning_classes_with_co_teachers_history_and_approval():
    admin = await _user("admin_t", "ADMIN")
    await _user("t_one", "TEACHER", status="PENDING")
    await _user("t_two", "TEACHER")
    db = mongodb.get_database()
    class_id = (await db[org.CLASSES].find_one({"audience.section": "B", "subject_key": "CN"}))["class_id"]
    async with _client() as client:
        both = await client.put(f"/api/v1/admin/org/classes/{class_id}/teachers", headers=admin, json={"teacher_ids": ["t_one", "t_two"]})
        only_two = await client.put(f"/api/v1/admin/org/classes/{class_id}/teachers", headers=admin, json={"teacher_ids": ["t_two"]})
        unknown_teacher = await client.put(f"/api/v1/admin/org/classes/{class_id}/teachers", headers=admin, json={"teacher_ids": ["nobody"]})
        unknown_class = await client.put("/api/v1/admin/org/teachers/t_one/classes", headers=admin, json={"class_ids": ["nope"]})
        bulk = await client.put("/api/v1/admin/org/teachers/t_one/classes", headers=admin, json={"class_ids": [class_id]})
        as_teacher = await client.put("/api/v1/admin/org/teachers/t_one/classes", headers=_auth("t_two", "TEACHER"), json={"class_ids": []})
    assert both.status_code == 200 and only_two.status_code == 200 and bulk.status_code == 200
    assert (unknown_teacher.status_code, unknown_class.status_code, as_teacher.status_code) == (404, 404, 403)
    assert set((await db[org.CLASSES].find_one({"class_id": class_id}))["teacher_ids"]) == {"t_one", "t_two"}
    history = [(h["teacher_id"], h["to"] is None) async for h in db["teacher_assignments"].find({"class_id": class_id}).sort("from", 1)]
    assert history == [("t_one", False), ("t_two", True), ("t_one", True)]
    # Being given classes approves a waiting teacher.
    assert (await db["users"].find_one({"user_id": "t_one"}))["status"] == "APPROVED"


@pytest.mark.anyio
async def test_the_timetable_shows_only_the_teachers_classes_and_skips_holidays():
    admin = await _user("admin_t", "ADMIN")
    teacher = await _user("t_cn", "TEACHER")
    db = mongodb.get_database()
    cn_b = [c["class_id"] async for c in db[org.CLASSES].find({"subject_key": "CN", "audience.section": "B"})]
    async with _client() as client:
        await client.put("/api/v1/admin/org/teachers/t_cn/classes", headers=admin, json={"class_ids": cn_b})
        week = (await client.get("/api/v1/teachers/timetable", headers=teacher, params={"date": MONDAY.isoformat()})).json()
        teaching_day = date.fromisoformat(week["week"][0]["date"])
        before = (await client.get("/api/v1/teachers/timetable", headers=teacher, params={"date": teaching_day.isoformat()})).json()
        await client.post("/api/v1/admin/org/calendar", headers=admin, json={"cohort_id": COHORT, "date": teaching_day.isoformat(), "reason": "Holiday"})
        after = (await client.get("/api/v1/teachers/timetable", headers=teacher, params={"date": teaching_day.isoformat()})).json()
        too_early = (await client.get("/api/v1/teachers/timetable", headers=teacher, params={"date": (MONDAY - timedelta(days=7)).isoformat()})).json()
    assert week["week"] and all(s["class_id"] in cn_b for s in week["week"])
    assert before["today"] and all(s["state"] in ("UPCOMING", "NOT_TAKEN") for s in before["today"])
    assert after["today"] == []
    assert too_early["week"] == []  # no timetable in force before its date


@pytest.mark.anyio
async def test_four_sections_run_sessions_at_the_same_time_with_their_own_rosters(vision_frames):
    admin = await _user("admin_t", "ADMIN")
    day_code, start, slots = await _common_slots()
    day = MONDAY + timedelta(days=DAYS.index(day_code))
    rosters = {section: await _students(section, 3) for section in "ABCD"}
    waiting = await _students("B", 1, status="PENDING")
    teachers = {}
    async with _client() as client:
        for section, slot in slots.items():
            teacher_id = f"t_{section}"
            teachers[section] = await _user(teacher_id, "TEACHER")
            await client.put(f"/api/v1/admin/org/classes/{slot['class_id']}/teachers", headers=admin, json={"teacher_ids": [teacher_id]})
        started = {
            section: (await client.post("/api/v1/teachers/sessions/from-slot", headers=teachers[section],
                                        json={"slot_id": slots[section]["slot_id"], "date": day.isoformat()})).json()
            for section in "ABCD"
        }
        again = await client.post("/api/v1/teachers/sessions/from-slot", headers=teachers["A"], json={"slot_id": slots["A"]["slot_id"], "date": day.isoformat()})
        other_class = await client.post("/api/v1/teachers/sessions/from-slot", headers=teachers["A"], json={"slot_id": slots["B"]["slot_id"], "date": day.isoformat()})
        wrong_day = await client.post("/api/v1/teachers/sessions/from-slot", headers=teachers["A"], json={"slot_id": slots["A"]["slot_id"], "date": (day + timedelta(days=1)).isoformat()})
        for section in "ABCD":
            assert (await client.post(f"/api/v1/sessions/{started[section]['session_id']}/start", headers=teachers[section])).status_code == 200
            # Each section opens its own ENTRY round; rounds are per session.
            assert (await client.post(f"/api/v1/sessions/{started[section]['session_id']}/rounds/ENTRY/open", headers=teachers[section])).status_code == 200
        # Each section's frame recognises one of its own students and one from Section A.
        results = {}
        for section in "ABCD":
            session_id = started[section]["session_id"]
            vision_frames.faces = [
                vision_frames.recognized(session_id, rosters[section][0]),
                vision_frames.recognized(session_id, rosters["A"][1]),
            ]
            response = await client.post(f"/api/v1/attendance/{session_id}/process-frame", headers=teachers[section], content=b"frame")
            results[section] = [f["mark_status"] for f in response.json()["faces"]]

    db = mongodb.get_database()
    assert len({s["session_id"] for s in started.values()}) == 4
    for section in "ABCD":
        session_id = started[section]["session_id"]
        assert started[section]["created"] is True and started[section]["roster_size"] == 3
        roster = (await db["session_rosters"].find_one({"session_id": session_id}))["identities"]
        assert sorted(roster) == sorted(rosters[section]) and waiting[0] not in roster
        present = sorted([r["identity"] async for r in db["attendance_records"].find({"session_id": session_id, "status": "PRESENT"})])
        assert present == (sorted(rosters["A"][:2]) if section == "A" else [rosters[section][0]])
    # Section A's own student is marked in A only; elsewhere they are not on the roster.
    assert results["A"] == ["marked", "marked"]
    assert all(results[s] == ["marked", "rejected"] for s in "BCD")
    assert again.json()["created"] is False and again.json()["session_id"] == started["A"]["session_id"]
    assert (other_class.status_code, wrong_day.status_code) == (403, 409)
    assert await db["sessions"].count_documents({}) == 4
