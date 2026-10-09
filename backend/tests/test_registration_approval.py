"""Registration approval.

Every public registration is PENDING until an administrator approves it. A
pending account cannot log in, a pending student's face is not recognizable,
and a teacher can create sessions only for classes an administrator assigned.
Rejecting removes everything the registration created.

The vision service is stubbed and photos are placeholder bytes.
"""

from datetime import datetime, timedelta, timezone
import json

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.core.uploads import pending_photo_path, student_photo_path
from app.database import mongodb
from app.database.mongodb import init_indexes
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from app.services import approval_service, student_deletion
from app.services.account_bootstrap import bootstrap_first_admin, migrate_account_status
from app.services.approval_service import purge_stale_registrations

PASSWORD = "RegistrationPass123!"
PHOTO_B64 = "cGxhY2Vob2xkZXIgcGhvdG8gYnl0ZXM="  # placeholder bytes, not an image of anyone
APPROVALS = "/api/v1/admin/approvals"


@pytest.fixture(autouse=True)
async def fresh_db(monkeypatch):
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await init_indexes(db)
    for code, branch, section in (("DS-B", "Data Science", "B"), ("DS-C", "Data Science", "C"), ("CS-A", "Computer Science", "A")):
        await db["academic_classes"].insert_one(
            {"class_id": code, "class_code": code, "branch": branch, "section": section}
        )
    refreshes = []

    async def fake_refresh() -> bool:
        refreshes.append("reload")
        return True

    monkeypatch.setattr(student_deletion, "_refresh_vision_gallery", fake_refresh)
    monkeypatch.setattr(approval_service, "_refresh_vision_gallery", fake_refresh)
    yield refreshes
    mongodb._client = AsyncMongoMockClient()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _token(user_id: str, role: str) -> dict[str, str]:
    await create_user(
        user_id=user_id,
        email=f"{user_id}@approval.test",
        password_hash=hash_password(PASSWORD),
        role=role,
    )
    return {"Authorization": f"Bearer {create_access_token(user_id=user_id, role=role)}"}


def _student_payload(student_id: str = "APR001", email: str = "apr001@approval.test") -> dict:
    return {
        "name": "Approval Test Student",
        "email": email,
        "password": PASSWORD,
        "student_id": student_id,
        "roll_number": "20260001",
        "branch": "Data Science",
        "section": "B",
        "photo_base64": PHOTO_B64,
    }


def _teacher_payload(teacher_id: str = "T-APR-1", email: str = "t.apr1@approval.test") -> dict:
    return {
        "name": "Approval Test Teacher",
        "email": email,
        "password": PASSWORD,
        "teacher_id": teacher_id,
        "department": "Data Science",
        "assigned_classes": ["DS-B", "DS-C", "CS-A"],
        "assigned_subjects": ["Machine Learning"],
    }


async def _login(client: AsyncClient, email: str, password: str = PASSWORD):
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def _gallery_identities(client: AsyncClient, service_key_headers) -> list[str]:
    response = await client.get("/api/v1/attendance/vision-gallery", headers=service_key_headers)
    assert response.status_code == 200
    return sorted(item["identity"] for item in response.json()["gallery"])


def _session_payload(class_code: str | None) -> dict:
    payload = {
        "course_name": "Approval Session",
        "classroom_id": "ROOM_101",
        "start_time": "2026-10-20T09:00:00Z",
        "end_time": "2026-10-20T10:00:00Z",
        "required_presence_percentage": 75.0,
    }
    if class_code is not None:
        payload["class_code"] = class_code
    return payload


