"""Deleting a student removes everything held about them, and is audited.

DELETE /api/v1/admin/students/{user_id} used to remove only the account, the
profile and the face template: no audit entry, and the photo, attendance
records and roster entries stayed behind. These tests fail if any of that
comes back. The vision service call is stubbed; photos are placeholder bytes.
"""

from datetime import datetime, timezone
import json

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.core.config import settings
from app.core.uploads import student_photo_path
from app.database import mongodb
from app.database.mongodb import init_indexes
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from app.services import student_deletion

URL = "/api/v1/admin/students/{}"
STUDENT_NAME = "Deletion Target Student"
STUDENT_EMAIL = "del001@deletion.test"


@pytest.fixture(autouse=True)
async def fresh_db():
    mongodb._client = AsyncMongoMockClient()
    await init_indexes(mongodb.get_database())
    yield
    mongodb._client = AsyncMongoMockClient()


@pytest.fixture
def vision(monkeypatch):
    """Record the gallery refresh instead of calling the vision service."""
    calls = []

    async def fake_refresh() -> bool:
        calls.append("reload")
        return True

    monkeypatch.setattr(student_deletion, "_refresh_vision_gallery", fake_refresh)
    return calls


async def _headers(user_id: str, role: str) -> dict[str, str]:
    await create_user(
        user_id=user_id,
        email=f"{user_id}@deletion.test",
        password_hash=hash_password("Password123!"),
        role=role,
    )
    return {"Authorization": f"Bearer {create_access_token(user_id=user_id, role=role)}"}


async def _student(user_id: str, student_id: str, identity: str, *, email: str = STUDENT_EMAIL) -> None:
    """A student with data in every place the system keeps it."""
    db = mongodb.get_database()
    now = datetime.now(timezone.utc)
    await create_user(
        user_id=user_id, email=email, password_hash=hash_password("Password123!"), role="STUDENT"
    )
    await db["student_profiles"].insert_one(
        {
            "user_id": user_id,
            "identity": identity,
            "student_id": student_id,
            "name": STUDENT_NAME,
            "email": email,
            "class_code": "DS-B",
            "photo_base64": "cGxhY2Vob2xkZXI=",
        }
    )
    await db["biometric_profiles"].insert_one({"identity": identity, "mean_embedding": [0.1] * 512})
    for key in {student_id, identity}:
        path = student_photo_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"placeholder photo bytes")
    for n in (1, 2, 3):
        # Session IDs deliberately say nothing about the student: a session is
        # not the student's data and stays after the deletion.
        session_id = f"sess_{student_id.lower()[:3]}{abs(hash(user_id)) % 10_000}_{n}"
        await db["attendance_records"].insert_one(
            {
                "attendance_id": f"att_{session_id}_{identity}",
                "session_id": session_id,
                "identity": identity,
                "student_id": student_id,
                "student_name": STUDENT_NAME,
                "status": "PRESENT",
            }
        )
        await db["session_rosters"].insert_one(
            {"session_id": session_id, "identities": [identity, "someone_else"]}
        )
    await db["attendance_corrections"].insert_one(
        {"correction_id": f"corr_{abs(hash(user_id)) % 10_000}", "identity": identity, "session_id": "sess_x_1"}
    )
    for direction in ("ENTRY", "EXIT"):
        await db[settings.EVENTS_COLLECTION].insert_one(
            {"event_id": f"evt_{user_id}_{direction}", "identity": identity, "direction": direction, "timestamp": now}
        )


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _mentions(*needles: str) -> dict[str, int]:
    """How many documents in each collection still mention any of the given strings."""
    db = mongodb.get_database()
    found = {}
    for name in await db.list_collection_names():
        if name == "audit_events":
            continue
        count = 0
        async for doc in db[name].find({}):
            text = json.dumps({k: v for k, v in doc.items() if k != "_id"}, default=str)
            if any(needle in text for needle in needles):
                count += 1
        if count:
            found[name] = count
    return found


