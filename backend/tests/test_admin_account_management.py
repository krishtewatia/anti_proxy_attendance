"""Admin account management.

Accounts an administrator creates or resets must change their password at the
next login; a password change or reset invalidates every earlier token; a
student's ID can change without touching photos or attendance; a teacher is
deleted without their history; the last administrator cannot be removed.

The vision service is stubbed and photos are placeholder bytes.
"""

from datetime import datetime, timezone
import json

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.core.uploads import student_photo_path
from app.database import mongodb
from app.database.mongodb import init_indexes
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password, verify_password
from app.services import account_admin_service, approval_service, student_deletion
from app.tools import cleanup_test_accounts

PASSWORD = "FirstPassword123!"
NEW_PASSWORD = "ChosenByOwner456!"
PHOTO_B64 = "cGxhY2Vob2xkZXIgcGhvdG8gYnl0ZXM="  # placeholder bytes, not an image of anyone
ADMIN = "/api/v1/admin"


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
    refreshes = []

    async def fake_refresh() -> bool:
        refreshes.append("reload")
        return True

    for module in (student_deletion, approval_service, account_admin_service):
        monkeypatch.setattr(module, "_refresh_vision_gallery", fake_refresh)
    yield refreshes
    mongodb._client = AsyncMongoMockClient()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _token(user_id: str, role: str) -> dict[str, str]:
    await create_user(
        user_id=user_id,
        email=f"{user_id}@accounts.test",
        password_hash=hash_password(PASSWORD),
        role=role,
    )
    return {"Authorization": f"Bearer {create_access_token(user_id=user_id, role=role)}"}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _student_payload(student_id: str = "ACC001", email: str = "acc001@accounts.test") -> dict:
    return {
        "name": "Account Test Student",
        "email": email,
        "password": PASSWORD,
        "student_id": student_id,
        "roll_number": "20260001",
        "branch": "Data Science",
        "section": "B",
        "photo_base64": PHOTO_B64,
    }


def _teacher_payload(teacher_id: str = "T-ACC-1", email: str = "t.acc1@accounts.test") -> dict:
    return {
        "name": "Account Test Teacher",
        "email": email,
        "password": PASSWORD,
        "teacher_id": teacher_id,
        "department": "Data Science",
        "assigned_classes": ["DS-B"],
        "assigned_subjects": ["Machine Learning"],
    }


async def _login(client: AsyncClient, email: str, password: str = PASSWORD):
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def _change(client: AsyncClient, token: str, current: str, new: str):
    return await client.post(
        "/api/v1/auth/change-password",
        headers=_bearer(token),
        json={"current_password": current, "new_password": new},
    )


async def _audit(action: str) -> list[dict]:
    return [doc async for doc in mongodb.get_database()["audit_events"].find({"action": action})]


def _session_payload(class_code: str = "DS-B") -> dict:
    return {
        "course_name": "Account Session",
        "classroom_id": "ROOM_101",
        "start_time": "2026-10-20T09:00:00Z",
        "end_time": "2026-10-20T10:00:00Z",
        "required_presence_percentage": 75.0,
        "class_code": class_code,
    }


async def _ready_teacher(client: AsyncClient, admin: dict, **payload) -> tuple[str, dict[str, str]]:
    """A teacher the administrator created, who has already chosen their own password."""
    body = _teacher_payload(**payload)
    created = await client.post(f"{ADMIN}/teachers", headers=admin, json=body)
    assert created.status_code == 201, created.text
    first = await _login(client, body["email"])
    changed = await _change(client, first.json()["access_token"], PASSWORD, NEW_PASSWORD)
    assert changed.status_code == 200, changed.text
    return created.json()["user_id"], _bearer(changed.json()["access_token"])