# ------------------------------------------------------------------------------
# Registration creates a pending account that cannot be used
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_all_three_public_registration_routes_create_pending_accounts(stub_vision_embedding):
    async with _client() as client:
        student = await client.post("/api/v1/students/register", json=_student_payload())
        teacher = await client.post("/api/v1/teachers/register", json=_teacher_payload())
        bare = await client.post(
            "/api/v1/auth/register",
            json={"email": "bare@approval.test", "password": PASSWORD, "role": "TEACHER"},
        )
    assert (student.status_code, teacher.status_code, bare.status_code) == (201, 201, 201)

    db = mongodb.get_database()
    statuses = {u["email"]: u["status"] async for u in db["users"].find({})}
    assert statuses == {
        "apr001@approval.test": "PENDING",
        "t.apr1@approval.test": "PENDING",
        "bare@approval.test": "PENDING",
    }


@pytest.mark.anyio
async def test_pending_account_cannot_log_in_and_is_told_why(stub_vision_embedding):
    async with _client() as client:
        await client.post("/api/v1/students/register", json=_student_payload())
        correct = await _login(client, "apr001@approval.test")
        wrong = await _login(client, "apr001@approval.test", "not-the-password")
        unknown = await _login(client, "nobody@approval.test")

    assert correct.status_code == 403
    assert correct.json()["detail"]["code"] == "account_pending"
    assert "awaiting admin approval" in correct.json()["detail"]["message"]
    assert "access_token" not in correct.text
    # The message appears only after the right password, so it cannot be used
    # to find out whether an email is registered.
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


@pytest.mark.anyio
async def test_a_token_for_a_pending_account_is_refused(stub_vision_embedding):
    async with _client() as client:
        registered = await client.post("/api/v1/teachers/register", json=_teacher_payload())
        user_id = registered.json()["user_id"]
        forged = {"Authorization": f"Bearer {create_access_token(user_id=user_id, role='TEACHER')}"}
        response = await client.get("/api/v1/sessions", headers=forged)
    assert response.status_code == 401


@pytest.mark.anyio
async def test_pending_student_is_not_recognizable_or_listed_anywhere(
    stub_vision_embedding, service_key_headers
):
    admin = await _token("admin_apr", "ADMIN")
    teacher = await _token("teacher_apr", "TEACHER")
    async with _client() as client:
        await client.post("/api/v1/students/register", json=_student_payload())

        assert await _gallery_identities(client, service_key_headers) == []
        class_list = await client.get("/api/v1/academic/classes/DS-B/students", headers=teacher)
        directory = await client.get("/api/v1/students/directory", headers=teacher)
        admin_list = await client.get("/api/v1/admin/students", headers=admin)

    assert class_list.json() == []
    assert "APR001" not in json.dumps(directory.json())
    assert admin_list.json() == []
    # The photo and template are held for the administrator's review
    template = await mongodb.get_database()["biometric_profiles"].find_one({"identity": "APR001"})
    assert template["review_status"] == "PENDING_REVIEW"
    assert student_photo_path("APR001").is_file()


@pytest.mark.anyio
async def test_pending_student_is_not_put_on_a_new_session_roster(stub_vision_embedding):
    from tests.conftest import assign_teacher_classes

    teacher = await _token("teacher_apr", "TEACHER")
    await assign_teacher_classes("teacher_apr", ("DS-B",))
    async with _client() as client:
        await client.post("/api/v1/students/register", json=_student_payload())
        created = await client.post("/api/v1/sessions", headers=teacher, json=_session_payload("DS-B"))
    assert created.status_code == 201
    roster = await mongodb.get_database()["session_rosters"].find_one(
        {"session_id": created.json()["session_id"]}
    )
    assert roster is None or "APR001" not in roster["identities"]


# ------------------------------------------------------------------------------
# Approving
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_pending_list_shows_each_kind_with_counts(stub_vision_embedding):
    admin = await _token("admin_apr", "ADMIN")
    async with _client() as client:
        await client.post("/api/v1/students/register", json=_student_payload())
        await client.post("/api/v1/teachers/register", json=_teacher_payload())
        listing = await client.get(APPROVALS, headers=admin)
        count = await client.get(f"{APPROVALS}/count", headers=admin)

    body = listing.json()
    assert body["counts"] == {"students": 1, "teachers": 1, "accounts": 0, "photo_changes": 0, "total": 2}
    assert count.json() == body["counts"]
    assert body["students"][0]["student_id"] == "APR001"
    assert body["students"][0]["class_code"] == "DS-B"
    assert body["teachers"][0]["requested_classes"] == ["DS-B", "DS-C", "CS-A"]
    assert "password" not in listing.text and "embedding" not in listing.text


