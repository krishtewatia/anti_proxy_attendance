"""Who may list a class's students, and which subjects a session or a teacher may be given.

* The students of a class are listed only for an administrator or a teacher
  assigned to that class.
* A session, and a teacher assignment, accept only a subject that exists in
  the catalog and is active.
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
from app.services import account_admin_service, approval_service, student_deletion

PASSWORD = "CatalogRules123!"
ADMIN = "/api/v1/admin"


@pytest.fixture(autouse=True)
async def fresh_db(monkeypatch):
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await init_indexes(db)
    for code, branch, section in (("DS-B", "Data Science", "B"), ("DS-C", "Data Science", "C")):
        await db["academic_classes"].insert_one(
            {"class_id": code, "class_code": code, "branch": branch, "section": section}
        )
    await db["subjects"].insert_many(
        [
            {"subject_id": "sub_ml", "name": "Machine Learning"},
            {"subject_id": "sub_dbms", "name": "DBMS"},
            {"subject_id": "sub_old", "name": "Retired Subject", "status": "ARCHIVED"},
        ]
    )
    await db["student_profiles"].insert_many(
        [
            {"user_id": "student_b", "identity": "STU-B", "student_id": "STU-B", "name": "Student B",
             "email": "student_b@rules.test", "class_code": "DS-B"},
            {"user_id": "student_c", "identity": "STU-C", "student_id": "STU-C", "name": "Student C",
             "email": "student_c@rules.test", "class_code": "DS-C"},
        ]
    )

    async def fake_refresh() -> bool:
        return True

    for module in (student_deletion, approval_service, account_admin_service):
        monkeypatch.setattr(module, "_refresh_vision_gallery", fake_refresh)
    yield
    mongodb._client = AsyncMongoMockClient()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _token(user_id: str, role: str) -> dict[str, str]:
    await create_user(
        user_id=user_id,
        email=f"{user_id}@rules.test",
        password_hash=hash_password(PASSWORD),
        role=role,
    )
    return {"Authorization": f"Bearer {create_access_token(user_id=user_id, role=role)}"}


async def _teacher(user_id: str, classes: list[str], subjects: list[str] | None = None) -> dict[str, str]:
    headers = await _token(user_id, "TEACHER")
    await mongodb.get_database()["teacher_profiles"].insert_one(
        {
            "user_id": user_id,
            "teacher_id": f"T-{user_id}",
            "name": "Rules Teacher",
            "email": f"{user_id}@rules.test",
            "department": "Data Science",
            "assigned_classes": classes,
            "assigned_subjects": subjects or [],
        }
    )
    return headers


def _session(subject: str | None = None, class_code: str = "DS-B") -> dict:
    payload = {
        "course_name": "Rules Session",
        "classroom_id": "ROOM_101",
        "start_time": "2026-10-20T09:00:00Z",
        "end_time": "2026-10-20T10:00:00Z",
        "required_presence_percentage": 75.0,
        "class_code": class_code,
    }
    if subject is not None:
        payload["subject"] = subject
    return payload


# ------------------------------------------------------------------------------
# Listing the students of a class
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_class_students_are_listed_for_admins_and_that_class_teachers_only():
    admin = await _token("admin_rules", "ADMIN")
    teacher_b = await _teacher("teacher_b", ["DS-B"])
    teacher_c = await _teacher("teacher_c", ["DS-C"])
    teacher_none = await _teacher("teacher_none", [])
    student_b = await _token("student_b", "STUDENT")
    path = "/api/v1/academic/classes/DS-B/students"
    async with _client() as client:
        as_admin = await client.get(path, headers=admin)
        as_own_teacher = await client.get("/api/v1/academic/classes/ds-b/students", headers=teacher_b)
        as_other_teacher = await client.get(path, headers=teacher_c)
        as_unassigned_teacher = await client.get(path, headers=teacher_none)
        # Not even a student of that class.
        as_student = await client.get(path, headers=student_b)
        no_token = await client.get(path)
        # A class that does not exist gives the same answer, so codes cannot be probed.
        unknown_as_student = await client.get("/api/v1/academic/classes/NOPE-1/students", headers=student_b)
        unknown_as_teacher = await client.get("/api/v1/academic/classes/NOPE-1/students", headers=teacher_b)

    assert as_admin.status_code == 200 and as_own_teacher.status_code == 200
    assert [s["student_id"] for s in as_admin.json()] == ["STU-B"]
    assert [s["student_id"] for s in as_own_teacher.json()] == ["STU-B"]
    assert [
        r.status_code
        for r in (as_other_teacher, as_unassigned_teacher, as_student, unknown_as_student, unknown_as_teacher)
    ] == [403, 403, 403, 403, 403]
    assert no_token.status_code == 401
    for refused in (as_other_teacher, as_student):
        assert "Student B" not in refused.text and "STU-B" not in refused.text


@pytest.mark.anyio
async def test_a_teacher_loses_the_class_list_when_the_class_is_taken_away():
    admin = await _token("admin_rules", "ADMIN")
    teacher = await _teacher("teacher_b", ["DS-B"])
    path = "/api/v1/academic/classes/DS-B/students"
    async with _client() as client:
        before = await client.get(path, headers=teacher)
        await client.patch(f"{ADMIN}/teachers/teacher_b", headers=admin, json={"assigned_classes": ["DS-C"]})
        after = await client.get(path, headers=teacher)
    assert (before.status_code, after.status_code) == (200, 403)


# ------------------------------------------------------------------------------
# Subjects of a session
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_session_accepts_only_an_active_catalog_subject():
    admin = await _token("admin_rules", "ADMIN")
    teacher = await _teacher("teacher_b", ["DS-B"])
    db = mongodb.get_database()
    async with _client() as client:
        unknown = await client.post("/api/v1/sessions", headers=teacher, json=_session("Astrology"))
        archived = await client.post("/api/v1/sessions", headers=teacher, json=_session("Retired Subject"))
        admin_unknown = await client.post(f"{ADMIN}/sessions", headers=admin, json=_session("Astrology"))
        admin_archived = await client.post(f"{ADMIN}/sessions", headers=admin, json=_session("retired subject"))
        assert [r.status_code for r in (unknown, archived, admin_unknown, admin_archived)] == [400] * 4
        assert "Astrology" in unknown.json()["detail"]
        assert await db["sessions"].count_documents({}) == 0

        known = await client.post("/api/v1/sessions", headers=teacher, json=_session("Machine Learning"))
        other_case = await client.post(f"{ADMIN}/sessions", headers=admin, json=_session("dbms"))
        no_subject = await client.post(f"{ADMIN}/sessions", headers=admin, json=_session(None))
        assert [r.status_code for r in (known, other_case, no_subject)] == [201, 201, 201]


# ------------------------------------------------------------------------------
# Subjects assigned to a teacher
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_every_way_of_assigning_a_subject_refuses_unknown_and_archived_ones():
    admin = await _token("admin_rules", "ADMIN")
    await _teacher("teacher_b", ["DS-B"])
    db = mongodb.get_database()
    async with _client() as client:
        for subject in ("Astrology", "Retired Subject"):
            by_edit = await client.patch(
                f"{ADMIN}/teachers/teacher_b", headers=admin, json={"assigned_subjects": ["DBMS", subject]}
            )
            by_assign = await client.post(
                f"{ADMIN}/teachers/teacher_b/assign",
                headers=admin,
                json={"assigned_classes": ["DS-B"], "assigned_subjects": [subject]},
            )
            by_create = await client.post(
                f"{ADMIN}/teachers",
                headers=admin,
                json={
                    "name": "New Teacher",
                    "email": "new.teacher@rules.test",
                    "password": PASSWORD,
                    "teacher_id": "T-NEW",
                    "department": "Data Science",
                    "assigned_classes": ["DS-B"],
                    "assigned_subjects": [subject],
                },
            )
            waiting = await client.post(
                "/api/v1/auth/register",
                json={"email": f"waiting.{subject[:3].lower()}@rules.test", "password": PASSWORD, "role": "TEACHER"},
            )
            by_approval = await client.post(
                f"{ADMIN}/approvals/{waiting.json()['user_id']}/approve",
                headers=admin,
                json={"assigned_classes": ["DS-B"], "assigned_subjects": [subject]},
            )
            statuses = [r.status_code for r in (by_edit, by_assign, by_create, by_approval)]
            assert statuses == [400, 400, 400, 400], (subject, statuses)
            assert subject in by_edit.json()["detail"]

        assert (await db["teacher_profiles"].find_one({"user_id": "teacher_b"}))["assigned_subjects"] == []
        assert await db["users"].count_documents({"email": "new.teacher@rules.test"}) == 0
        assert await db["users"].count_documents({"status": "PENDING"}) == 2

        accepted = await client.patch(
            f"{ADMIN}/teachers/teacher_b", headers=admin, json={"assigned_subjects": ["Machine Learning", "DBMS"]}
        )
        assert accepted.status_code == 200
    profile = await db["teacher_profiles"].find_one({"user_id": "teacher_b"})
    assert profile["assigned_subjects"] == ["Machine Learning", "DBMS"]


@pytest.mark.anyio
async def test_a_teacher_keeps_subjects_they_already_had_when_edited_for_something_else():
    """Records from before this rule may hold a subject that is not in the catalog."""
    admin = await _token("admin_rules", "ADMIN")
    await _teacher("teacher_b", ["DS-B"], ["Old Free Text Subject", "Retired Subject"])
    async with _client() as client:
        keeps = await client.patch(
            f"{ADMIN}/teachers/teacher_b",
            headers=admin,
            json={"assigned_subjects": ["Old Free Text Subject", "Retired Subject", "DBMS"]},
        )
        adds_unknown = await client.patch(
            f"{ADMIN}/teachers/teacher_b",
            headers=admin,
            json={"assigned_subjects": ["Old Free Text Subject", "Another Unknown"]},
        )
    assert (keeps.status_code, adds_unknown.status_code) == (200, 400)
