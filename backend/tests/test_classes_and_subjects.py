"""Classes and subjects: create, edit, archive, restore, delete.

An archived class or subject is hidden from registration, new sessions and
new assignments, and everything that already refers to it is kept. A class or
subject that is in use cannot be renamed or deleted.
"""

import json

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

PASSWORD = "CatalogPass123!"
ADMIN = "/api/v1/admin"
CLASSES = f"{ADMIN}/academic/classes"
SUBJECTS = f"{ADMIN}/academic/subjects"


@pytest.fixture(autouse=True)
async def fresh_db(monkeypatch):
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await init_indexes(db)
    for code, branch, section in (
        ("DS-B", "Data Science", "B"),
        ("DS-C", "Data Science", "C"),
        ("CS-A", "Computer Science", "A"),
    ):
        await db["academic_classes"].insert_one(
            {"class_id": code, "class_code": code, "branch": branch, "section": section}
        )
    for subject_id, name in (("sub_ml", "Machine Learning"), ("sub_dbms", "DBMS")):
        await db["subjects"].insert_one({"subject_id": subject_id, "name": name, "code": None})

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
        email=f"{user_id}@catalog.test",
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
            "name": "Catalog Teacher",
            "email": f"{user_id}@catalog.test",
            "department": "Data Science",
            "assigned_classes": classes,
            "assigned_subjects": subjects or [],
        }
    )
    return headers


def _student(student_id: str, **overrides) -> dict:
    payload = {
        "name": "Catalog Student",
        "email": f"{student_id.lower()}@catalog.test",
        "password": PASSWORD,
        "student_id": student_id,
        "roll_number": "20260001",
        "branch": "Data Science",
        "section": "B",
    }
    payload.update(overrides)
    return payload


def _session(class_code: str = "DS-B", subject: str | None = None) -> dict:
    payload = {
        "course_name": "Catalog Session",
        "classroom_id": "ROOM_101",
        "start_time": "2026-10-20T09:00:00Z",
        "end_time": "2026-10-20T10:00:00Z",
        "required_presence_percentage": 75.0,
        "class_code": class_code,
    }
    if subject is not None:
        payload["subject"] = subject
    return payload


async def _audit(action: str) -> list[dict]:
    return [doc async for doc in mongodb.get_database()["audit_events"].find({"action": action})]


async def _class_row(client: AsyncClient, admin: dict, code: str) -> dict | None:
    rows = (await client.get(CLASSES, headers=admin)).json()
    return next((row for row in rows if row["class_code"] == code), None)


async def _subject_row(client: AsyncClient, admin: dict, name: str) -> dict | None:
    rows = (await client.get(SUBJECTS, headers=admin)).json()
    return next((row for row in rows if row["name"] == name), None)


# ------------------------------------------------------------------------------
# Classes: create and edit
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_creating_a_class_makes_it_available_everywhere():
    admin = await _token("admin_cat", "ADMIN")
    async with _client() as client:
        created = await client.post(
            CLASSES,
            headers=admin,
            json={"class_code": "ece-a", "branch": " Electronics ", "section": "a", "semester": 4},
        )
        assert created.status_code == 201, created.text
        assert created.json()["class_code"] == "ECE-A"

        row = await _class_row(client, admin, "ECE-A")
        assert row["status"] == "ACTIVE" and row["in_use"] is False
        assert (row["branch"], row["section"], row["semester"]) == ("Electronics", "A", 4)
        assert row["usage"] == {"students": 0, "teachers": 0, "sessions": 0}

        public = await client.get("/api/v1/academic/public/classes")
        structure = await client.get("/api/v1/academic/structure", headers=admin)
        assert "ECE-A" in [c["class_code"] for c in public.json()]
        assert "ECE-A" in [c["class_code"] for c in structure.json()["classes"]]
        assert {"name": "Electronics", "sections": ["A"]} in structure.json()["branches"]

    entries = await _audit("CLASS_CREATED")
    assert len(entries) == 1 and entries[0]["resource_id"] == "ECE-A"


