from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.database.audit import AUDIT_EVENTS_COLLECTION, ensure_audit_indexes, get_audit_events
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from tests.conftest import assign_teacher_classes


@pytest.fixture
async def setup_test_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await db["sessions"].delete_many({})
    await db["session_rosters"].delete_many({})
    await db["users"].delete_many({})
    await db[AUDIT_EVENTS_COLLECTION].delete_many({})
    await ensure_audit_indexes(db)
    yield
    await db["sessions"].delete_many({})
    await db["session_rosters"].delete_many({})
    await db["users"].delete_many({})
    await db[AUDIT_EVENTS_COLLECTION].delete_many({})


@pytest.fixture
async def teacher_auth():
    teacher_id = "teacher_audit_001"
    await create_user(
        user_id=teacher_id,
        email="teacher.audit@university.edu",
        password_hash=hash_password("Password123!"),
        role="TEACHER",
    )
    await assign_teacher_classes(teacher_id)
    token = create_access_token(user_id=teacher_id, role="TEACHER")
    return {
        "user_id": teacher_id,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture
async def other_teacher_auth():
    teacher_id = "teacher_audit_002"
    await create_user(
        user_id=teacher_id,
        email="teacher2.audit@university.edu",
        password_hash=hash_password("Password123!"),
        role="TEACHER",
    )
    await assign_teacher_classes(teacher_id)
    token = create_access_token(user_id=teacher_id, role="TEACHER")
    return {
        "user_id": teacher_id,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture
async def student_auth():
    student_id = "student_audit_001"
    await create_user(
        user_id=student_id,
        email="student.audit@university.edu",
        password_hash=hash_password("Password123!"),
        role="STUDENT",
    )
    token = create_access_token(user_id=student_id, role="STUDENT")
    return {
        "user_id": student_id,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture
async def seeded_session(teacher_auth):
    db = mongodb.get_database()
    session_doc = {
        "session_id": "session_audit_test_100",
        "course_name": "Operating Systems",
        "classroom_id": "ROOM_202",
        "class_code": "DS-B",
        "start_time": datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
        "end_time": datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
        "required_presence_percentage": 75.0,
        "status": "SCHEDULED",
        "created_by": teacher_auth["user_id"],
        "created_at": datetime.now(timezone.utc),
    }
    await db["sessions"].insert_one(session_doc)
    return session_doc


# ------------------------------------------------------------------------------
# 1. Session Creation Audit Tests
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_teacher_creates_session_records_audit_event(setup_test_db, teacher_auth):
    transport = ASGITransport(app=app)
    payload = {
        "course_name": "Distributed Systems",
        "classroom_id": "ROOM_404",
        "class_code": "DS-B",
        "start_time": "2026-10-02T10:00:00Z",
        "end_time": "2026-10-02T11:30:00Z",
        "required_presence_percentage": 80.0,
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/sessions",
            headers=teacher_auth["headers"],
            json=payload,
        )

    assert response.status_code == 201
    body = response.json()
    session_id = body["session_id"]

    events = await get_audit_events(resource_type="SESSION", resource_id=session_id)
    assert len(events) == 1

    ev = events[0]
    assert ev["audit_id"].startswith("audit_")
    assert ev["actor_user_id"] == teacher_auth["user_id"]
    assert ev["actor_role"] == "TEACHER"
    assert ev["action"] == "SESSION_CREATED"
    assert ev["resource_type"] == "SESSION"
    assert ev["resource_id"] == session_id
    assert ev["metadata"]["course_name"] == "Distributed Systems"
    assert ev["metadata"]["classroom_id"] == "ROOM_404"
    assert ev["metadata"]["required_presence_percentage"] == 80.0
    assert "2026-10-02T10:00:00" in ev["metadata"]["start_time"]
    assert "2026-10-02T11:30:00" in ev["metadata"]["end_time"]


@pytest.mark.anyio
async def test_failed_session_creation_does_not_create_audit_event(setup_test_db, teacher_auth, student_auth):
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Invalid payload (presence percentage > 100)
        invalid_payload = {
            "course_name": "Distributed Systems",
            "classroom_id": "ROOM_404",
            "class_code": "DS-B",
            "start_time": "2026-10-02T10:00:00Z",
            "end_time": "2026-10-02T11:30:00Z",
            "required_presence_percentage": 150.0,
        }
        resp1 = await client.post(
            "/api/v1/sessions",
            headers=teacher_auth["headers"],
            json=invalid_payload,
        )
        assert resp1.status_code == 422

        # Student unauthorized attempt
        valid_payload = {
            "course_name": "Distributed Systems",
            "classroom_id": "ROOM_404",
            "class_code": "DS-B",
            "start_time": "2026-10-02T10:00:00Z",
            "end_time": "2026-10-02T11:30:00Z",
            "required_presence_percentage": 80.0,
        }
        resp2 = await client.post(
            "/api/v1/sessions",
            headers=student_auth["headers"],
            json=valid_payload,
        )
        assert resp2.status_code == 403

    # Assert no audit event was created
    events = await get_audit_events(resource_type="SESSION")
    assert len(events) == 0


@pytest.mark.anyio
async def test_audit_failure_does_not_prevent_session_creation(setup_test_db, teacher_auth):
    transport = ASGITransport(app=app)
    payload = {
        "course_name": "Resilience Engineering",
        "classroom_id": "ROOM_101",
        "class_code": "DS-B",
        "start_time": "2026-10-02T14:00:00Z",
        "end_time": "2026-10-02T15:00:00Z",
        "required_presence_percentage": 75.0,
    }

    with patch(
        "app.api.routes.sessions.record_audit_event",
        side_effect=RuntimeError("Simulated audit database connection outage"),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/sessions",
                headers=teacher_auth["headers"],
                json=payload,
            )

    # Primary business operation succeeds
    assert response.status_code == 201
    body = response.json()
    assert body["course_name"] == "Resilience Engineering"
    assert body["session_id"].startswith("session_")


# ------------------------------------------------------------------------------
# 2. Roster Update Audit Tests
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_teacher_updates_roster_records_audit_event(setup_test_db, teacher_auth, seeded_session):
    transport = ASGITransport(app=app)
    session_id = seeded_session["session_id"]
    payload = {
        "identities": ["student_alice", "student_bob", "student_carol"]
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/sessions/{session_id}/roster",
            headers=teacher_auth["headers"],
            json=payload,
        )

    assert response.status_code == 200
    events = await get_audit_events(resource_type="SESSION_ROSTER", resource_id=session_id)
    assert len(events) == 1

    ev = events[0]
    assert ev["audit_id"].startswith("audit_")
    assert ev["actor_user_id"] == teacher_auth["user_id"]
    assert ev["actor_role"] == "TEACHER"
    assert ev["action"] == "ROSTER_UPDATED"
    assert ev["resource_type"] == "SESSION_ROSTER"
    assert ev["resource_id"] == session_id
    assert ev["metadata"] == {"student_count": 3}


@pytest.mark.anyio
async def test_failed_roster_update_does_not_create_audit_event(
    setup_test_db, teacher_auth, other_teacher_auth, seeded_session
):
    transport = ASGITransport(app=app)
    session_id = seeded_session["session_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Non-owning teacher tries to update roster -> 403 Forbidden
        resp1 = await client.post(
            f"/api/v1/sessions/{session_id}/roster",
            headers=other_teacher_auth["headers"],
            json={"identities": ["intruder_student"]},
        )
        assert resp1.status_code == 403

        # 2. Update roster on non-existent session -> 404 Not Found
        resp2 = await client.post(
            "/api/v1/sessions/non_existent_session_999/roster",
            headers=teacher_auth["headers"],
            json={"identities": ["student_x"]},
        )
        assert resp2.status_code == 404

    # Assert no ROSTER_UPDATED audit events created
    events = await get_audit_events(resource_type="SESSION_ROSTER")
    assert len(events) == 0


@pytest.mark.anyio
async def test_audit_failure_does_not_prevent_roster_update(setup_test_db, teacher_auth, seeded_session):
    transport = ASGITransport(app=app)
    session_id = seeded_session["session_id"]
    payload = {
        "identities": ["student_resilient_01", "student_resilient_02"]
    }

    with patch(
        "app.api.routes.session_roster.record_audit_event",
        side_effect=RuntimeError("Simulated audit database connection outage"),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/sessions/{session_id}/roster",
                headers=teacher_auth["headers"],
                json=payload,
            )

    # Primary business operation succeeds
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == session_id
    assert body["identities"] == ["student_resilient_01", "student_resilient_02"]