@pytest.mark.anyio
async def test_approving_a_student_lets_them_log_in_and_makes_the_face_recognizable(
    fresh_db, stub_vision_embedding, service_key_headers
):
    admin = await _token("admin_apr", "ADMIN")
    async with _client() as client:
        registered = await client.post("/api/v1/students/register", json=_student_payload())
        user_id = registered.json()["user_id"]

        approved = await client.post(
            f"{APPROVALS}/{user_id}/approve", headers=admin, json={"branch": "Data Science", "section": "C"}
        )
        login = await _login(client, "apr001@approval.test")
        gallery = await _gallery_identities(client, service_key_headers)

    assert approved.status_code == 200, approved.text
    assert approved.json()["class_code"] == "DS-C"  # the administrator corrected the class
    assert login.status_code == 200
    assert gallery == ["APR001"]
    assert fresh_db == ["reload"]
    db = mongodb.get_database()
    assert (await db["student_profiles"].find_one({"student_id": "APR001"}))["class_code"] == "DS-C"
    assert (await db["biometric_profiles"].find_one({"identity": "APR001"}))["review_status"] == "ACTIVE"
    user = await db["users"].find_one({"user_id": user_id})
    assert user["status"] == "APPROVED" and user["approved_by"] == "admin_apr"


@pytest.mark.anyio
async def test_approving_a_teacher_requires_and_sets_assigned_classes():
    admin = await _token("admin_apr", "ADMIN")
    async with _client() as client:
        registered = await client.post("/api/v1/teachers/register", json=_teacher_payload())
        user_id = registered.json()["user_id"]
        # What the form asked for is only a request: nothing is assigned yet
        assert registered.json()["assigned_classes"] == []

        without = await client.post(f"{APPROVALS}/{user_id}/approve", headers=admin, json={})
        empty = await client.post(
            f"{APPROVALS}/{user_id}/approve", headers=admin, json={"assigned_classes": []}
        )
        unknown = await client.post(
            f"{APPROVALS}/{user_id}/approve", headers=admin, json={"assigned_classes": ["NOPE-Z"]}
        )
        assert (await _login(client, "t.apr1@approval.test")).status_code == 403

        approved = await client.post(
            f"{APPROVALS}/{user_id}/approve",
            headers=admin,
            json={"assigned_classes": ["ds-b"], "assigned_subjects": ["Machine Learning"]},
        )
        login = await _login(client, "t.apr1@approval.test")

    assert (without.status_code, empty.status_code, unknown.status_code) == (400, 400, 400)
    assert approved.status_code == 200 and login.status_code == 200
    profile = await mongodb.get_database()["teacher_profiles"].find_one({"user_id": user_id})
    assert profile["assigned_classes"] == ["DS-B"]
    assert "requested_classes" not in profile


@pytest.mark.anyio
async def test_a_teacher_registered_without_a_profile_gets_one_when_approved():
    admin = await _token("admin_apr", "ADMIN")
    async with _client() as client:
        bare = await client.post(
            "/api/v1/auth/register",
            json={"email": "bare.teacher@approval.test", "password": PASSWORD, "role": "TEACHER"},
        )
        user_id = bare.json()["user_id"]
        listing = await client.get(APPROVALS, headers=admin)
        approved = await client.post(
            f"{APPROVALS}/{user_id}/approve", headers=admin, json={"assigned_classes": ["DS-B"]}
        )
        login = await _login(client, "bare.teacher@approval.test")
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        own = await client.post("/api/v1/sessions", headers=headers, json=_session_payload("DS-B"))
        other = await client.post("/api/v1/sessions", headers=headers, json=_session_payload("CS-A"))

    assert listing.json()["counts"]["accounts"] == 1
    assert approved.status_code == 200
    assert (own.status_code, other.status_code) == (201, 403)