@pytest.mark.anyio
async def test_a_class_that_already_exists_or_is_malformed_is_refused():
    admin = await _token("admin_cat", "ADMIN")
    async with _client() as client:
        same_code = await client.post(
            CLASSES, headers=admin, json={"class_code": "ds-b", "branch": "Design", "section": "Z"}
        )
        same_pair = await client.post(
            CLASSES, headers=admin, json={"class_code": "DSCI-B", "branch": "data science", "section": "b"}
        )
        bad = [
            await client.post(CLASSES, headers=admin, json=body)
            for body in (
                {"class_code": "A", "branch": "Design", "section": "A"},
                {"class_code": "has space", "branch": "Design", "section": "A"},
                {"class_code": "../x", "branch": "Design", "section": "A"},
                {"class_code": "DE-A", "branch": " ", "section": "A"},
                {"class_code": "DE-A", "branch": "Design", "section": "A", "semester": 40},
            )
        ]
    assert (same_code.status_code, same_pair.status_code) == (409, 409)
    assert "DS-B" in same_pair.json()["detail"]
    assert [response.status_code for response in bad] == [400, 400, 400, 400, 400]
    # The existing class was not overwritten.
    stored = await mongodb.get_database()["academic_classes"].find_one({"class_code": "DS-B"})
    assert stored["branch"] == "Data Science"


