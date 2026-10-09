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
    # The session was created but never started, so nobody in it is absent.
    assert "ACC-STU,Access Student,Not taken" in export.text
    assert attendance.json()["was_taken"] is False


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
async def test_an_admin_does_not_take_attendance_or_edit_rosters():
    """Creating, starting and ending a session, sending camera frames and editing the
    roster stay with the teacher who owns the session. Finalizing and deleting are
    done through the administrator's own routes.
    """
    teacher = await _token("teacher_owner", "TEACHER", ("DS-B",))
    admin = await _token("admin_acc", "ADMIN")
    async with _client() as client:
        session_id, _ = await _owned_session(client, teacher)
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
            await client.put(
                f"/api/v1/sessions/{session_id}/roster", headers=admin, json={"identities": []}
            ),
            await client.delete(f"/api/v1/sessions/{session_id}", headers=admin),
        ]
        assert [r.status_code for r in refused] == [403] * 7

        # The administrator's own routes for a session.
        finalized = await client.post(f"/api/v1/admin/sessions/{session_id}/finalize", headers=admin)
        assert finalized.status_code == 200, finalized.text
        listed = await client.get("/api/v1/admin/sessions", headers=admin)
        assert [s["status"] for s in listed.json()] == ["FINALIZED"]
        detail = await client.get(f"/api/v1/sessions/{session_id}", headers=admin)
        assert detail.json()["status"] == "FINALIZED"
        deleted = await client.delete(f"/api/v1/admin/sessions/{session_id}", headers=admin)
        assert deleted.status_code == 200


def _correction(reason: str = "Medical certificate checked by the office") -> dict:
    return {"new_status": "PRESENT", "new_presence_seconds": 0.0, "reason": reason}


@pytest.mark.anyio
async def test_an_admin_can_correct_attendance_with_a_reason_and_it_is_audited_as_theirs():
    teacher = await _token("teacher_owner", "TEACHER", ("DS-B",))
    admin = await _token("admin_acc", "ADMIN")
    db = mongodb.get_database()
    async with _client() as client:
        session_id, attendance_id = await _owned_session(client, teacher)
        path = f"/api/v1/attendance/{session_id}/records/{attendance_id}"

        corrected = await client.patch(path, headers=admin, json=_correction())
        assert corrected.status_code == 200, corrected.text
        assert corrected.json()["corrected_by"] == "admin_acc"
        assert corrected.json()["previous_status"] == "ABSENT"

        # Everyone who opens the session sees the corrected record.
        for viewer in (admin, teacher):
            row = (await client.get(f"/api/v1/attendance/{session_id}", headers=viewer)).json()["records"][0]
            assert (row["status"], row["manually_corrected"]) == ("PRESENT", True)
        history = await client.get(f"{path}/corrections", headers=teacher)
        assert [c["reason"] for c in history.json()] == ["Medical certificate checked by the office"]

    entries = [doc async for doc in db["audit_events"].find({"action": "ATTENDANCE_CORRECTED"})]
    assert len(entries) == 1
    entry = entries[0]
    assert (entry["actor_user_id"], entry["actor_role"]) == ("admin_acc", "ADMIN")
    assert entry["metadata"]["admin_correction"] is True
    assert entry["metadata"]["corrected_by_role"] == "ADMIN"
    assert entry["metadata"]["reason"] == "Medical certificate checked by the office"
    assert (entry["metadata"]["previous_status"], entry["metadata"]["new_status"]) == ("ABSENT", "PRESENT")
    assert entry["metadata"]["session_id"] == session_id


@pytest.mark.anyio
async def test_an_admin_correction_without_a_reason_is_refused_and_changes_nothing():
    teacher = await _token("teacher_owner", "TEACHER", ("DS-B",))
    admin = await _token("admin_acc", "ADMIN")
    db = mongodb.get_database()
    async with _client() as client:
        session_id, attendance_id = await _owned_session(client, teacher)
        path = f"/api/v1/attendance/{session_id}/records/{attendance_id}"

        # The one-click toggle carries no reason.
        toggle = await client.patch(path, headers=admin, json={"status": "PRESENT"})
        blank = await client.patch(path, headers=admin, json=_correction("   "))
        empty = await client.patch(path, headers=admin, json=_correction(""))
        missing = await client.patch(
            path, headers=admin, json={"new_status": "PRESENT", "new_presence_seconds": 0.0}
        )
    assert (toggle.status_code, blank.status_code) == (400, 400)
    assert "reason" in toggle.json()["detail"].lower()
    assert empty.status_code == 422 and missing.status_code in (400, 422)

    record = await db["attendance_records"].find_one({"attendance_id": attendance_id})
    assert record["status"] == "ABSENT" and not record.get("manually_corrected")
    assert await db["audit_events"].count_documents({"action": "ATTENDANCE_CORRECTED"}) == 0
    assert await db["attendance_corrections"].count_documents({}) == 0