@pytest.mark.anyio
async def test_approving_twice_or_an_unknown_registration_fails():
    admin = await _token("admin_apr", "ADMIN")
    async with _client() as client:
        registered = await client.post("/api/v1/teachers/register", json=_teacher_payload())
        user_id = registered.json()["user_id"]
        body = {"assigned_classes": ["DS-B"]}
        first = await client.post(f"{APPROVALS}/{user_id}/approve", headers=admin, json=body)
        second = await client.post(f"{APPROVALS}/{user_id}/approve", headers=admin, json=body)
        reject_approved = await client.post(f"{APPROVALS}/{user_id}/reject", headers=admin)
        missing = await client.post(f"{APPROVALS}/user_nope/approve", headers=admin, json=body)
    assert (first.status_code, second.status_code, reject_approved.status_code, missing.status_code) == (
        200,
        409,
        409,
        404,
    )
    # An approved account can never be removed through "reject"
    assert await mongodb.get_database()["users"].count_documents({"user_id": user_id}) == 1


# ------------------------------------------------------------------------------
# Rejecting
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_rejecting_a_student_removes_everything_and_they_can_register_again(
    stub_vision_embedding, service_key_headers
):
    admin = await _token("admin_apr", "ADMIN")
    async with _client() as client:
        registered = await client.post("/api/v1/students/register", json=_student_payload())
        user_id = registered.json()["user_id"]
        rejected = await client.post(f"{APPROVALS}/{user_id}/reject", headers=admin)
        login = await _login(client, "apr001@approval.test")
        again = await client.post("/api/v1/students/register", json=_student_payload())

    assert rejected.status_code == 200
    assert rejected.json()["removed"]["photo_files_deleted"] == 1
    assert rejected.json()["removed"]["face_templates_deleted"] == 1
    assert login.status_code == 401  # no stub is kept: the account simply does not exist
    assert again.status_code == 201

    db = mongodb.get_database()
    events = [e async for e in db["audit_events"].find({"action": "REGISTRATION_REJECTED"})]
    assert len(events) == 1
    assert events[0]["resource_id"] == user_id and events[0]["actor_user_id"] == "admin_apr"
    serialized = json.dumps({k: v for k, v in events[0].items() if k != "_id"}, default=str)
    for personal in ("Approval Test Student", "apr001@approval.test", PHOTO_B64):
        assert personal not in serialized


@pytest.mark.anyio
async def test_rejecting_a_teacher_removes_the_account_and_profile():
    admin = await _token("admin_apr", "ADMIN")
    async with _client() as client:
        registered = await client.post("/api/v1/teachers/register", json=_teacher_payload())
        user_id = registered.json()["user_id"]
        rejected = await client.post(f"{APPROVALS}/{user_id}/reject", headers=admin)
    assert rejected.status_code == 200
    db = mongodb.get_database()
    assert await db["users"].count_documents({"user_id": user_id}) == 0
    assert await db["teacher_profiles"].count_documents({"user_id": user_id}) == 0
    event = await db["audit_events"].find_one({"action": "REGISTRATION_REJECTED"})
    assert "t.apr1@approval.test" not in json.dumps(event["metadata"], default=str)