# ------------------------------------------------------------------------------
# Accounts created by an administrator must change their password first
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_created_accounts_are_approved_but_must_change_password(stub_vision_embedding):
    admin = await _token("admin_acc", "ADMIN")
    async with _client() as client:
        student = await client.post(f"{ADMIN}/students", headers=admin, json=_student_payload())
        teacher = await client.post(f"{ADMIN}/teachers", headers=admin, json=_teacher_payload())
        other_admin = await client.post(
            f"{ADMIN}/admins",
            headers=admin,
            json={"name": "Second Admin", "email": "second@accounts.test", "password": PASSWORD},
        )
        assert (student.status_code, teacher.status_code, other_admin.status_code) == (201, 201, 201)

        for email, own_route in (
            ("acc001@accounts.test", "/api/v1/students/me"),
            ("t.acc1@accounts.test", "/api/v1/teachers/profile"),
            ("second@accounts.test", f"{ADMIN}/students"),
        ):
            login = await _login(client, email)
            assert login.status_code == 200, login.text
            assert login.json()["must_change_password"] is True

            blocked = await client.get(own_route, headers=_bearer(login.json()["access_token"]))
            assert blocked.status_code == 403
            assert blocked.json()["detail"]["code"] == "password_change_required"

    db = mongodb.get_database()
    for created in (student, teacher, other_admin):
        user = await db["users"].find_one({"user_id": created.json()["user_id"]})
        assert user["status"] == "APPROVED" and user["must_change_password"] is True
    assert len(await _audit("ACCOUNT_CREATED")) == 3
    assert "password" not in json.dumps(other_admin.json()).lower().replace("must_change_password", "")


@pytest.mark.anyio
async def test_changing_the_first_password_unlocks_the_account():
    admin = await _token("admin_acc", "ADMIN")
    async with _client() as client:
        await client.post(f"{ADMIN}/teachers", headers=admin, json=_teacher_payload())
        first = (await _login(client, "t.acc1@accounts.test")).json()["access_token"]

        wrong_current = await _change(client, first, "not the password", NEW_PASSWORD)
        same_again = await _change(client, first, PASSWORD, PASSWORD)
        too_short = await _change(client, first, PASSWORD, "short")
        assert (wrong_current.status_code, same_again.status_code, too_short.status_code) == (
            400,
            400,
            422,
        )

        changed = await _change(client, first, PASSWORD, NEW_PASSWORD)
        assert changed.status_code == 200, changed.text
        assert changed.json()["must_change_password"] is False

        me = await client.get(
            "/api/v1/teachers/profile", headers=_bearer(changed.json()["access_token"])
        )
        assert me.status_code == 200
        assert (await _login(client, "t.acc1@accounts.test")).status_code == 401
        again = await _login(client, "t.acc1@accounts.test", NEW_PASSWORD)
        assert again.status_code == 200 and again.json()["must_change_password"] is False

    entries = await _audit("PASSWORD_CHANGED")
    assert len(entries) == 1 and entries[0]["metadata"] == {"forced": True}


@pytest.mark.anyio
async def test_self_registered_accounts_are_not_forced_to_change_password():
    admin = await _token("admin_acc", "ADMIN")
    async with _client() as client:
        registered = await client.post("/api/v1/teachers/register", json=_teacher_payload())
        await client.post(
            f"{ADMIN}/approvals/{registered.json()['user_id']}/approve",
            headers=admin,
            json={"assigned_classes": ["DS-B"]},
        )
        login = await _login(client, "t.acc1@accounts.test")
        assert login.status_code == 200 and login.json()["must_change_password"] is False


# ------------------------------------------------------------------------------
# A password change or reset invalidates every earlier token
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_changing_a_password_invalidates_all_existing_tokens():
    admin = await _token("admin_acc", "ADMIN")
    async with _client() as client:
        _, teacher = await _ready_teacher(client, admin)
        # Two more logins: three valid tokens for the same teacher.
        second = _bearer((await _login(client, "t.acc1@accounts.test", NEW_PASSWORD)).json()["access_token"])
        third = _bearer((await _login(client, "t.acc1@accounts.test", NEW_PASSWORD)).json()["access_token"])
        for headers in (teacher, second, third):
            assert (await client.get("/api/v1/teachers/profile", headers=headers)).status_code == 200

        changed = await client.post(
            "/api/v1/auth/change-password",
            headers=second,
            json={"current_password": NEW_PASSWORD, "new_password": "AnotherOne789!"},
        )
        assert changed.status_code == 200

        for headers in (teacher, second, third):
            refused = await client.get("/api/v1/teachers/profile", headers=headers)
            assert refused.status_code == 401
        # Not even to change the password again.
        assert (await _change(client, third["Authorization"][7:], "AnotherOne789!", PASSWORD)).status_code == 401

        fresh = _bearer(changed.json()["access_token"])
        assert (await client.get("/api/v1/teachers/profile", headers=fresh)).status_code == 200


