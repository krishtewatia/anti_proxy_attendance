"""A session in which attendance was never taken counts nowhere.

It is left out of every student's totals and percentage, so it cannot put a
student into shortage; it adds nothing to the administrator's report; and its
CSV export and register say "not taken" instead of listing absences.
"""

from datetime import datetime, timezone

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.database import mongodb
from app.database.mongodb import init_indexes
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password

CLASS = "DS-B"


@pytest.fixture(autouse=True)
async def fresh_db():
    mongodb._client = AsyncMongoMockClient()
    await init_indexes(mongodb.get_database())
    yield
    mongodb._client = AsyncMongoMockClient()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _token(user_id: str, role: str) -> dict[str, str]:
    await create_user(
        user_id=user_id,
        email=f"{user_id}@untaken.test",
        password_hash=hash_password("UntakenPass123!"),
        role=role,
    )
    return {"Authorization": f"Bearer {create_access_token(user_id=user_id, role=role)}"}


async def _student(identity: str) -> dict[str, str]:
    headers = await _token(f"user_{identity}", "STUDENT")
    await mongodb.get_database()["student_profiles"].insert_one(
        {
            "user_id": f"user_{identity}",
            "identity": identity,
            "student_id": identity,
            "name": f"Student {identity}",
            "email": f"user_{identity}@untaken.test",
            "roll_number": f"R-{identity}",
            "branch": "Data Science",
            "section": "B",
            "class_code": CLASS,
        }
    )
    return headers


async def _session(
    session_id: str,
    marks: dict[str, str],
    *,
    started: bool,
    subject: str = "Maths",
    status: str = "FINALIZED",
    teacher: str = "teacher_untaken",
) -> None:
    """A stored session with a roster and one record per student.

    ``started=False`` is a session that was created and closed without
    attendance being taken: every record is the ABSENT placeholder written
    when the roster is built.
    """
    db = mongodb.get_database()
    doc = {
        "session_id": session_id,
        "course_name": subject,
        "subject": subject,
        "classroom_id": "ROOM_1",
        "start_time": datetime(2026, 10, 1, 9, tzinfo=timezone.utc),
        "end_time": datetime(2026, 10, 1, 10, tzinfo=timezone.utc),
        "created_at": datetime(2026, 10, 1, 8, tzinfo=timezone.utc),
        "class_code": CLASS,
        "required_presence_percentage": 75.0,
        "status": status,
        "created_by": teacher,
    }
    if started:
        doc["started_at"] = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
    await db["sessions"].insert_one(doc)
    await db["session_rosters"].insert_one({"session_id": session_id, "identities": list(marks)})
    await db["attendance_records"].insert_many(
        [
            {
                "attendance_id": f"att_{session_id}_{identity}",
                "session_id": session_id,
                "identity": identity,
                "status": mark,
            }
            for identity, mark in marks.items()
        ]
    )