@pytest.mark.anyio
async def test_registrations_pending_for_more_than_14_days_are_purged(stub_vision_embedding):
    async with _client() as client:
        old = await client.post("/api/v1/students/register", json=_student_payload("OLD001", "old@approval.test"))
        recent = await client.post(
            "/api/v1/students/register", json=_student_payload("NEW001", "new@approval.test")
        )
    db = mongodb.get_database()
    now = datetime.now(timezone.utc)
    await db["users"].update_one(
        {"user_id": old.json()["user_id"]}, {"$set": {"created_at": now - timedelta(days=15)}}
    )
    await db["users"].update_one(
        {"user_id": recent.json()["user_id"]}, {"$set": {"created_at": now - timedelta(days=13)}}
    )
    approved_long_ago = "approved_old"
    await create_user(
        user_id=approved_long_ago, email="approved@approval.test", password_hash="x", role="TEACHER"
    )
    await db["users"].update_one(
        {"user_id": approved_long_ago}, {"$set": {"created_at": now - timedelta(days=400)}}
    )

    purged = await purge_stale_registrations(db)

    assert purged == [old.json()["user_id"]]
    assert await db["users"].count_documents({"user_id": old.json()["user_id"]}) == 0
    assert await db["biometric_profiles"].count_documents({"identity": "OLD001"}) == 0
    assert not student_photo_path("OLD001").exists()
    assert await db["users"].count_documents({"user_id": recent.json()["user_id"]}) == 1
    assert await db["users"].count_documents({"user_id": approved_long_ago}) == 1
    event = await db["audit_events"].find_one({"action": "REGISTRATION_REJECTED"})
    assert event["actor_role"] == "SYSTEM"
    assert event["metadata"]["reason"] == "pending_longer_than_14_days"
    assert await purge_stale_registrations(db) == []


# ------------------------------------------------------------------------------
# Teachers create sessions only for their assigned classes (security gap 6.1)
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_teacher_can_create_sessions_only_for_assigned_classes():
    from tests.conftest import assign_teacher_classes

    admin = await _token("admin_apr", "ADMIN")
    assigned = await _token("teacher_assigned", "TEACHER")
    unassigned = await _token("teacher_unassigned", "TEACHER")
    await assign_teacher_classes("teacher_assigned", ("DS-B",))

    async with _client() as client:
        own = await client.post("/api/v1/sessions", headers=assigned, json=_session_payload("ds-b"))
        other = await client.post("/api/v1/sessions", headers=assigned, json=_session_payload("CS-A"))
        none_given = await client.post("/api/v1/sessions", headers=assigned, json=_session_payload(None))
        no_classes = await client.post("/api/v1/sessions", headers=unassigned, json=_session_payload("DS-B"))
        no_classes_none = await client.post(
            "/api/v1/sessions", headers=unassigned, json=_session_payload(None)
        )
        admin_any = await client.post("/api/v1/admin/sessions", headers=admin, json=_session_payload("CS-A"))

    assert own.status_code == 201
    assert (other.status_code, none_given.status_code) == (403, 403)
    assert (no_classes.status_code, no_classes_none.status_code) == (403, 403)
    assert admin_any.status_code == 201
    assert await mongodb.get_database()["sessions"].count_documents({"created_by": "teacher_unassigned"}) == 0


@pytest.mark.anyio
async def test_a_self_registered_teacher_cannot_reach_another_classes_students(stub_vision_embedding):
    """The whole path of gap 6.1: register, then try to get at a class."""
    admin = await _token("admin_apr", "ADMIN")
    async with _client() as client:
        student = await client.post("/api/v1/students/register", json=_student_payload())
        await client.post(
            f"{APPROVALS}/{student.json()['user_id']}/approve", headers=admin, json={}
        )
        teacher = await client.post("/api/v1/teachers/register", json=_teacher_payload())
        teacher_id = teacher.json()["user_id"]

        # Not approved: cannot log in at all
        assert (await _login(client, "t.apr1@approval.test")).status_code == 403

        # Approved for CS-A only, although the form asked for DS-B as well
        await client.post(
            f"{APPROVALS}/{teacher_id}/approve", headers=admin, json={"assigned_classes": ["CS-A"]}
        )
        login = await _login(client, "t.apr1@approval.test")
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        session_other_class = await client.post(
            "/api/v1/sessions", headers=headers, json=_session_payload("DS-B")
        )
        own = await client.post("/api/v1/sessions", headers=headers, json=_session_payload("CS-A"))
        add_to_roster = await client.put(
            f"/api/v1/sessions/{own.json()['session_id']}/roster",
            headers=headers,
            json={"identities": ["APR001"]},
        )
        photo = await client.get("/api/v1/students/APR001/photo", headers=headers)

    assert session_other_class.status_code == 403
    assert own.status_code == 201
    assert add_to_roster.status_code == 403
    assert photo.status_code == 403