@pytest.mark.anyio
async def test_resetting_a_password_invalidates_tokens_and_forces_a_change():
    admin = await _token("admin_acc", "ADMIN")
    async with _client() as client:
        teacher_id, teacher = await _ready_teacher(client, admin)

        reset = await client.post(f"{ADMIN}/users/{teacher_id}/reset-password", headers=admin)
        assert reset.status_code == 200, reset.text
        temporary = reset.json()["temporary_password"]
        assert len(temporary) >= 12 and temporary not in (PASSWORD, NEW_PASSWORD)

        # The token from before the reset is dead; so is the old password.
        assert (await client.get("/api/v1/teachers/profile", headers=teacher)).status_code == 401
        assert (await _login(client, "t.acc1@accounts.test", NEW_PASSWORD)).status_code == 401

        login = await _login(client, "t.acc1@accounts.test", temporary)
        assert login.status_code == 200 and login.json()["must_change_password"] is True
        token = login.json()["access_token"]
        assert (await client.get("/api/v1/teachers/profile", headers=_bearer(token))).status_code == 403
        assert (await _change(client, token, temporary, "OwnersChoice321!")).status_code == 200

    db = mongodb.get_database()
    user = await db["users"].find_one({"user_id": teacher_id})
    assert verify_password("OwnersChoice321!", user["password_hash"])
    # The temporary password is not kept anywhere, and the audit entry holds no secret.
    stored = json.dumps([doc async for doc in db["users"].find({})], default=str)
    audit = json.dumps([doc async for doc in db["audit_events"].find({})], default=str)
    assert temporary not in stored and temporary not in audit
    entries = await _audit("PASSWORD_RESET")
    assert len(entries) == 1
    assert entries[0]["resource_id"] == teacher_id and entries[0]["metadata"] == {"role": "TEACHER"}


@pytest.mark.anyio
async def test_reset_is_refused_for_yourself_unknown_and_pending_accounts():
    admin = await _token("admin_acc", "ADMIN")
    async with _client() as client:
        pending = await client.post("/api/v1/teachers/register", json=_teacher_payload())
        own = await client.post(f"{ADMIN}/users/admin_acc/reset-password", headers=admin)
        unknown = await client.post(f"{ADMIN}/users/nobody/reset-password", headers=admin)
        waiting = await client.post(
            f"{ADMIN}/users/{pending.json()['user_id']}/reset-password", headers=admin
        )
    assert (own.status_code, unknown.status_code, waiting.status_code) == (400, 404, 409)


@pytest.mark.anyio
async def test_no_admin_response_contains_a_password_hash(stub_vision_embedding):
    admin = await _token("admin_acc", "ADMIN")
    async with _client() as client:
        await client.post(f"{ADMIN}/students", headers=admin, json=_student_payload())
        await client.post(f"{ADMIN}/teachers", headers=admin, json=_teacher_payload())
        bodies = [
            (await client.get(path, headers=admin)).text
            for path in (
                f"{ADMIN}/users",
                f"{ADMIN}/students",
                f"{ADMIN}/teachers",
                f"{ADMIN}/admins",
                f"{ADMIN}/approvals",
            )
        ]
    hashes = [doc["password_hash"] async for doc in mongodb.get_database()["users"].find({})]
    for body in bodies:
        assert "password_hash" not in body
        assert not any(value in body for value in hashes)


# ------------------------------------------------------------------------------
# Editing a student, including the student ID
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_editing_a_student_changes_name_email_and_class(stub_vision_embedding, fresh_db):
    admin = await _token("admin_acc", "ADMIN")
    async with _client() as client:
        created = await client.post(f"{ADMIN}/students", headers=admin, json=_student_payload())
        user_id = created.json()["user_id"]

        edited = await client.patch(
            f"{ADMIN}/students/{user_id}",
            headers=admin,
            json={
                "name": "Renamed Student",
                "email": "Renamed@Accounts.Test",
                "branch": "Data Science",
                "section": "c",
            },
        )
        assert edited.status_code == 200, edited.text
        assert sorted(edited.json()["changed"]) == ["class", "email", "name"]

        assert (await _login(client, "acc001@accounts.test")).status_code == 401
        assert (await _login(client, "renamed@accounts.test")).status_code == 200

        unknown_class = await client.patch(
            f"{ADMIN}/students/{user_id}", headers=admin, json={"branch": "History", "section": "Z"}
        )
        unknown_field = await client.patch(
            f"{ADMIN}/students/{user_id}", headers=admin, json={"role": "ADMIN"}
        )
        missing = await client.patch(f"{ADMIN}/students/nobody", headers=admin, json={"name": "No One"})
    assert (unknown_class.status_code, unknown_field.status_code, missing.status_code) == (
        400,
        422,
        404,
    )

    profile = await mongodb.get_database()["student_profiles"].find_one({"user_id": user_id})
    assert (profile["name"], profile["email"], profile["class_code"]) == (
        "Renamed Student",
        "renamed@accounts.test",
        "DS-C",
    )
    entries = await _audit("ACCOUNT_UPDATED")
    assert len(entries) == 1
    # Field names and the class code only: no name, no email address.
    assert entries[0]["metadata"] == {
        "role": "STUDENT",
        "fields": ["name", "class", "email"],
        "class_code": "DS-C",
    }
    assert "reload" in fresh_db  # the vision service shows the name


