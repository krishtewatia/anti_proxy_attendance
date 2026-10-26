"""Reports for timetable classes: the student's subject-wise view (in
lectures, with "not entered" apart), the lecture list, the class list and the
register. Names and numbers are made up.
"""

from datetime import timedelta

from httpx import ASGITransport, AsyncClient
import pytest

from app.database import mongodb
from app.main import app
from app.services import organisation_service as org
from app.services import reports_service as reports
from tests.test_rounds import fresh_db  # noqa: F401  (same seeded, activated timetable)
from tests.test_teaching import DAYS, MONDAY, _students, _user

TODAY = MONDAY + timedelta(days=6)  # the Sunday after the first week


@pytest.fixture(autouse=True)
def pinned_today(monkeypatch):
    monkeypatch.setattr(reports, "today", lambda: TODAY)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _setup():
    """Section B: two students, a CN teacher; the first CN slot of the week is taken."""
    admin = await _user("admin_r8", "ADMIN")
    teacher = await _user("t_cn", "TEACHER")
    db = mongodb.get_database()
    students = await _students("B", 2)
    cn = await db[org.CLASSES].find_one({"audience.section": "B", "subject_key": "CN"})
    slots = sorted([s async for s in db[org.SLOTS].find({"class_id": cn["class_id"]})], key=lambda s: (DAYS.index(s["day"]), s["start_minute"]))
    return admin, teacher, db, students, cn, slots


async def _take(client, teacher, slot, marks: dict[str, tuple[str, str]]):
    day = MONDAY + timedelta(days=DAYS.index(slot["day"]))
    started = (await client.post("/api/v1/teachers/sessions/from-slot", headers=teacher, json={"slot_id": slot["slot_id"], "date": day.isoformat()})).json()
    sid = started["session_id"]
    await client.post(f"/api/v1/sessions/{sid}/start", headers=teacher)
    for rnd in ("ENTRY", "EXIT"):
        await client.post(f"/api/v1/sessions/{sid}/rounds/{rnd}/open", headers=teacher)
        for identity, (entry, exit_) in marks.items():
            status = entry if rnd == "ENTRY" else exit_
            await client.post(f"/api/v1/sessions/{sid}/rounds/{rnd}/marks", headers=teacher, json={"identity": identity, "status": status})
    await client.post(f"/api/v1/sessions/{sid}/finalize", headers=teacher)
    return sid, day


@pytest.mark.anyio
async def test_the_student_view_counts_lectures_and_keeps_not_entered_apart():
    admin, teacher, db, students, cn, slots = await _setup()
    first = slots[0]
    periods = int(first["periods"])
    async with _client() as client:
        await client.put(f"/api/v1/admin/org/teachers/t_cn/classes", headers=admin, json={"class_ids": [cn["class_id"]]})
        await _take(client, teacher, first, {students[0]: ("PRESENT", "PRESENT"), students[1]: ("PRESENT", "ABSENT")})
        # A holiday on another CN day: its slots are not "not entered".
        holiday_slot = next((s for s in slots if s["day"] != first["day"]), None)
        if holiday_slot:
            holiday = MONDAY + timedelta(days=DAYS.index(holiday_slot["day"]))
            await client.post("/api/v1/admin/org/calendar", headers=admin, json={"cohort_id": cn["cohort_id"], "date": holiday.isoformat(), "reason": "Holiday"})
        uid0 = (await db["student_profiles"].find_one({"identity": students[0]}))["user_id"]
        uid1 = (await db["student_profiles"].find_one({"identity": students[1]}))["user_id"]
        from app.security.jwt import create_access_token

        view0 = (await client.get("/api/v1/students/attendance/subjects", headers={"Authorization": f"Bearer {create_access_token(user_id=uid0, role='STUDENT')}"})).json()
        view1 = (await client.get("/api/v1/students/attendance/subjects", headers={"Authorization": f"Bearer {create_access_token(user_id=uid1, role='STUDENT')}"})).json()
        lectures1 = (await client.get("/api/v1/students/attendance/subjects/CN", headers={"Authorization": f"Bearer {create_access_token(user_id=uid1, role='STUDENT')}"})).json()
        other_subject = await client.get("/api/v1/students/attendance/subjects/PRED", headers={"Authorization": f"Bearer {create_access_token(user_id=uid1, role='STUDENT')}"})

    expected_not_entered = sum(
        int(s["periods"]) for s in slots[1:] if not holiday_slot or s["day"] != holiday_slot["day"]
    )
    cn0 = next(r for r in view0["subjects"] if r["subject_key"] == "CN")
    cn1 = next(r for r in view1["subjects"] if r["subject_key"] == "CN")
    assert (cn0["held"], cn0["present"], cn0["not_entered"]) == (periods, periods, expected_not_entered)
    assert cn0["percentage"] == 100.0 and cn0["shortage"] is False
    # Student 1 was absent at EXIT: single period -> A; double -> P, A.
    assert cn1["present"] == (0 if periods == 1 else 1) and cn1["held"] == periods
    assert cn1["shortage"] is True and view1["overall"]["shortage"] is True
    # Subjects with no session yet: nothing held, no percentage.
    dcc = next(r for r in view0["subjects"] if r["subject_key"] == "DCC")
    assert dcc["held"] == 0 and dcc["percentage"] is None and dcc["not_entered"] >= 0
    assert {s["name"] for s in view0["not_counted"]} >= {"MOOC"} or view0["not_counted"]
    assert [lec["lecture"] for lec in lectures1["lectures"]] == list(range(periods, 0, -1))
    assert lectures1["lectures"][-1]["entry"] == "PRESENT" and lectures1["lectures"][-1]["exit"] == "ABSENT"
    assert other_subject.status_code == 404