@pytest.mark.anyio
async def test_an_unused_class_can_be_changed_completely():
    admin = await _token("admin_cat", "ADMIN")
    async with _client() as client:
        edited = await client.patch(
            f"{CLASSES}/CS-A",
            headers=admin,
            json={"class_code": "CSE-D", "branch": "Computer Science", "section": "d", "semester": 2},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json() == {
            "class_code": "CSE-D",
            "changed": ["class_code", "section", "semester"],
        }
        assert await _class_row(client, admin, "CS-A") is None
        assert (await _class_row(client, admin, "CSE-D"))["section"] == "D"

        onto_existing = await client.patch(
            f"{CLASSES}/CSE-D", headers=admin, json={"class_code": "DS-B"}
        )
        onto_existing_pair = await client.patch(
            f"{CLASSES}/CSE-D", headers=admin, json={"branch": "Data Science", "section": "C"}
        )
        unknown_field = await client.patch(f"{CLASSES}/CSE-D", headers=admin, json={"status": "X"})
        missing = await client.patch(f"{CLASSES}/NOPE-1", headers=admin, json={"semester": 1})
    assert (
        onto_existing.status_code,
        onto_existing_pair.status_code,
        unknown_field.status_code,
        missing.status_code,
    ) == (409, 409, 422, 404)
    entries = await _audit("CLASS_UPDATED")
    assert len(entries) == 1
    assert entries[0]["metadata"] == {
        "fields": ["class_code", "section", "semester"],
        "previous_class_code": "CS-A",
    }


@pytest.mark.anyio
async def test_a_class_in_use_keeps_its_code_branch_and_section():
    admin = await _token("admin_cat", "ADMIN")
    db = mongodb.get_database()
    async with _client() as client:
        registered = await client.post("/api/v1/students/register", json=_student("CAT001"))
        assert registered.status_code == 201, registered.text

        refused = [
            await client.patch(f"{CLASSES}/DS-B", headers=admin, json=body)
            for body in ({"class_code": "DS-X"}, {"branch": "Design"}, {"section": "Z"})
        ]
        assert [response.status_code for response in refused] == [409, 409, 409]
        assert "1 students" in refused[0].json()["detail"]

        semester = await client.patch(f"{CLASSES}/DS-B", headers=admin, json={"semester": 7})
        assert semester.status_code == 200 and semester.json()["changed"] == ["semester"]
        row = await _class_row(client, admin, "DS-B")
        assert row["in_use"] is True and row["usage"]["students"] == 1 and row["semester"] == 7

    profile = await db["student_profiles"].find_one({"student_id": "CAT001"})
    assert profile["class_code"] == "DS-B"


# ------------------------------------------------------------------------------
# Classes: archive and restore
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_an_archived_class_is_hidden_from_registration_sessions_and_assignments():
    admin = await _token("admin_cat", "ADMIN")
    teacher = await _teacher("teacher_cat", ["DS-B", "DS-C"])
    other_teacher = await _teacher("teacher_two", ["DS-C"])
    db = mongodb.get_database()
    async with _client() as client:
        existing_student = await client.post("/api/v1/students/register", json=_student("CAT001"))
        pending_student = await client.post("/api/v1/students/register", json=_student("CAT002"))
        existing_session = await client.post("/api/v1/sessions", headers=teacher, json=_session("DS-B"))
        assert existing_session.status_code == 201, existing_session.text

        archived = await client.post(f"{CLASSES}/DS-B/archive", headers=admin)
        assert archived.status_code == 200, archived.text
        assert archived.json()["status"] == "ARCHIVED"
        assert archived.json()["usage"] == {"students": 2, "teachers": 1, "sessions": 1}

        # Hidden from every list a person chooses a class from.
        public = await client.get("/api/v1/academic/public/classes")
        plain = await client.get("/api/v1/academic/classes", headers=teacher)
        structure = await client.get("/api/v1/academic/structure", headers=admin)
        for listing in (public.json(), plain.json(), structure.json()["classes"]):
            assert "DS-B" not in [c["class_code"] for c in listing]
        assert {"name": "Data Science", "sections": ["C"]} in structure.json()["branches"]
        assert (await _class_row(client, admin, "DS-B"))["status"] == "ARCHIVED"

        # Registration: by code and by branch and section.
        by_code = await client.post(
            "/api/v1/students/register", json=_student("CAT003", class_code="DS-B")
        )
        by_pair = await client.post("/api/v1/students/register", json=_student("CAT004"))
        assert (by_code.status_code, by_pair.status_code) == (400, 400)
        assert await db["users"].count_documents({"email": "cat003@catalog.test"}) == 0

        # Approval into the archived class.
        approve = await client.post(
            f"{ADMIN}/approvals/{pending_student.json()['user_id']}/approve", headers=admin, json={}
        )
        approve_elsewhere = await client.post(
            f"{ADMIN}/approvals/{pending_student.json()['user_id']}/approve",
            headers=admin,
            json={"class_code": "DS-C"},
        )
        assert (approve.status_code, approve_elsewhere.status_code) == (400, 200)

        # New sessions.
        new_session = await client.post("/api/v1/sessions", headers=teacher, json=_session("DS-B"))
        admin_session = await client.post(f"{ADMIN}/sessions", headers=admin, json=_session("DS-B"))
        still_fine = await client.post("/api/v1/sessions", headers=other_teacher, json=_session("DS-C"))
        assert (new_session.status_code, admin_session.status_code, still_fine.status_code) == (
            400,
            400,
            201,
        )
        assert "archived" in new_session.json()["detail"]

        # New assignments, through every route that assigns a class.
        by_edit = await client.patch(
            f"{ADMIN}/teachers/teacher_two", headers=admin, json={"assigned_classes": ["DS-C", "DS-B"]}
        )
        by_assign = await client.post(
            f"{ADMIN}/teachers/teacher_two/assign",
            headers=admin,
            json={"assigned_classes": ["DS-B"], "assigned_subjects": []},
        )
        by_create = await client.post(
            f"{ADMIN}/teachers",
            headers=admin,
            json={
                "name": "New Teacher",
                "email": "new.teacher@catalog.test",
                "password": PASSWORD,
                "teacher_id": "T-NEW",
                "department": "Data Science",
                "assigned_classes": ["DS-B"],
            },
        )
        waiting = await client.post(
            "/api/v1/auth/register",
            json={"email": "waiting@catalog.test", "password": PASSWORD, "role": "TEACHER"},
        )
        by_approval = await client.post(
            f"{ADMIN}/approvals/{waiting.json()['user_id']}/approve",
            headers=admin,
            json={"assigned_classes": ["DS-B"]},
        )
        assert [r.status_code for r in (by_edit, by_assign, by_create, by_approval)] == [400] * 4
        assert await db["users"].count_documents({"email": "new.teacher@catalog.test"}) == 0

        # A teacher who already had the class keeps it when edited for something else.
        keeps = await client.patch(
            f"{ADMIN}/teachers/teacher_cat", headers=admin, json={"assigned_classes": ["DS-B"]}
        )
        assert keeps.status_code == 200, keeps.text

    # Nothing that referred to the class was touched.
    assert (await db["student_profiles"].find_one({"student_id": "CAT001"}))["class_code"] == "DS-B"
    assert await db["sessions"].count_documents({"class_code": "DS-B"}) == 1
    entries = await _audit("CLASS_ARCHIVED")
    assert len(entries) == 1 and entries[0]["resource_id"] == "DS-B"


@pytest.mark.anyio
async def test_restoring_a_class_makes_it_available_again():
    admin = await _token("admin_cat", "ADMIN")
    teacher = await _teacher("teacher_cat", ["DS-B"])
    async with _client() as client:
        assert (await client.post(f"{CLASSES}/DS-B/archive", headers=admin)).status_code == 200
        again = await client.post(f"{CLASSES}/DS-B/archive", headers=admin)
        recreate = await client.post(
            CLASSES, headers=admin, json={"class_code": "DS-B", "branch": "Data Science", "section": "B"}
        )
        assert (again.status_code, recreate.status_code) == (409, 409)
        assert "restore" in recreate.json()["detail"]

        restored = await client.post(f"{CLASSES}/DS-B/unarchive", headers=admin)
        assert restored.status_code == 200 and restored.json()["status"] == "ACTIVE"
        not_archived = await client.post(f"{CLASSES}/DS-B/unarchive", headers=admin)
        assert not_archived.status_code == 409

        public = await client.get("/api/v1/academic/public/classes")
        assert "DS-B" in [c["class_code"] for c in public.json()]
        registered = await client.post("/api/v1/students/register", json=_student("CAT001"))
        session = await client.post("/api/v1/sessions", headers=teacher, json=_session("DS-B"))
        assert (registered.status_code, session.status_code) == (201, 201)
    assert len(await _audit("CLASS_UNARCHIVED")) == 1


@pytest.mark.anyio
async def test_a_class_with_a_session_in_progress_cannot_be_archived():
    admin = await _token("admin_cat", "ADMIN")
    teacher = await _teacher("teacher_cat", ["DS-B"])
    async with _client() as client:
        session = await client.post("/api/v1/sessions", headers=teacher, json=_session("DS-B"))
        session_id = session.json()["session_id"]
        await mongodb.get_database()["sessions"].update_one(
            {"session_id": session_id}, {"$set": {"status": "ACTIVE"}}
        )
        blocked = await client.post(f"{CLASSES}/DS-B/archive", headers=admin)
        assert blocked.status_code == 409
        await mongodb.get_database()["sessions"].update_one(
            {"session_id": session_id}, {"$set": {"status": "FINALIZED"}}
        )
        allowed = await client.post(f"{CLASSES}/DS-B/archive", headers=admin)
        assert allowed.status_code == 200


# ------------------------------------------------------------------------------
# Classes: delete
# ------------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("referrer", ["student", "teacher", "session"])
async def test_a_class_something_refers_to_cannot_be_deleted(referrer):
    admin = await _token("admin_cat", "ADMIN")
    db = mongodb.get_database()
    async with _client() as client:
        if referrer == "student":
            await client.post("/api/v1/students/register", json=_student("CAT001"))
        elif referrer == "teacher":
            await _teacher("teacher_cat", ["DS-B"])
        else:
            await db["sessions"].insert_one(
                {"session_id": "old_session", "class_code": "DS-B", "status": "FINALIZED"}
            )
        refused = await client.delete(f"{CLASSES}/DS-B", headers=admin)
        # Archiving is the way out, and still does not allow deleting.
        await client.post(f"{CLASSES}/DS-B/archive", headers=admin)
        refused_archived = await client.delete(f"{CLASSES}/DS-B", headers=admin)
    assert (refused.status_code, refused_archived.status_code) == (409, 409)
    assert f"1 {referrer}s" in refused.json()["detail"]
    assert await db["academic_classes"].count_documents({"class_code": "DS-B"}) == 1
    assert await _audit("CLASS_DELETED") == []


@pytest.mark.anyio
async def test_an_unused_class_can_be_deleted():
    admin = await _token("admin_cat", "ADMIN")
    async with _client() as client:
        deleted = await client.delete(f"{CLASSES}/cs-a", headers=admin)
        again = await client.delete(f"{CLASSES}/CS-A", headers=admin)
        public = await client.get("/api/v1/academic/public/classes")
    assert (deleted.status_code, again.status_code) == (200, 404)
    assert "CS-A" not in [c["class_code"] for c in public.json()]
    entries = await _audit("CLASS_DELETED")
    assert len(entries) == 1 and entries[0]["resource_id"] == "CS-A"


# ------------------------------------------------------------------------------
# Registration chooses from the active classes
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_the_public_class_list_needs_no_sign_in_and_holds_only_what_the_form_needs():
    admin = await _token("admin_cat", "ADMIN")
    async with _client() as client:
        await client.post(f"{CLASSES}/DS-C/archive", headers=admin)
        public = await client.get("/api/v1/academic/public/classes")
    assert public.status_code == 200
    assert public.json() == [
        {"class_code": "CS-A", "branch": "Computer Science", "section": "A"},
        {"class_code": "DS-B", "branch": "Data Science", "section": "B"},
    ]


@pytest.mark.anyio
async def test_a_student_registers_into_a_class_chosen_by_its_code():
    admin = await _token("admin_cat", "ADMIN")
    db = mongodb.get_database()
    async with _client() as client:
        await client.post(
            CLASSES, headers=admin, json={"class_code": "ECE-A", "branch": "Electronics", "section": "A"}
        )
        # Only the code: branch and section come from the class.
        by_code = await client.post(
            "/api/v1/students/register",
            json=_student("CAT001", class_code="ece-a", branch="", section=""),
        )
        # The older form: branch and section, for a class whose code is not derived from them.
        by_pair = await client.post(
            "/api/v1/students/register",
            json=_student("CAT002", branch="electronics", section="a"),
        )
        unknown_code = await client.post(
            "/api/v1/students/register", json=_student("CAT003", class_code="NOPE-1")
        )
        unknown_pair = await client.post(
            "/api/v1/students/register", json=_student("CAT004", branch="History", section="Q")
        )
        nothing = await client.post(
            "/api/v1/students/register", json=_student("CAT005", branch="", section="")
        )
    assert (by_code.status_code, by_pair.status_code) == (201, 201)
    assert (unknown_code.status_code, unknown_pair.status_code, nothing.status_code) == (400, 400, 422)
    for student_id in ("CAT001", "CAT002"):
        profile = await db["student_profiles"].find_one({"student_id": student_id})
        assert (profile["class_code"], profile["branch"], profile["section"]) == (
            "ECE-A",
            "Electronics",
            "A",
        )
    assert await db["users"].count_documents({}) == 3  # the admin and the two students


@pytest.mark.anyio
async def test_an_admin_moves_a_student_to_another_class_by_its_code():
    admin = await _token("admin_cat", "ADMIN")
    db = mongodb.get_database()
    async with _client() as client:
        created = await client.post(f"{ADMIN}/students", headers=admin, json=_student("CAT001"))
        user_id = created.json()["user_id"]
        await client.post(f"{CLASSES}/DS-C/archive", headers=admin)

        moved = await client.patch(
            f"{ADMIN}/students/{user_id}", headers=admin, json={"class_code": "CS-A"}
        )
        into_archived = await client.patch(
            f"{ADMIN}/students/{user_id}", headers=admin, json={"class_code": "DS-C"}
        )
        unknown = await client.patch(
            f"{ADMIN}/students/{user_id}", headers=admin, json={"class_code": "NOPE-1"}
        )
        assert (moved.status_code, into_archived.status_code, unknown.status_code) == (200, 400, 400)
        profile = await db["student_profiles"].find_one({"user_id": user_id})
        assert (profile["class_code"], profile["branch"], profile["section"]) == (
            "CS-A",
            "Computer Science",
            "A",
        )

        # A student whose class is archived later can still be edited.
        await client.post(f"{CLASSES}/CS-A/archive", headers=admin)
        renamed = await client.patch(
            f"{ADMIN}/students/{user_id}",
            headers=admin,
            json={"name": "Renamed Student", "class_code": "CS-A"},
        )
        assert renamed.status_code == 200 and renamed.json()["changed"] == ["name"]


# ------------------------------------------------------------------------------
# Subjects
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_subjects_are_created_edited_and_listed():
    admin = await _token("admin_cat", "ADMIN")
    async with _client() as client:
        created = await client.post(
            SUBJECTS, headers=admin, json={"name": " Robotics ", "code": "RB-101", "branch": "AI & ML"}
        )
        assert created.status_code == 201, created.text
        subject_id = created.json()["subject_id"]

        duplicate = await client.post(SUBJECTS, headers=admin, json={"name": "machine learning"})
        blank = await client.post(SUBJECTS, headers=admin, json={"name": " "})
        assert (duplicate.status_code, blank.status_code) == (409, 400)

        edited = await client.patch(
            f"{SUBJECTS}/{subject_id}",
            headers=admin,
            json={"name": "Robotics II", "code": "RB-201", "branch": ""},
        )
        assert edited.status_code == 200
        assert edited.json()["changed"] == ["branch", "code", "name"]
        onto_existing = await client.patch(
            f"{SUBJECTS}/{subject_id}", headers=admin, json={"name": "DBMS"}
        )
        missing = await client.patch(f"{SUBJECTS}/sub_nope", headers=admin, json={"code": "X"})
        assert (onto_existing.status_code, missing.status_code) == (409, 404)

        row = await _subject_row(client, admin, "Robotics II")
        assert (row["code"], row["branch"], row["status"], row["in_use"]) == (
            "RB-201",
            None,
            "ACTIVE",
            False,
        )
        listed = await client.get("/api/v1/academic/subjects", headers=admin)
        assert "Robotics II" in [s["name"] for s in listed.json()]
    assert len(await _audit("SUBJECT_CREATED")) == 1 and len(await _audit("SUBJECT_UPDATED")) == 1


@pytest.mark.anyio
async def test_a_subject_in_use_keeps_its_name_and_cannot_be_deleted():
    admin = await _token("admin_cat", "ADMIN")
    await _teacher("teacher_cat", ["DS-B"], ["Machine Learning"])
    db = mongodb.get_database()
    await db["sessions"].insert_one(
        {"session_id": "old_session", "class_code": "DS-B", "subject": "DBMS", "status": "FINALIZED"}
    )
    async with _client() as client:
        rename_assigned = await client.patch(
            f"{SUBJECTS}/sub_ml", headers=admin, json={"name": "ML Basics"}
        )
        rename_used_in_session = await client.patch(
            f"{SUBJECTS}/sub_dbms", headers=admin, json={"name": "Databases"}
        )
        delete_assigned = await client.delete(f"{SUBJECTS}/sub_ml", headers=admin)
        delete_used_in_session = await client.delete(f"{SUBJECTS}/sub_dbms", headers=admin)
        assert [
            r.status_code
            for r in (rename_assigned, rename_used_in_session, delete_assigned, delete_used_in_session)
        ] == [409, 409, 409, 409]

        # The code and branch are not what others refer to, so they stay editable.
        code = await client.patch(f"{SUBJECTS}/sub_ml", headers=admin, json={"code": "DS-301"})
        assert code.status_code == 200 and code.json()["changed"] == ["code"]
        row = await _subject_row(client, admin, "Machine Learning")
        assert row["in_use"] is True and row["usage"] == {"teachers": 1, "sessions": 0}

        created = await client.post(SUBJECTS, headers=admin, json={"name": "Unused Subject"})
        deleted = await client.delete(f"{SUBJECTS}/{created.json()['subject_id']}", headers=admin)
        assert deleted.status_code == 200
    assert await db["subjects"].count_documents({}) == 2
    assert len(await _audit("SUBJECT_DELETED")) == 1


@pytest.mark.anyio
async def test_an_archived_subject_is_hidden_from_sessions_and_assignments():
    admin = await _token("admin_cat", "ADMIN")
    teacher = await _teacher("teacher_cat", ["DS-B"], ["Machine Learning"])
    await _teacher("teacher_two", ["DS-C"])
    db = mongodb.get_database()
    async with _client() as client:
        before = await client.post(
            "/api/v1/sessions", headers=teacher, json=_session("DS-B", "Machine Learning")
        )
        assert before.status_code == 201, before.text

        archived = await client.post(f"{SUBJECTS}/sub_ml/archive", headers=admin)
        assert archived.status_code == 200 and archived.json()["status"] == "ARCHIVED"
        assert (await client.post(f"{SUBJECTS}/sub_ml/archive", headers=admin)).status_code == 409

        listed = await client.get("/api/v1/academic/subjects", headers=teacher)
        structure = await client.get("/api/v1/academic/structure", headers=admin)
        assert "Machine Learning" not in [s["name"] for s in listed.json()]
        assert "Machine Learning" not in [s["name"] for s in structure.json()["subjects"]]
        assert (await _subject_row(client, admin, "Machine Learning"))["status"] == "ARCHIVED"

        new_session = await client.post(
            "/api/v1/sessions", headers=teacher, json=_session("DS-B", "machine learning")
        )
        other_subject = await client.post(
            "/api/v1/sessions", headers=teacher, json=_session("DS-B", "DBMS")
        )
        assert (new_session.status_code, other_subject.status_code) == (400, 201)

        assign = await client.patch(
            f"{ADMIN}/teachers/teacher_two", headers=admin, json={"assigned_subjects": ["Machine Learning"]}
        )
        keeps = await client.patch(
            f"{ADMIN}/teachers/teacher_cat",
            headers=admin,
            json={"assigned_subjects": ["Machine Learning", "DBMS"]},
        )
        assert (assign.status_code, keeps.status_code) == (400, 200)

        restored = await client.post(f"{SUBJECTS}/sub_ml/unarchive", headers=admin)
        assert restored.status_code == 200
        assign_again = await client.patch(
            f"{ADMIN}/teachers/teacher_two", headers=admin, json={"assigned_subjects": ["Machine Learning"]}
        )
        assert assign_again.status_code == 200

    # The session recorded before archiving is untouched.
    assert await db["sessions"].count_documents({"subject": "Machine Learning"}) == 1
    assert len(await _audit("SUBJECT_ARCHIVED")) == 1 and len(await _audit("SUBJECT_UNARCHIVED")) == 1


# ------------------------------------------------------------------------------
# Audit and role checks
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_catalog_audit_entries_hold_codes_and_counts_only():
    admin = await _token("admin_cat", "ADMIN")
    async with _client() as client:
        await client.post("/api/v1/students/register", json=_student("CAT001"))
        await client.post(f"{CLASSES}/DS-B/archive", headers=admin)
        await client.post(SUBJECTS, headers=admin, json={"name": "Robotics", "branch": "AI & ML"})
    entries = [
        doc
        async for doc in mongodb.get_database()["audit_events"].find(
            {"resource_type": "ACADEMIC"}
        )
    ]
    assert sorted(e["action"] for e in entries) == ["CLASS_ARCHIVED", "SUBJECT_CREATED"]
    text = json.dumps([e["metadata"] for e in entries])
    assert "Catalog Student" not in text and "@" not in text and "Robotics" not in text
    assert all(e["actor_user_id"] == "admin_cat" for e in entries)


CATALOG_ROUTES = [
    ("GET", CLASSES),
    ("POST", CLASSES),
    ("PATCH", f"{CLASSES}/DS-B"),
    ("POST", f"{CLASSES}/DS-B/archive"),
    ("POST", f"{CLASSES}/DS-B/unarchive"),
    ("DELETE", f"{CLASSES}/DS-B"),
    ("GET", SUBJECTS),
    ("POST", SUBJECTS),
    ("PATCH", f"{SUBJECTS}/sub_ml"),
    ("POST", f"{SUBJECTS}/sub_ml/archive"),
    ("POST", f"{SUBJECTS}/sub_ml/unarchive"),
    ("DELETE", f"{SUBJECTS}/sub_ml"),
]


@pytest.mark.anyio
@pytest.mark.parametrize("method,path", CATALOG_ROUTES)
async def test_catalog_routes_need_an_admin(method, path):
    teacher = await _token("teacher_cat", "TEACHER")
    student = await _token("student_cat", "STUDENT")
    db = mongodb.get_database()
    before = [
        [doc async for doc in db[name].find({})] for name in ("academic_classes", "subjects")
    ]
    async with _client() as client:
        no_token = await client.request(method, path, json={})
        as_teacher = await client.request(method, path, headers=teacher, json={})
        as_student = await client.request(method, path, headers=student, json={})
    assert no_token.status_code == 401
    assert (as_teacher.status_code, as_student.status_code) == (403, 403)
    assert before == [
        [doc async for doc in db[name].find({})] for name in ("academic_classes", "subjects")
    ]