@pytest.mark.anyio
async def test_an_email_already_in_use_is_refused(stub_vision_embedding):
    admin = await _token("admin_acc", "ADMIN")
    async with _client() as client:
        first = await client.post(f"{ADMIN}/students", headers=admin, json=_student_payload())
        await client.post(f"{ADMIN}/teachers", headers=admin, json=_teacher_payload())
        clash = await client.patch(
            f"{ADMIN}/students/{first.json()['user_id']}",
            headers=admin,
            json={"email": "t.acc1@accounts.test"},
        )
    assert clash.status_code == 409
    profile = await mongodb.get_database()["student_profiles"].find_one(
        {"user_id": first.json()["user_id"]}
    )
    assert profile["email"] == "acc001@accounts.test"


@pytest.mark.anyio
async def test_changing_a_student_id_is_one_update_and_everything_follows(
    stub_vision_embedding, service_key_headers, vision_frames
):
    admin = await _token("admin_acc", "ADMIN")
    db = mongodb.get_database()
    async with _client() as client:
        created = await client.post(f"{ADMIN}/students", headers=admin, json=_student_payload())
        user_id = created.json()["user_id"]
        _, teacher = await _ready_teacher(client, admin)

        session = await client.post("/api/v1/sessions", headers=teacher, json=_session_payload())
        assert session.status_code == 201, session.text
        session_id = session.json()["session_id"]
        assert (
            await client.post(f"/api/v1/sessions/{session_id}/start", headers=teacher)
        ).status_code == 200
        vision_frames.faces = [vision_frames.recognized(session_id, "ACC001")]
        marked = await client.post(
            f"/api/v1/attendance/{session_id}/process-frame",
            headers=teacher,
            files={"frame": ("frame.jpg", b"frame bytes", "image/jpeg")},
        )
        assert marked.status_code == 200, marked.text

        before = {
            name: [doc async for doc in db[name].find({})]
            for name in ("attendance_records", "session_rosters", "biometric_profiles", "users")
        }
        photo_before = student_photo_path("ACC001").read_bytes()

        changed = await client.patch(
            f"{ADMIN}/students/{user_id}", headers=admin, json={"student_id": "ACC999"}
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["changed"] == ["student_id"]

        # Only the student record changed: photo, template, roster and attendance are untouched.
        for name, documents in before.items():
            assert [doc async for doc in db[name].find({})] == documents
        assert student_photo_path("ACC001").read_bytes() == photo_before
        assert not student_photo_path("ACC999").exists()
        profile = await db["student_profiles"].find_one({"user_id": user_id})
        assert (profile["identity"], profile["student_id"]) == ("ACC001", "ACC999")

        # Views and the export read the ID from the student record.
        listing = await client.get(f"/api/v1/attendance/{session_id}", headers=teacher)
        row = listing.json()["records"][0]
        assert (row["identity"], row["student_id"], row["status"]) == ("ACC001", "ACC999", "PRESENT")
        export = await client.get(f"/api/v1/attendance/{session_id}/export", headers=teacher)
        assert "ACC999,Account Test Student,PRESENT" in export.text
        assert "ACC001" not in export.text

        gallery = await client.get("/api/v1/attendance/vision-gallery", headers=service_key_headers)
        assert [(g["identity"], g["student_id"]) for g in gallery.json()["gallery"]] == [
            ("ACC001", "ACC999")
        ]

        # The photo is served under the new ID and under the address stored on the record.
        by_new_id = await client.get("/api/v1/students/ACC999/photo", headers=admin)
        by_stored_url = await client.get(profile["photo_url"], headers=admin)
        assert by_new_id.status_code == 200 and by_new_id.content == photo_before
        assert by_stored_url.status_code == 200 and by_stored_url.content == photo_before

        # Recognition still marks the same student.
        vision_frames.faces = [vision_frames.recognized(session_id, "ACC001")]
        again = await client.post(
            f"/api/v1/attendance/{session_id}/process-frame",
            headers=teacher,
            files={"frame": ("frame.jpg", b"frame bytes", "image/jpeg")},
        )
        assert again.status_code == 200

    entries = await _audit("STUDENT_ID_CHANGED")
    assert len(entries) == 1
    assert entries[0]["metadata"] == {"old_student_id": "ACC001", "new_student_id": "ACC999"}


@pytest.mark.anyio
async def test_a_student_id_in_use_or_unsafe_is_refused(stub_vision_embedding):
    admin = await _token("admin_acc", "ADMIN")
    async with _client() as client:
        first = await client.post(f"{ADMIN}/students", headers=admin, json=_student_payload())
        second = await client.post(
            f"{ADMIN}/students",
            headers=admin,
            json=_student_payload("ACC002", "acc002@accounts.test"),
        )
        first_id, second_id = first.json()["user_id"], second.json()["user_id"]

        taken = await client.patch(
            f"{ADMIN}/students/{second_id}", headers=admin, json={"student_id": "ACC001"}
        )
        unsafe = [
            await client.patch(
                f"{ADMIN}/students/{second_id}", headers=admin, json={"student_id": value}
            )
            for value in ("../../etc", "a/b", "..", "has space")
        ]
        assert taken.status_code == 409
        assert [response.status_code for response in unsafe] == [400, 400, 400, 400]

        # After a change the old ID stays reserved: it is still the first
        # student's internal identity, so nobody else can take it.
        moved = await client.patch(
            f"{ADMIN}/students/{first_id}", headers=admin, json={"student_id": "ACC100"}
        )
        reuse_by_edit = await client.patch(
            f"{ADMIN}/students/{second_id}", headers=admin, json={"student_id": "ACC001"}
        )
        reuse_by_registration = await client.post(
            "/api/v1/students/register", json=_student_payload("ACC001", "acc003@accounts.test")
        )
        back_again = await client.patch(
            f"{ADMIN}/students/{first_id}", headers=admin, json={"student_id": "ACC001"}
        )
    assert moved.status_code == 200
    assert (reuse_by_edit.status_code, reuse_by_registration.status_code) == (409, 409)
    assert back_again.status_code == 200


# ------------------------------------------------------------------------------
# Editing and deleting a teacher
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_editing_a_teacher_changes_profile_classes_and_email():
    admin = await _token("admin_acc", "ADMIN")
    async with _client() as client:
        first = await client.post(f"{ADMIN}/teachers", headers=admin, json=_teacher_payload())
        await client.post(
            f"{ADMIN}/teachers",
            headers=admin,
            json=_teacher_payload("T-ACC-2", "t.acc2@accounts.test"),
        )
        user_id = first.json()["user_id"]

        edited = await client.patch(
            f"{ADMIN}/teachers/{user_id}",
            headers=admin,
            json={
                "name": "Renamed Teacher",
                "email": "renamed.teacher@accounts.test",
                "teacher_id": "T-ACC-9",
                "department": "Computer Science",
                "assigned_classes": ["ds-c", "CS-A", "DS-C"],
                "assigned_subjects": ["Deep Learning", " "],
            },
        )
        assert edited.status_code == 200, edited.text

        unknown_class = await client.patch(
            f"{ADMIN}/teachers/{user_id}", headers=admin, json={"assigned_classes": ["NOPE-1"]}
        )
        taken_id = await client.patch(
            f"{ADMIN}/teachers/{user_id}", headers=admin, json={"teacher_id": "T-ACC-2"}
        )
        taken_email = await client.patch(
            f"{ADMIN}/teachers/{user_id}", headers=admin, json={"email": "t.acc2@accounts.test"}
        )
        not_a_teacher = await client.patch(
            f"{ADMIN}/teachers/admin_acc", headers=admin, json={"name": "Not A Teacher"}
        )
        assert (await _login(client, "renamed.teacher@accounts.test")).status_code == 200
    assert (
        unknown_class.status_code,
        taken_id.status_code,
        taken_email.status_code,
        not_a_teacher.status_code,
    ) == (400, 409, 409, 404)

    profile = await mongodb.get_database()["teacher_profiles"].find_one({"user_id": user_id})
    assert (profile["name"], profile["teacher_id"], profile["department"]) == (
        "Renamed Teacher",
        "T-ACC-9",
        "Computer Science",
    )
    assert profile["assigned_classes"] == ["DS-C", "CS-A"]
    assert profile["assigned_subjects"] == ["Deep Learning"]
    entries = await _audit("ACCOUNT_UPDATED")
    assert len(entries) == 1 and entries[0]["metadata"]["assigned_classes"] == ["DS-C", "CS-A"]
    assert "Renamed" not in json.dumps(entries[0]["metadata"])


@pytest.mark.anyio
async def test_a_teacher_loses_the_classes_an_admin_takes_away():
    admin = await _token("admin_acc", "ADMIN")
    async with _client() as client:
        user_id, teacher = await _ready_teacher(client, admin)
        allowed = await client.post("/api/v1/sessions", headers=teacher, json=_session_payload())
        await client.patch(
            f"{ADMIN}/teachers/{user_id}", headers=admin, json={"assigned_classes": ["DS-C"]}
        )
        refused = await client.post("/api/v1/sessions", headers=teacher, json=_session_payload())
    assert (allowed.status_code, refused.status_code) == (201, 403)


@pytest.mark.anyio
async def test_deleting_a_teacher_keeps_their_sessions_and_attendance():
    admin = await _token("admin_acc", "ADMIN")
    db = mongodb.get_database()
    async with _client() as client:
        user_id, teacher = await _ready_teacher(client, admin)
        session = await client.post("/api/v1/sessions", headers=teacher, json=_session_payload())
        session_id = session.json()["session_id"]
        await db["attendance_records"].insert_one(
            {
                "attendance_id": f"att_{session_id}_ACC001",
                "session_id": session_id,
                "identity": "ACC001",
                "status": "PRESENT",
            }
        )

        # A session in progress blocks the deletion.
        await client.post(f"/api/v1/sessions/{session_id}/start", headers=teacher)
        blocked = await client.delete(f"{ADMIN}/teachers/{user_id}", headers=admin)
        assert blocked.status_code == 409
        assert await db["users"].find_one({"user_id": user_id}) is not None

        await db["sessions"].update_one({"session_id": session_id}, {"$set": {"status": "FINALIZED"}})
        deleted = await client.delete(f"{ADMIN}/teachers/{user_id}", headers=admin)
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["sessions_kept"] == 1

        assert (await client.get("/api/v1/teachers/profile", headers=teacher)).status_code == 401
        assert (await _login(client, "t.acc1@accounts.test", NEW_PASSWORD)).status_code == 401
        gone = await client.delete(f"{ADMIN}/teachers/{user_id}", headers=admin)
        assert gone.status_code == 404

    assert await db["users"].find_one({"user_id": user_id}) is None
    assert await db["teacher_profiles"].find_one({"user_id": user_id}) is None
    assert await db["sessions"].count_documents({"session_id": session_id}) == 1
    assert await db["attendance_records"].count_documents({"session_id": session_id}) == 1
    entries = await _audit("TEACHER_DELETED")
    assert len(entries) == 1 and entries[0]["metadata"]["sessions_kept"] == 1


@pytest.mark.anyio
async def test_the_teacher_delete_route_does_not_delete_other_roles(stub_vision_embedding):
    admin = await _token("admin_acc", "ADMIN")
    async with _client() as client:
        student = await client.post(f"{ADMIN}/students", headers=admin, json=_student_payload())
        as_student = await client.delete(
            f"{ADMIN}/teachers/{student.json()['user_id']}", headers=admin
        )
        as_admin = await client.delete(f"{ADMIN}/teachers/admin_acc", headers=admin)
    assert (as_student.status_code, as_admin.status_code) == (400, 400)
    assert await mongodb.get_database()["users"].count_documents({}) == 2


# ------------------------------------------------------------------------------
# Administrators
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admins_can_be_created_listed_and_deleted_with_protections():
    admin = await _token("admin_acc", "ADMIN")
    db = mongodb.get_database()
    async with _client() as client:
        # The only administrator cannot be removed, by themself or otherwise.
        own = await client.delete(f"{ADMIN}/admins/admin_acc", headers=admin)
        assert own.status_code == 409

        created = await client.post(
            f"{ADMIN}/admins",
            headers=admin,
            json={"name": "Second Admin", "email": "second@accounts.test", "password": PASSWORD},
        )
        assert created.status_code == 201, created.text
        second_id = created.json()["user_id"]

        duplicate = await client.post(
            f"{ADMIN}/admins",
            headers=admin,
            json={"name": "Second Admin", "email": "SECOND@accounts.test", "password": PASSWORD},
        )
        weak = await client.post(
            f"{ADMIN}/admins",
            headers=admin,
            json={"name": "Weak Admin", "email": "weak@accounts.test", "password": "short"},
        )
        assert (duplicate.status_code, weak.status_code) == (409, 422)

        listed = await client.get(f"{ADMIN}/admins", headers=admin)
        assert sorted(a["email"] for a in listed.json()) == [
            "admin_acc@accounts.test",
            "second@accounts.test",
        ]

        still_own = await client.delete(f"{ADMIN}/admins/admin_acc", headers=admin)
        not_an_admin = await client.delete(f"{ADMIN}/admins/nobody", headers=admin)
        assert (still_own.status_code, not_an_admin.status_code) == (409, 404)

        deleted = await client.delete(f"{ADMIN}/admins/{second_id}", headers=admin)
        assert deleted.status_code == 200
    assert await db["users"].count_documents({"role": "ADMIN"}) == 1
    assert len(await _audit("ADMIN_DELETED")) == 1


@pytest.mark.anyio
async def test_the_last_administrator_cannot_be_deleted_even_by_a_stale_caller():
    """The caller's own account is gone, their token is refused: no path removes the last admin."""
    first = await _token("admin_one", "ADMIN")
    second = await _token("admin_two", "ADMIN")
    db = mongodb.get_database()
    async with _client() as client:
        assert (await client.delete(f"{ADMIN}/admins/admin_two", headers=first)).status_code == 200
        refused = await client.delete(f"{ADMIN}/admins/admin_one", headers=second)
    assert refused.status_code == 401
    assert await db["users"].count_documents({"role": "ADMIN"}) == 1


@pytest.mark.anyio
async def test_there_is_no_route_that_changes_a_role():
    admin = await _token("admin_acc", "ADMIN")
    async with _client() as client:
        created = await client.post(f"{ADMIN}/teachers", headers=admin, json=_teacher_payload())
        attempt = await client.patch(
            f"{ADMIN}/teachers/{created.json()['user_id']}", headers=admin, json={"role": "ADMIN"}
        )
    assert attempt.status_code == 422
    user = await mongodb.get_database()["users"].find_one({"user_id": created.json()["user_id"]})
    assert user["role"] == "TEACHER"


# ------------------------------------------------------------------------------
# Role checks on every account-management route
# ------------------------------------------------------------------------------

ACCOUNT_ROUTES = [
    ("PATCH", f"{ADMIN}/students/some_user"),
    ("PATCH", f"{ADMIN}/teachers/some_user"),
    ("POST", f"{ADMIN}/users/some_user/reset-password"),
    ("GET", f"{ADMIN}/admins"),
    ("POST", f"{ADMIN}/admins"),
    ("DELETE", f"{ADMIN}/admins/some_user"),
    ("POST", f"{ADMIN}/students"),
    ("POST", f"{ADMIN}/teachers"),
    ("DELETE", f"{ADMIN}/students/some_user"),
    ("DELETE", f"{ADMIN}/teachers/some_user"),
]


@pytest.mark.anyio
@pytest.mark.parametrize("method,path", ACCOUNT_ROUTES)
async def test_account_routes_need_an_admin(method, path):
    teacher = await _token("teacher_acc", "TEACHER")
    student = await _token("student_acc", "STUDENT")
    async with _client() as client:
        no_token = await client.request(method, path, json={})
        as_teacher = await client.request(method, path, headers=teacher, json={})
        as_student = await client.request(method, path, headers=student, json={})
    assert no_token.status_code == 401
    assert (as_teacher.status_code, as_student.status_code) == (403, 403)


@pytest.mark.anyio
async def test_change_password_needs_a_token():
    async with _client() as client:
        response = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_a_token_from_before_token_versions_still_works_until_the_password_changes():
    """Tokens issued before this change carry no version; they match a user who has none."""
    import jwt

    from app.security.config import JWT_ALGORITHM, JWT_SECRET_KEY

    await _token("teacher_old", "TEACHER")
    old_token = jwt.encode(
        {"sub": "teacher_old", "role": "TEACHER", "exp": datetime(2099, 1, 1, tzinfo=timezone.utc)},
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )
    async with _client() as client:
        assert (await client.get("/api/v1/teachers/profile", headers=_bearer(old_token))).status_code == 200
        assert (await _change(client, old_token, PASSWORD, NEW_PASSWORD)).status_code == 200
        assert (await client.get("/api/v1/teachers/profile", headers=_bearer(old_token))).status_code == 401


# ------------------------------------------------------------------------------
# Test-debris clean-up command
# ------------------------------------------------------------------------------


async def _debris(db) -> None:
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)

    async def user(user_id, role, email):
        await db["users"].insert_one(
            {"user_id": user_id, "email": email, "role": role, "status": "APPROVED",
             "is_active": True, "password_hash": "x", "created_at": now}
        )

    await user("orphan_student", "STUDENT", "someone@example.test")
    await user("orphan_teacher", "TEACHER", "teacher_1759912345678@university.edu")
    await user("real_student", "STUDENT", "real@example.test")
    await user("real_teacher", "TEACHER", "real.teacher@example.test")
    await user("junk_teacher", "TEACHER", "t_1759912345999@test.edu")
    await user("junk_student", "STUDENT", "student1_id_1759912346000@test.edu")
    await user("the_admin", "ADMIN", "admin_1759912345678@test.edu")

    await db["student_profiles"].insert_many(
        [
            {"user_id": "real_student", "identity": "REAL1", "student_id": "REAL1"},
            {"user_id": "junk_student", "identity": "JUNK1", "student_id": "JUNK1"},
        ]
    )
    await db["teacher_profiles"].insert_many(
        [{"user_id": "real_teacher", "teacher_id": "T1"}, {"user_id": "junk_teacher", "teacher_id": "T2"}]
    )
    await db["sessions"].insert_many(
        [
            {"session_id": "real_session", "created_by": "real_teacher", "status": "FINALIZED"},
            {"session_id": "junk_session", "created_by": "junk_teacher", "status": "FINALIZED"},
        ]
    )
    await db["session_rosters"].insert_many(
        [
            {"session_id": "real_session", "identities": ["REAL1", "JUNK1"]},
            {"session_id": "junk_session", "identities": ["REAL1"]},
        ]
    )
    await db["attendance_records"].insert_many(
        [
            {"session_id": "real_session", "identity": "REAL1", "status": "PRESENT"},
            {"session_id": "real_session", "identity": "JUNK1", "status": "ABSENT"},
            {"session_id": "junk_session", "identity": "REAL1", "status": "PRESENT"},
        ]
    )