@pytest.mark.anyio
async def test_a_teachers_correction_is_still_allowed_and_is_not_marked_as_an_admin_correction():
    teacher = await _token("teacher_owner", "TEACHER", ("DS-B",))
    other_teacher = await _token("teacher_other", "TEACHER", ("DS-B",))
    student = await _token("student_acc", "STUDENT")
    db = mongodb.get_database()
    async with _client() as client:
        session_id, attendance_id = await _owned_session(client, teacher)
        path = f"/api/v1/attendance/{session_id}/records/{attendance_id}"
        # The owner can still use the one-click toggle; nobody else can correct at all.
        toggled = await client.patch(path, headers=teacher, json={"status": "PRESENT"})
        as_other = await client.patch(path, headers=other_teacher, json=_correction())
        as_student = await client.patch(path, headers=student, json=_correction())
        no_token = await client.patch(path, json=_correction())
    assert toggled.status_code == 200, toggled.text
    assert (as_other.status_code, as_student.status_code, no_token.status_code) == (403, 403, 401)

    entry = await db["audit_events"].find_one({"action": "ATTENDANCE_CORRECTED"})
    assert (entry["actor_user_id"], entry["actor_role"]) == ("teacher_owner", "TEACHER")
    assert entry["metadata"]["admin_correction"] is False


@pytest.mark.anyio
async def test_attendance_rows_carry_the_students_name_id_and_roll_number():
    teacher = await _token("teacher_owner", "TEACHER", ("DS-B",))
    await mongodb.get_database()["student_profiles"].update_one(
        {"identity": "ACC-STU"}, {"$set": {"roll_number": "20261234"}}
    )
    async with _client() as client:
        session_id, _ = await _owned_session(client, teacher)
        row = (await client.get(f"/api/v1/attendance/{session_id}", headers=teacher)).json()["records"][0]
    assert (row["student_name"], row["student_id"], row["roll_number"]) == (
        "Access Student",
        "ACC-STU",
        "20261234",
    )


@pytest.mark.anyio
async def test_a_session_that_was_never_started_is_reported_as_not_taken():
    """Created and closed without attendance: its 0 % is not a turnout."""
    teacher = await _token("teacher_owner", "TEACHER", ("DS-B",))
    admin = await _token("admin_acc", "ADMIN")
    db = mongodb.get_database()
    async with _client() as client:
        never_taken, _ = await _owned_session(client, teacher)
        await client.post(f"/api/v1/admin/sessions/{never_taken}/finalize", headers=admin)

        # Started, everyone absent: taken, and a real 0 %.
        taken_empty = (await client.post("/api/v1/sessions", headers=teacher, json=_session("Taken"))).json()["session_id"]
        assert (await client.post(f"/api/v1/sessions/{taken_empty}/start", headers=teacher)).status_code == 200
        await client.post(f"/api/v1/sessions/{taken_empty}/finalize", headers=teacher)

        # From before start times were stored, but with a mark: taken.
        legacy = (await client.post("/api/v1/sessions", headers=teacher, json=_session("Legacy"))).json()["session_id"]
        await client.get(f"/api/v1/attendance/{legacy}", headers=teacher)
        await db["attendance_records"].update_one({"session_id": legacy}, {"$set": {"status": "PRESENT"}})
        await db["sessions"].update_one({"session_id": legacy}, {"$set": {"status": "FINALIZED"}})

        dashboard = (await client.get("/api/v1/teachers/dashboard", headers=teacher)).json()
        admin_rows = {s["session_id"]: s for s in (await client.get("/api/v1/admin/sessions", headers=admin)).json()}

    teacher_rows = {s["session_id"]: s for s in dashboard["previous_sessions"]}
    for rows in (teacher_rows, admin_rows):
        assert rows[never_taken]["was_taken"] is False
        assert rows[taken_empty]["was_taken"] is True
        assert rows[legacy]["was_taken"] is True
    assert teacher_rows[taken_empty]["attendance_percentage"] == 0.0
    assert (await db["sessions"].find_one({"session_id": taken_empty}))["started_at"] is not None