# ------------------------------------------------------------------------------
# Everything is removed
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_deleting_a_student_removes_every_trace_of_them(vision):
    await _student("user_del_1", "DEL001", "del_identity_1")
    admin = await _headers("admin_del", "ADMIN")
    before = await _mentions("user_del_1", "DEL001", "del_identity_1", STUDENT_NAME, STUDENT_EMAIL)
    assert set(before) == {
        "users",
        "student_profiles",
        "biometric_profiles",
        "attendance_records",
        "attendance_corrections",
        settings.EVENTS_COLLECTION,
        "session_rosters",
    }

    async with _client() as client:
        response = await client.delete(URL.format("user_del_1"), headers=admin)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "deleted" and body["user_id"] == "user_del_1"
    assert body["student_id"] == "DEL001"
    assert body["removed"] == {
        "account_deleted": True,
        "profile_deleted": True,
        "face_templates_deleted": 1,
        "photo_files_deleted": 2,
        "attendance_records_deleted": 3,
        "attendance_corrections_deleted": 1,
        "doorway_events_deleted": 2,
        "roster_entries_removed": 3,
        "vision_gallery_refreshed": True,
    }

    assert await _mentions("user_del_1", "DEL001", "del_identity_1", STUDENT_NAME, STUDENT_EMAIL) == {}
    assert not student_photo_path("DEL001").exists()
    assert not student_photo_path("del_identity_1").exists()
    assert vision == ["reload"]


@pytest.mark.anyio
async def test_other_students_and_the_rest_of_each_roster_are_untouched(vision):
    await _student("user_del_1", "DEL001", "del_identity_1")
    await _student("user_keep_1", "KEEP001", "keep_identity_1", email="keep001@deletion.test")
    admin = await _headers("admin_del", "ADMIN")
    db = mongodb.get_database()

    async with _client() as client:
        assert (await client.delete(URL.format("user_del_1"), headers=admin)).status_code == 200

    assert await db["users"].count_documents({"user_id": "user_keep_1"}) == 1
    assert await db["student_profiles"].count_documents({"student_id": "KEEP001"}) == 1
    assert await db["biometric_profiles"].count_documents({"identity": "keep_identity_1"}) == 1
    assert await db["attendance_records"].count_documents({"identity": "keep_identity_1"}) == 3
    assert await db[settings.EVENTS_COLLECTION].count_documents({"identity": "keep_identity_1"}) == 2
    assert student_photo_path("KEEP001").is_file()
    # Rosters keep their other members; only the deleted student is pulled out
    rosters = [r async for r in db["session_rosters"].find({})]
    assert len(rosters) == 6
    assert all("del_identity_1" not in r["identities"] for r in rosters)
    assert all("someone_else" in r["identities"] for r in rosters)
    assert sum("keep_identity_1" in r["identities"] for r in rosters) == 3


# ------------------------------------------------------------------------------
# Audited, without keeping what was deleted
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_deletion_writes_one_audit_entry_with_ids_and_counts_only(vision):
    await _student("user_del_1", "DEL001", "del_identity_1")
    admin = await _headers("admin_del", "ADMIN")

    async with _client() as client:
        await client.delete(URL.format("user_del_1"), headers=admin)

    events = [e async for e in mongodb.get_database()["audit_events"].find({"action": "STUDENT_DELETED"})]
    assert len(events) == 1
    event = events[0]
    assert event["actor_user_id"] == "admin_del"
    assert event["actor_role"] == "ADMIN"
    assert event["resource_type"] == "STUDENT_PROFILE"
    assert event["resource_id"] == "DEL001"
    assert event["metadata"]["deleted_user_id"] == "user_del_1"
    assert event["metadata"]["identities"] == ["DEL001", "del_identity_1"]
    assert event["metadata"]["attendance_records_deleted"] == 3
    assert event["metadata"]["photo_files_deleted"] == 2

    # The audit entry must not preserve the personal data that was just deleted.
    serialized = json.dumps({k: v for k, v in event.items() if k != "_id"}, default=str)
    for personal in (STUDENT_NAME, STUDENT_EMAIL, "cGxhY2Vob2xkZXI=", "0.1, 0.1"):
        assert personal not in serialized


# ------------------------------------------------------------------------------
# Who may delete, and what may be deleted
# ------------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["TEACHER", "STUDENT"])
async def test_only_an_admin_can_delete_a_student(vision, role):
    await _student("user_del_1", "DEL001", "del_identity_1")
    headers = await _headers(f"not_admin_{role.lower()}", role)

    async with _client() as client:
        no_token = await client.delete(URL.format("user_del_1"))
        forbidden = await client.delete(URL.format("user_del_1"), headers=headers)

    assert no_token.status_code == 401
    assert forbidden.status_code == 403
    assert await mongodb.get_database()["users"].count_documents({"user_id": "user_del_1"}) == 1
    assert student_photo_path("DEL001").is_file()
    assert [e async for e in mongodb.get_database()["audit_events"].find({"action": "STUDENT_DELETED"})] == []


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["TEACHER", "ADMIN"])
async def test_the_route_cannot_be_used_to_delete_a_teacher_or_an_admin(vision, role):
    """It used to delete whatever user ID it was given."""
    admin = await _headers("admin_del", "ADMIN")
    await _headers("staff_account", role)

    async with _client() as client:
        response = await client.delete(URL.format("staff_account"), headers=admin)
        own_account = await client.delete(URL.format("admin_del"), headers=admin)

    assert response.status_code == 400
    assert own_account.status_code == 400
    db = mongodb.get_database()
    assert await db["users"].count_documents({"user_id": "staff_account"}) == 1
    assert await db["users"].count_documents({"user_id": "admin_del"}) == 1
    assert await db["audit_events"].count_documents({"action": "STUDENT_DELETED"}) == 0