@pytest.mark.anyio
async def test_roster_edit_still_accepts_own_class_students_and_plain_identities(stub_vision_embedding):
    from tests.conftest import assign_teacher_classes

    admin = await _token("admin_apr", "ADMIN")
    teacher = await _token("teacher_apr", "TEACHER")
    await assign_teacher_classes("teacher_apr", ("DS-B",))
    async with _client() as client:
        student = await client.post("/api/v1/students/register", json=_student_payload())
        await client.post(f"{APPROVALS}/{student.json()['user_id']}/approve", headers=admin, json={})
        session = await client.post("/api/v1/sessions", headers=teacher, json=_session_payload("DS-B"))
        updated = await client.put(
            f"/api/v1/sessions/{session.json()['session_id']}/roster",
            headers=teacher,
            json={"identities": ["APR001", "doorway_identity_without_a_record"]},
        )
    assert updated.status_code == 200
    assert sorted(updated.json()["identities"]) == ["APR001", "doorway_identity_without_a_record"]


# ------------------------------------------------------------------------------
# Photo changes are reviewed
# ------------------------------------------------------------------------------


async def _approved_student(client: AsyncClient, admin: dict) -> dict[str, str]:
    registered = await client.post("/api/v1/students/register", json=_student_payload())
    await client.post(f"{APPROVALS}/{registered.json()['user_id']}/approve", headers=admin, json={})
    login = await _login(client, "apr001@approval.test")
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.anyio
async def test_a_new_photo_does_not_replace_the_face_in_use_until_approved(
    fresh_db, stub_vision_embedding, monkeypatch
):
    admin = await _token("admin_apr", "ADMIN")
    db = mongodb.get_database()
    async with _client() as client:
        student = await _approved_student(client, admin)
        original_photo = student_photo_path("APR001").read_bytes()
        await db["biometric_profiles"].update_one(
            {"identity": "APR001"}, {"$set": {"mean_embedding": [0.5] * 512}}
        )
        fresh_db.clear()

        new_photo = "bmV3IHBob3RvIGJ5dGVz"  # "new photo bytes"
        uploaded = await client.post(
            "/api/v1/students/photo", headers=student, json={"photo_base64": new_photo}
        )
        pending = await client.get(APPROVALS, headers=admin)
        image = await client.get(f"{APPROVALS}/photos/APR001/image", headers=admin)
        image_as_student = await client.get(f"{APPROVALS}/photos/APR001/image", headers=student)

        assert uploaded.status_code == 200 and uploaded.json()["status"] == "pending_review"
        # Nothing in use has changed
        assert student_photo_path("APR001").read_bytes() == original_photo
        template = await db["biometric_profiles"].find_one({"identity": "APR001"})
        assert template["mean_embedding"] == [0.5] * 512 and template["review_status"] == "ACTIVE"
        assert fresh_db == []
        assert pending.json()["counts"]["photo_changes"] == 1
        assert image.status_code == 200 and image.content == b"new photo bytes"
        assert image_as_student.status_code == 403

        approved = await client.post(f"{APPROVALS}/photos/APR001/approve", headers=admin)

    assert approved.status_code == 200
    assert student_photo_path("APR001").read_bytes() == b"new photo bytes"
    assert not pending_photo_path("APR001").exists()
    template = await db["biometric_profiles"].find_one({"identity": "APR001"})
    assert template["mean_embedding"] != [0.5] * 512 and template["review_status"] == "ACTIVE"
    assert await db["photo_change_requests"].count_documents({}) == 0
    assert fresh_db == ["reload"]
    assert await db["audit_events"].count_documents({"action": "PHOTO_CHANGE_APPROVED"}) == 1