@pytest.mark.anyio
async def test_cleanup_dry_run_lists_and_deletes_nothing(capsys):
    db = mongodb.get_database()
    await _debris(db)
    before = {name: await db[name].count_documents({}) for name in await db.list_collection_names()}

    default_rule = await cleanup_test_accounts.find_candidates(db)
    wider_rule = await cleanup_test_accounts.find_candidates(db, include_test_pattern=True)
    assert sorted(c["user_id"] for c in default_rule) == ["orphan_student", "orphan_teacher"]
    assert sorted(c["user_id"] for c in wider_rule) == [
        "junk_student",
        "junk_teacher",
        "orphan_student",
        "orphan_teacher",
    ]

    exit_code = await cleanup_test_accounts._run(
        cleanup_test_accounts.argparse.Namespace(include_test_pattern=True, apply=False, expect=-1)
    )
    assert exit_code == 0
    assert "Dry run: nothing was deleted" in capsys.readouterr().out
    assert before == {
        name: await db[name].count_documents({}) for name in await db.list_collection_names()
    }


@pytest.mark.anyio
async def test_cleanup_refuses_to_apply_when_the_list_changed(capsys):
    db = mongodb.get_database()
    await _debris(db)
    exit_code = await cleanup_test_accounts._run(
        cleanup_test_accounts.argparse.Namespace(include_test_pattern=False, apply=True, expect=5)
    )
    assert exit_code == 2
    assert "Nothing was deleted" in capsys.readouterr().out
    assert await db["users"].count_documents({}) == 7


@pytest.mark.anyio
async def test_cleanup_apply_removes_only_the_listed_accounts_and_audits_each():
    db = mongodb.get_database()
    await _debris(db)
    exit_code = await cleanup_test_accounts._run(
        cleanup_test_accounts.argparse.Namespace(include_test_pattern=True, apply=True, expect=4)
    )
    assert exit_code == 0

    # Real accounts, the administrator and the real session are untouched.
    assert sorted([u["user_id"] async for u in db["users"].find({})]) == [
        "real_student",
        "real_teacher",
        "the_admin",
    ]
    assert [s["session_id"] async for s in db["sessions"].find({})] == ["real_session"]
    assert await db["attendance_records"].count_documents({}) == 1
    roster = await db["session_rosters"].find_one({"session_id": "real_session"})
    assert roster["identities"] == ["REAL1"]
    assert await db["session_rosters"].count_documents({}) == 1

    entries = await _audit("TEST_ACCOUNT_REMOVED")
    assert sorted(e["resource_id"] for e in entries) == [
        "junk_student",
        "junk_teacher",
        "orphan_student",
        "orphan_teacher",
    ]
    assert "@" not in json.dumps([e["metadata"] for e in entries])
