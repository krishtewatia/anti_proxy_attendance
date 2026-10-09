"""An administrator can open and manage any session.

Regression test: the session and attendance routes were limited to the
TEACHER role, so an administrator got 403 "Insufficient permissions" before
the ownership check (which lets administrators through) was reached.

Taking attendance stays a teacher's job: creating, starting and ending a
session and sending camera frames remain teacher-only.
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

PASSWORD = "SessionAccess123!"


@pytest.fixture(autouse=True)
async def fresh_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await init_indexes(db)
    await db["academic_classes"].insert_one(
        {"class_id": "DS-B", "class_code": "DS-B", "branch": "Data Science", "section": "B"}
    )
    await db["student_profiles"].insert_one(
        {"user_id": "student_acc", "identity": "ACC-STU", "student_id": "ACC-STU",
         "name": "Access Student", "email": "student_acc@access.test", "class_code": "DS-B"}
    )
    yield
    mongodb._client = AsyncMongoMockClient()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _token(user_id: str, role: str, classes: tuple[str, ...] = ()) -> dict[str, str]:
    await create_user(
        user_id=user_id,
        email=f"{user_id}@access.test",
        password_hash=hash_password(PASSWORD),
        role=role,
    )
    if role == "TEACHER":
        await mongodb.get_database()["teacher_profiles"].insert_one(
            {"user_id": user_id, "teacher_id": f"T-{user_id}", "name": "Access Teacher",
             "email": f"{user_id}@access.test", "department": "Data Science",
             "assigned_classes": list(classes), "assigned_subjects": []}
        )
    return {"Authorization": f"Bearer {create_access_token(user_id=user_id, role=role)}"}


def _session(name: str = "Access Session") -> dict:
    return {
        "course_name": name,
        "classroom_id": "ROOM_101",
        "start_time": "2026-10-20T09:00:00Z",
        "end_time": "2026-10-20T10:00:00Z",
        "required_presence_percentage": 75.0,
        "class_code": "DS-B",
    }


async def _owned_session(client: AsyncClient, teacher: dict) -> tuple[str, str]:
    """A session a teacher created, with one rostered student. Returns (session_id, attendance_id)."""
    created = await client.post("/api/v1/sessions", headers=teacher, json=_session())
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]
    listing = await client.get(f"/api/v1/attendance/{session_id}", headers=teacher)
    assert listing.status_code == 200, listing.text
    return session_id, listing.json()["records"][0]["attendance_id"]


def _view_routes(session_id: str, attendance_id: str) -> list[str]:
    return [
        f"/api/v1/sessions/{session_id}",
        f"/api/v1/sessions/{session_id}/live-snapshot",
        f"/api/v1/sessions/{session_id}/roster",
        f"/api/v1/attendance/{session_id}",
        f"/api/v1/attendance/{session_id}/export",
        f"/api/v1/attendance/{session_id}/records/{attendance_id}/corrections",
    ]


@pytest.mark.anyio
async def test_an_admin_can_open_every_view_of_a_session_they_do_not_own():
    teacher = await _token("teacher_owner", "TEACHER", ("DS-B",))
    admin = await _token("admin_acc", "ADMIN")
    async with _client() as client:
        session_id, attendance_id = await _owned_session(client, teacher)
        for path in _view_routes(session_id, attendance_id):
            response = await client.get(path, headers=admin)
            assert response.status_code == 200, (path, response.status_code, response.text)

        detail = await client.get(f"/api/v1/sessions/{session_id}", headers=admin)
        attendance = await client.get(f"/api/v1/attendance/{session_id}", headers=admin)
        export = await client.get(f"/api/v1/attendance/{session_id}/export", headers=admin)
    assert detail.json()["created_by"] == "teacher_owner"
    assert [r["student_id"] for r in attendance.json()["records"]] == ["ACC-STU"]
    assert "ACC-STU,Access Student,ABSENT" in export.text


@pytest.mark.anyio
async def test_other_teachers_and_students_still_cannot_open_the_session():
    teacher = await _token("teacher_owner", "TEACHER", ("DS-B",))
    other_teacher = await _token("teacher_other", "TEACHER", ("DS-B",))
    student = await _token("student_acc", "STUDENT")
    async with _client() as client:
        session_id, attendance_id = await _owned_session(client, teacher)
        for path in _view_routes(session_id, attendance_id):
            as_other = await client.get(path, headers=other_teacher)
            as_student = await client.get(path, headers=student)
            no_token = await client.get(path)
            assert (as_other.status_code, as_student.status_code, no_token.status_code) == (
                403,
                403,
                401,
            ), path
            assert "Access Student" not in as_other.text + as_student.text


@pytest.mark.anyio
async def test_the_session_list_shows_a_teacher_their_own_and_an_admin_everything():
    first = await _token("teacher_one", "TEACHER", ("DS-B",))
    second = await _token("teacher_two", "TEACHER", ("DS-B",))
    admin = await _token("admin_acc", "ADMIN")
    async with _client() as client:
        await client.post("/api/v1/sessions", headers=first, json=_session("First"))
        await client.post("/api/v1/sessions", headers=second, json=_session("Second"))
        as_first = await client.get("/api/v1/sessions", headers=first)
        as_admin = await client.get("/api/v1/sessions", headers=admin)
    assert [s["course_name"] for s in as_first.json()] == ["First"]
    assert sorted(s["course_name"] for s in as_admin.json()) == ["First", "Second"]


@pytest.mark.anyio
async def test_an_admin_reads_but_does_not_take_or_correct_attendance():
    """Opening a session is read-only for an administrator.

    Creating, starting and ending a session, sending camera frames, editing
    the roster and correcting a record stay with the teacher who owns it.
    Finalizing and deleting are done through the administrator's own routes.
    """
    teacher = await _token("teacher_owner", "TEACHER", ("DS-B",))
    admin = await _token("admin_acc", "ADMIN")
    db = mongodb.get_database()
    async with _client() as client:
        session_id, attendance_id = await _owned_session(client, teacher)
        refused = [
            await client.post("/api/v1/sessions", headers=admin, json=_session()),
            await client.post(f"/api/v1/sessions/{session_id}/start", headers=admin),
            await client.post(f"/api/v1/sessions/{session_id}/end", headers=admin),
            await client.post(
                f"/api/v1/attendance/{session_id}/process-frame",
                headers=admin,
                files={"frame": ("frame.jpg", b"frame bytes", "image/jpeg")},
            ),
            await client.post(
                f"/api/v1/sessions/{session_id}/roster", headers=admin, json={"identities": []}
            ),
            await client.patch(
                f"/api/v1/attendance/{session_id}/records/{attendance_id}",
                headers=admin,
                json={"new_status": "PRESENT", "new_presence_seconds": 3600.0, "reason": "Office"},
            ),
            await client.delete(f"/api/v1/sessions/{session_id}", headers=admin),
        ]
        assert [r.status_code for r in refused] == [403] * 7
        record = await db["attendance_records"].find_one({"attendance_id": attendance_id})
        assert record["status"] == "ABSENT"

        # The administrator's own routes for a session.
        finalized = await client.post(f"/api/v1/admin/sessions/{session_id}/finalize", headers=admin)
        assert finalized.status_code == 200, finalized.text
        listed = await client.get("/api/v1/admin/sessions", headers=admin)
        assert [s["status"] for s in listed.json()] == ["FINALIZED"]
        detail = await client.get(f"/api/v1/sessions/{session_id}", headers=admin)
        assert detail.json()["status"] == "FINALIZED"
        deleted = await client.delete(f"/api/v1/admin/sessions/{session_id}", headers=admin)
        assert deleted.status_code == 200