@pytest.mark.anyio
async def test_rejecting_a_photo_change_keeps_the_old_face_and_discards_the_new(stub_vision_embedding):
    admin = await _token("admin_apr", "ADMIN")
    db = mongodb.get_database()
    async with _client() as client:
        student = await _approved_student(client, admin)
        original_photo = student_photo_path("APR001").read_bytes()
        original_template = (await db["biometric_profiles"].find_one({"identity": "APR001"}))["mean_embedding"]
        await client.post("/api/v1/students/photo", headers=student, json={"photo_base64": "bmV3IHBob3Rv"})
        rejected = await client.post(f"{APPROVALS}/photos/APR001/reject", headers=admin)
        again = await client.post(f"{APPROVALS}/photos/APR001/reject", headers=admin)

    assert (rejected.status_code, again.status_code) == (200, 404)
    assert student_photo_path("APR001").read_bytes() == original_photo
    assert not pending_photo_path("APR001").exists()
    assert (await db["biometric_profiles"].find_one({"identity": "APR001"}))["mean_embedding"] == original_template
    assert await db["photo_change_requests"].count_documents({}) == 0
    assert await db["audit_events"].count_documents({"action": "PHOTO_CHANGE_REJECTED"}) == 1


# ------------------------------------------------------------------------------
# Only administrators review
# ------------------------------------------------------------------------------

REVIEW_ROUTES = [
    ("GET", APPROVALS),
    ("GET", f"{APPROVALS}/count"),
    ("POST", f"{APPROVALS}/some_user/approve"),
    ("POST", f"{APPROVALS}/some_user/reject"),
    ("GET", f"{APPROVALS}/photos/SOMEONE/image"),
    ("POST", f"{APPROVALS}/photos/SOMEONE/approve"),
    ("POST", f"{APPROVALS}/photos/SOMEONE/reject"),
]


@pytest.mark.anyio
@pytest.mark.parametrize("method,path", REVIEW_ROUTES)
async def test_review_routes_need_an_admin(method, path):
    teacher = await _token("teacher_apr", "TEACHER")
    student = await _token("student_apr", "STUDENT")
    async with _client() as client:
        no_token = await client.request(method, path)
        as_teacher = await client.request(method, path, headers=teacher)
        as_student = await client.request(method, path, headers=student)
    assert no_token.status_code == 401
    assert (as_teacher.status_code, as_student.status_code) == (403, 403)


# ------------------------------------------------------------------------------
# Rate limit on public registration
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_public_registration_is_rate_limited_across_the_three_routes(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "REGISTRATION_RATE_LIMIT_PER_MINUTE", 3)
    async with _client() as client:
        first = await client.post(
            "/api/v1/auth/register", json={"email": "r1@approval.test", "password": PASSWORD, "role": "STUDENT"}
        )
        second = await client.post("/api/v1/teachers/register", json=_teacher_payload("T-R2", "r2@approval.test"))
        third = await client.post(
            "/api/v1/auth/register", json={"email": "r3@approval.test", "password": PASSWORD, "role": "STUDENT"}
        )
        limited = [
            await client.post("/api/v1/students/register", json=_student_payload("R4", "r4@approval.test")),
            await client.post("/api/v1/teachers/register", json=_teacher_payload("T-R5", "r5@approval.test")),
            await client.post(
                "/api/v1/auth/register", json={"email": "r6@approval.test", "password": PASSWORD, "role": "STUDENT"}
            ),
        ]
        # Logging in is not registration and is not affected
        login = await _login(client, "r1@approval.test")

    assert (first.status_code, second.status_code, third.status_code) == (201, 201, 201)
    assert [r.status_code for r in limited] == [429, 429, 429]
    assert login.status_code == 403
    assert await mongodb.get_database()["users"].count_documents({}) == 3


