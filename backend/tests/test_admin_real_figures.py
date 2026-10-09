"""The admin screens show counted values, never placeholders.

The session list reports the real teacher, roster size and present count; the
reports summary is counted from finalized sessions and says "nothing to
count" with null rather than a made-up percentage; a teacher without a
profile gets an empty profile, not an invented one.
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
        email=f"{user_id}@figures.test",
        password_hash=hash_password("FiguresPass123!"),
        role=role,
    )
    return {"Authorization": f"Bearer {create_access_token(user_id=user_id, role=role)}"}


async def _session(session_id: str, status: str, teacher: str, class_code: str, marks: dict[str, str]) -> None:
    """A stored session with a roster and one attendance record per student."""
    db = mongodb.get_database()
    await db["sessions"].insert_one(
        {
            "session_id": session_id,
            "course_name": f"Course {session_id}",
            "classroom_id": "ROOM_1",
            "start_time": "2026-10-01T09:00:00Z",
            "end_time": "2026-10-01T10:00:00Z",
            "class_code": class_code,
            "required_presence_percentage": 75.0,
            "status": status,
            "created_by": teacher,
        }
    )
    await db["session_rosters"].insert_one({"session_id": session_id, "identities": list(marks)})
    if marks:
        await db["attendance_records"].insert_many(
            [
                {"attendance_id": f"att_{session_id}_{identity}", "session_id": session_id,
                 "identity": identity, "status": status_}
                for identity, status_ in marks.items()
            ]
        )


@pytest.mark.anyio
async def test_the_admin_session_list_reports_counted_figures():
    admin = await _token("admin_fig", "ADMIN")
    db = mongodb.get_database()
    await db["teacher_profiles"].insert_one({"user_id": "teacher_fig", "teacher_id": "T1", "name": "Figures Teacher"})
    await _session("s_full", "FINALIZED", "teacher_fig", "DS-B", {"A": "PRESENT", "B": "PRESENT", "C": "ABSENT"})
    await _session("s_empty", "SCHEDULED", "teacher_gone", "DS-C", {})

    async with _client() as client:
        response = await client.get("/api/v1/admin/sessions", headers=admin)
    assert response.status_code == 200, response.text
    rows = {row["session_id"]: row for row in response.json()}

    assert (rows["s_full"]["teacher_name"], rows["s_full"]["total_students"], rows["s_full"]["present_count"]) == (
        "Figures Teacher",
        3,
        2,
    )
    # No roster, no records, a teacher who no longer exists: zeros and null, not a guess.
    assert (rows["s_empty"]["teacher_name"], rows["s_empty"]["total_students"], rows["s_empty"]["present_count"]) == (
        None,
        0,
        0,
    )


@pytest.mark.anyio
async def test_the_reports_summary_is_counted_from_finalized_sessions():
    admin = await _token("admin_fig", "ADMIN")
    # A: 2 of 2 present. B: 1 of 2 (50%). C: 0 of 1. Turnout 3 of 5 = 60%.
    await _session("s1", "FINALIZED", "t", "DS-B", {"A": "PRESENT", "B": "PRESENT", "C": "ABSENT"})
    await _session("s2", "FINALIZED", "t", "DS-C", {"A": "PRESENT", "B": "ABSENT"})
    # Not finalized: must not be counted.
    await _session("s3", "ACTIVE", "t", "CS-A", {"A": "ABSENT", "D": "ABSENT"})
    await _session("s4", "SCHEDULED", "t", "CS-A", {"A": "ABSENT"})

    async with _client() as client:
        response = await client.get("/api/v1/admin/reports/summary", headers=admin)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "finalized_sessions": 2,
        "classes_with_sessions": 2,
        "attendance_records": 5,
        "average_turnout_percentage": 60.0,
        "students_counted": 3,
        "students_below_threshold": 2,
        "threshold_percentage": 75.0,
    }


@pytest.mark.anyio
async def test_the_reports_summary_says_so_when_there_is_nothing_to_count():
    admin = await _token("admin_fig", "ADMIN")
    await _session("s3", "ACTIVE", "t", "CS-A", {"A": "PRESENT"})
    async with _client() as client:
        response = await client.get("/api/v1/admin/reports/summary", headers=admin)
    body = response.json()
    assert body["finalized_sessions"] == 0 and body["attendance_records"] == 0
    assert body["average_turnout_percentage"] is None
    assert body["students_below_threshold"] == 0 and body["students_counted"] == 0


@pytest.mark.anyio
async def test_the_reports_summary_needs_an_admin():
    teacher = await _token("teacher_fig", "TEACHER")
    student = await _token("student_fig", "STUDENT")
    async with _client() as client:
        no_token = await client.get("/api/v1/admin/reports/summary")
        as_teacher = await client.get("/api/v1/admin/reports/summary", headers=teacher)
        as_student = await client.get("/api/v1/admin/reports/summary", headers=student)
    assert (no_token.status_code, as_teacher.status_code, as_student.status_code) == (401, 403, 403)


@pytest.mark.anyio
async def test_a_teacher_without_a_profile_gets_an_empty_profile_not_an_invented_one():
    teacher = await _token("teacher_fig", "TEACHER")
    async with _client() as client:
        profile = await client.get("/api/v1/teachers/profile", headers=teacher)
        dashboard = await client.get("/api/v1/teachers/dashboard", headers=teacher)
    assert profile.status_code == 200 and dashboard.status_code == 200
    assert profile.json() == {
        "user_id": "teacher_fig",
        "teacher_id": "",
        "name": "",
        "email": "teacher_fig@figures.test",
        "department": "",
        "assigned_classes": [],
        "assigned_subjects": [],
    }
    assert dashboard.json()["teacher"]["assigned_classes"] == []
    assert dashboard.json()["previous_sessions"] == [] and dashboard.json()["active_session"] is None