async def _dashboard(headers: dict[str, str]) -> dict:
    async with _client() as client:
        response = await client.get("/api/v1/students/dashboard", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.anyio
async def test_untaken_sessions_cannot_put_a_student_into_shortage():
    """Present at 3 of the 4 sessions taken (75 %); 4 more were never taken.

    Counting the untaken ones as absences would give 3 of 8 = 37.5 %, a
    shortage the student did nothing to earn.
    """
    student = await _student("S1")
    for n in range(3):
        await _session(f"taken_{n}", {"S1": "PRESENT", "S2": "PRESENT"}, started=True)
    await _session("taken_missed", {"S1": "ABSENT", "S2": "PRESENT"}, started=True)
    for n in range(4):
        await _session(f"untaken_{n}", {"S1": "ABSENT", "S2": "ABSENT"}, started=False)

    body = await _dashboard(student)

    assert (body["overall_present"], body["overall_total"]) == (3, 4)
    assert body["overall_percentage"] == 75.0
    assert body["sessions_not_taken"] == 4
    assert body["subjects"] == [{"subject": "Maths", "present": 3, "total": 4, "percentage": 75.0}]

    statuses = {item["session_id"]: item["status"] for item in body["history"]}
    assert len(statuses) == 8
    assert all(statuses[f"untaken_{n}"] == "NOT_TAKEN" for n in range(4))
    assert statuses["taken_missed"] == "ABSENT"
    assert "ABSENT" not in {statuses[f"untaken_{n}"] for n in range(4)}


@pytest.mark.anyio
async def test_a_session_taken_with_the_student_absent_still_counts():
    """Started, and somebody else was marked: this student's absence is real."""
    student = await _student("S1")
    await _session("taken", {"S1": "ABSENT", "S2": "PRESENT"}, started=True)
    # Started but nobody turned up: still taken, still an absence.
    await _session("empty_room", {"S1": "ABSENT", "S2": "ABSENT"}, started=True)

    body = await _dashboard(student)
    assert (body["overall_present"], body["overall_total"], body["overall_percentage"]) == (0, 2, 0.0)
    assert body["sessions_not_taken"] == 0


@pytest.mark.anyio
async def test_a_student_with_only_untaken_sessions_has_no_percentage_and_no_subject_rows():
    student = await _student("S1")
    await _session("untaken_a", {"S1": "ABSENT"}, started=False, subject="Maths")
    await _session("untaken_b", {"S1": "ABSENT"}, started=False, subject="Physics")
    await _session("scheduled", {"S1": "ABSENT"}, started=False, subject="Physics", status="SCHEDULED")

    body = await _dashboard(student)
    assert (body["overall_present"], body["overall_total"]) == (0, 0)
    # null, not 0 %: there is nothing to be short of.
    assert body["overall_percentage"] is None
    assert body["subjects"] == []
    assert {item["status"] for item in body["history"]} == {"NOT_TAKEN"}
    assert body["sessions_not_taken"] == 3


@pytest.mark.anyio
async def test_a_correction_in_an_untaken_session_makes_it_count():
    """Attendance entered by hand is attendance taken."""
    student = await _student("S1")
    await _session("by_hand", {"S1": "ABSENT", "S2": "ABSENT"}, started=False)
    await mongodb.get_database()["attendance_records"].update_one(
        {"session_id": "by_hand", "identity": "S2"},
        {"$set": {"status": "PRESENT", "manually_corrected": True}},
    )

    body = await _dashboard(student)
    assert (body["overall_present"], body["overall_total"], body["overall_percentage"]) == (0, 1, 0.0)
    assert body["history"][0]["status"] == "ABSENT"


@pytest.mark.anyio
async def test_the_admin_report_leaves_untaken_sessions_out():
    admin = await _token("admin_untaken", "ADMIN")
    # S1: 3 of 4 = 75 %, not below the threshold. S2: 4 of 4.
    for n in range(3):
        await _session(f"taken_{n}", {"S1": "PRESENT", "S2": "PRESENT"}, started=True)
    await _session("taken_missed", {"S1": "ABSENT", "S2": "PRESENT"}, started=True)
    for n in range(4):
        await _session(f"untaken_{n}", {"S1": "ABSENT", "S2": "ABSENT"}, started=False)

    async with _client() as client:
        response = await client.get("/api/v1/admin/reports/summary", headers=admin)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "finalized_sessions": 4,
        "sessions_not_taken": 4,
        "classes_with_sessions": 1,
        "attendance_records": 8,
        # 7 of 8; with the untaken sessions it would have been 7 of 16.
        "average_turnout_percentage": 87.5,
        "students_counted": 2,
        # With the untaken sessions both students would be below 75 %.
        "students_below_threshold": 0,
        "threshold_percentage": 75.0,
    }


@pytest.mark.anyio
async def test_the_admin_report_has_nothing_to_count_when_no_session_was_taken():
    admin = await _token("admin_untaken", "ADMIN")
    await _session("untaken", {"S1": "ABSENT", "S2": "ABSENT"}, started=False)

    async with _client() as client:
        body = (await client.get("/api/v1/admin/reports/summary", headers=admin)).json()
    assert (body["finalized_sessions"], body["sessions_not_taken"]) == (0, 1)
    assert body["average_turnout_percentage"] is None
    assert (body["attendance_records"], body["students_counted"], body["students_below_threshold"]) == (0, 0, 0)
    assert body["classes_with_sessions"] == 0


@pytest.mark.anyio
async def test_the_csv_export_says_not_taken_instead_of_absent():
    teacher = await _token("teacher_untaken", "TEACHER")
    await _student("S1")
    await _session("untaken", {"S1": "ABSENT", "S2": "ABSENT"}, started=False)
    await _session("taken", {"S1": "ABSENT", "S2": "PRESENT"}, started=True)

    async with _client() as client:
        untaken = await client.get("/api/v1/attendance/untaken/export", headers=teacher)
        taken = await client.get("/api/v1/attendance/taken/export", headers=teacher)
    assert untaken.status_code == 200 and taken.status_code == 200

    untaken_rows = untaken.text.strip().splitlines()
    assert untaken_rows[0] == "Student ID,Student Name,Status"
    assert untaken_rows[1:] == ["S1,Student S1,Not taken", "S2,S2,Not taken"]
    assert "ABSENT" not in untaken.text

    assert taken.text.strip().splitlines()[1:] == ["S1,Student S1,ABSENT", "S2,S2,PRESENT"]


@pytest.mark.anyio
async def test_the_session_register_reports_whether_attendance_was_taken():
    teacher = await _token("teacher_untaken", "TEACHER")
    await _session("untaken", {"S1": "ABSENT"}, started=False)
    await _session("taken", {"S1": "ABSENT"}, started=True)

    async with _client() as client:
        untaken = (await client.get("/api/v1/attendance/untaken", headers=teacher)).json()
        taken = (await client.get("/api/v1/attendance/taken", headers=teacher)).json()
    assert untaken["was_taken"] is False
    assert taken["was_taken"] is True