@pytest.mark.anyio
async def test_unknown_student_is_404_and_writes_no_audit_entry(vision):
    admin = await _headers("admin_del", "ADMIN")

    async with _client() as client:
        response = await client.delete(URL.format("user_does_not_exist"), headers=admin)

    assert response.status_code == 404
    assert await mongodb.get_database()["audit_events"].count_documents({"action": "STUDENT_DELETED"}) == 0
    assert vision == []


@pytest.mark.anyio
async def test_deleting_twice_is_404_the_second_time(vision):
    await _student("user_del_1", "DEL001", "del_identity_1")
    admin = await _headers("admin_del", "ADMIN")

    async with _client() as client:
        first = await client.delete(URL.format("user_del_1"), headers=admin)
        second = await client.delete(URL.format("user_del_1"), headers=admin)

    assert (first.status_code, second.status_code) == (200, 404)
    assert await mongodb.get_database()["audit_events"].count_documents({"action": "STUDENT_DELETED"}) == 1


# ------------------------------------------------------------------------------
# Partial data and failures
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_student_with_an_account_but_no_profile_can_be_deleted(vision):
    admin = await _headers("admin_del", "ADMIN")
    await _headers("student_no_profile", "STUDENT")

    async with _client() as client:
        response = await client.delete(URL.format("student_no_profile"), headers=admin)

    assert response.status_code == 200
    removed = response.json()["removed"]
    assert removed["account_deleted"] is True and removed["profile_deleted"] is False
    assert removed["face_templates_deleted"] == 0
    assert vision == []  # nothing enrolled, so nothing to drop from the gallery
    assert await mongodb.get_database()["users"].count_documents({"user_id": "student_no_profile"}) == 0


@pytest.mark.anyio
async def test_deletion_completes_when_the_vision_service_is_unreachable(monkeypatch):
    """The gallery also refreshes itself; an unreachable vision service must not block erasure."""
    monkeypatch.setattr(settings, "VISION_SERVICE_URL", "http://127.0.0.1:9")
    await _student("user_del_1", "DEL001", "del_identity_1")
    admin = await _headers("admin_del", "ADMIN")

    async with _client() as client:
        response = await client.delete(URL.format("user_del_1"), headers=admin)

    assert response.status_code == 200
    assert response.json()["removed"]["vision_gallery_refreshed"] is False
    assert await _mentions("user_del_1", "DEL001", "del_identity_1") == {}
    assert await mongodb.get_database()["audit_events"].count_documents({"action": "STUDENT_DELETED"}) == 1


@pytest.mark.anyio
async def test_gallery_route_no_longer_serves_the_deleted_face(vision, service_key_headers):
    await _student("user_del_1", "DEL001", "del_identity_1")
    admin = await _headers("admin_del", "ADMIN")

    async with _client() as client:
        before = await client.get("/api/v1/attendance/vision-gallery", headers=service_key_headers)
        await client.delete(URL.format("user_del_1"), headers=admin)
        after = await client.get("/api/v1/attendance/vision-gallery", headers=service_key_headers)
        photo = await client.get("/api/v1/students/DEL001/photo", headers=admin)

    assert before.json()["count"] == 1
    assert after.json()["count"] == 0
    assert photo.status_code == 404


@pytest.mark.anyio
async def test_the_teacher_delete_route_only_deletes_teachers(vision):
    """It had the same flaw: it deleted whatever user ID it was given."""
    admin = await _headers("admin_del", "ADMIN")
    await _headers("a_teacher", "TEACHER")
    await _student("user_del_1", "DEL001", "del_identity_1")

    async with _client() as client:
        student = await client.delete("/api/v1/admin/teachers/user_del_1", headers=admin)
        own = await client.delete("/api/v1/admin/teachers/admin_del", headers=admin)
        teacher = await client.delete("/api/v1/admin/teachers/a_teacher", headers=admin)

    assert (student.status_code, own.status_code, teacher.status_code) == (400, 400, 200)
    db = mongodb.get_database()
    assert await db["users"].count_documents({"user_id": "user_del_1"}) == 1
    assert await db["users"].count_documents({"user_id": "admin_del"}) == 1
    assert await db["users"].count_documents({"user_id": "a_teacher"}) == 0