@pytest.mark.anyio
async def test_register_and_class_list_csv_and_who_may_download():
    admin, teacher, db, students, cn, slots = await _setup()
    other_teacher = await _user("t_other", "TEACHER")
    async with _client() as client:
        await client.put("/api/v1/admin/org/teachers/t_cn/classes", headers=admin, json={"class_ids": [cn["class_id"]]})
        _, day1 = await _take(client, teacher, slots[0], {students[0]: ("PRESENT", "PRESENT"), students[1]: ("ABSENT", "ABSENT")})
        _, day2 = await _take(client, teacher, slots[1], {students[0]: ("ABSENT", "ABSENT"), students[1]: ("PRESENT", "PRESENT")})
        from urllib.parse import quote

        base = f"/api/v1/teachers/classes/{quote(cn['class_id'], safe='')}"
        register = await client.get(f"{base}/register.csv", headers=teacher)
        first_day_only = await client.get(f"{base}/register.csv", headers=teacher, params={"from": day1.isoformat(), "to": day1.isoformat()})
        class_list = await client.get(f"{base}/students.csv", headers=teacher)
        sessions = (await client.get(f"{base}/sessions", headers=teacher)).json()
        mine = (await client.get("/api/v1/teachers/classes", headers=teacher)).json()
        refused = await client.get(f"{base}/register.csv", headers=other_teacher)
        as_admin = await client.get(f"{base}/students.csv", headers=admin)
        uid0 = (await db["student_profiles"].find_one({"identity": students[0]}))["user_id"]
        from app.security.jwt import create_access_token

        as_student = await client.get(f"{base}/students.csv", headers={"Authorization": f"Bearer {create_access_token(user_id=uid0, role='STUDENT')}"})

    lines = register.text.strip().splitlines()
    header = lines[0].split(",")
    p1, p2 = int(slots[0]["periods"]), int(slots[1]["periods"])
    assert header[:2] == ["Roll No", "Name"] and header[-3:] == ["Present", "Held", "%"]
    assert len(header) == 2 + p1 + p2 + 3 and header[2].endswith("L1")
    row0 = lines[1].split(",")
    assert row0[2:2 + p1 + p2] == ["P"] * p1 + ["A"] * p2
    assert row0[-3:-1] == [str(p1), str(p1 + p2)]
    assert len(first_day_only.text.strip().splitlines()[0].split(",")) == 2 + p1 + 3
    assert class_list.text.splitlines()[0] == "Roll No,Name,Email,Section,DE-II,DE-III,DLDA"
    assert len(class_list.text.strip().splitlines()) == 3 and ",B," in class_list.text.splitlines()[1]
    assert len(sessions) == 2 and all(s["rounds_held"] == ["ENTRY", "EXIT"] for s in sessions)
    assert [c["class_id"] for c in mine] == [cn["class_id"]]
    assert refused.status_code == 403 and as_admin.status_code == 200 and as_student.status_code == 403


@pytest.mark.anyio
async def test_a_group_class_id_with_slashes_works_in_the_url():
    admin, _, db, _, _, _ = await _setup()
    group_class = await db[org.CLASSES].find_one({"audience.kind": "GROUP"})
    assert "/" in group_class["class_id"]
    await _user("t_group", "TEACHER")
    from urllib.parse import quote

    async with _client() as client:
        assigned = await client.put(f"/api/v1/admin/org/classes/{quote(group_class['class_id'], safe='')}/teachers", headers=admin, json={"teacher_ids": ["t_group"]})
        listed = await client.get(f"/api/v1/teachers/classes/{quote(group_class['class_id'], safe='')}/students.csv", headers=admin)
    assert assigned.status_code == 200 and listed.status_code == 200