# ------------------------------------------------------------------------------
# Existing accounts and the first administrator
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_accounts_from_before_approval_keep_working_and_migration_is_repeatable():
    db = mongodb.get_database()
    await db["users"].insert_one(
        {
            "user_id": "legacy_teacher",
            "email": "legacy@approval.test",
            "password_hash": hash_password(PASSWORD),
            "role": "TEACHER",
            "is_active": True,
        }
    )
    await db["biometric_profiles"].insert_one({"identity": "legacy_student", "mean_embedding": [0.1] * 512})

    async with _client() as client:
        before = await _login(client, "legacy@approval.test")
    first = await migrate_account_status(db)
    second = await migrate_account_status(db)
    async with _client() as client:
        after = await _login(client, "legacy@approval.test")

    assert before.status_code == 200 and after.status_code == 200
    assert first == {"users": 1, "templates": 1}
    assert second == {"users": 0, "templates": 0}
    assert (await db["users"].find_one({"user_id": "legacy_teacher"}))["status"] == "APPROVED"
    assert (await db["biometric_profiles"].find_one({"identity": "legacy_student"}))["review_status"] == "ACTIVE"


@pytest.mark.anyio
async def test_first_admin_is_created_from_the_environment_only_when_there_is_none(monkeypatch, caplog):
    db = mongodb.get_database()
    monkeypatch.delenv("BOOTSTRAP_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    assert await bootstrap_first_admin(db) == "not_configured"
    assert await db["users"].count_documents({"role": "ADMIN"}) == 0

    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "First.Admin@approval.test")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "short")
    assert await bootstrap_first_admin(db) == "invalid"
    assert await db["users"].count_documents({"role": "ADMIN"}) == 0

    bootstrap_password = "a-long-bootstrap-passphrase-2026"
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", bootstrap_password)
    assert await bootstrap_first_admin(db) == "created"
    admin = await db["users"].find_one({"role": "ADMIN"})
    assert admin["email"] == "first.admin@approval.test"
    assert admin["status"] == "APPROVED" and admin["must_change_password"] is True
    assert bootstrap_password not in json.dumps({k: str(v) for k, v in admin.items()})
    async with _client() as client:
        assert (await _login(client, "first.admin@approval.test", bootstrap_password)).status_code == 200

    # Still set afterwards: nothing changes, and a warning says to remove them
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "a-different-passphrase-entirely")
    with caplog.at_level("WARNING"):
        assert await bootstrap_first_admin(db) == "exists"
    assert await db["users"].count_documents({"role": "ADMIN"}) == 1
    assert (await db["users"].find_one({"role": "ADMIN"}))["password_hash"] == admin["password_hash"]
    warning = " ".join(r.getMessage() for r in caplog.records)
    assert "still set" in warning and "remove them" in warning
    assert "a-different-passphrase-entirely" not in warning and bootstrap_password not in warning


@pytest.mark.anyio
async def test_there_is_no_default_bootstrap_password(monkeypatch):
    """With only the email set, or only the password, no administrator is created."""
    import inspect
    import re

    from app.services import account_bootstrap

    db = mongodb.get_database()
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "only.email@approval.test")
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    assert await bootstrap_first_admin(db) == "invalid"
    monkeypatch.delenv("BOOTSTRAP_ADMIN_EMAIL", raising=False)
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "a-long-bootstrap-passphrase-2026")
    assert await bootstrap_first_admin(db) == "invalid"
    assert await db["users"].count_documents({"role": "ADMIN"}) == 0

    # Every environment read in the module falls back to an empty string.
    source = inspect.getsource(account_bootstrap)
    fallbacks = re.findall(r"os\.getenv\([^,]+,\s*([^)]+)\)", source)
    assert fallbacks and all(value.strip() == '""' for value in fallbacks), fallbacks
