from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.database.audit import AUDIT_EVENTS_COLLECTION, ensure_audit_indexes
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from app.services.audit_service import record_audit_event


@pytest.fixture
async def setup_test_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await db["sessions"].delete_many({})
    await db["session_rosters"].delete_many({})
    await db["attendance_records"].delete_many({})
    await db["users"].delete_many({})
    await db[AUDIT_EVENTS_COLLECTION].delete_many({})
    await ensure_audit_indexes(db)
    yield
    await db["sessions"].delete_many({})
    await db["session_rosters"].delete_many({})
    await db["attendance_records"].delete_many({})
    await db["users"].delete_many({})
    await db[AUDIT_EVENTS_COLLECTION].delete_many({})


@pytest.fixture
async def teacher_a_auth():
    teacher_id = "teacher_audit_a"
    await create_user(
        user_id=teacher_id,
        email="teacher_a@university.edu",
        password_hash=hash_password("Password123!"),
        role="TEACHER",
    )
    token = create_access_token(user_id=teacher_id, role="TEACHER")
    return {
        "user_id": teacher_id,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture
async def teacher_b_auth():
    teacher_id = "teacher_audit_b"
    await create_user(
        user_id=teacher_id,
        email="teacher_b@university.edu",
        password_hash=hash_password("Password123!"),
        role="TEACHER",
    )
    token = create_access_token(user_id=teacher_id, role="TEACHER")
    return {
        "user_id": teacher_id,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture
async def admin_auth():
    admin_id = "admin_audit_001"
    await create_user(
        user_id=admin_id,
        email="admin@university.edu",
        password_hash=hash_password("Password123!"),
        role="ADMIN",
    )
    token = create_access_token(user_id=admin_id, role="ADMIN")
    return {
        "user_id": admin_id,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture
async def student_auth():
    student_id = "student_audit_001"
    await create_user(
        user_id=student_id,
        email="student@university.edu",
        password_hash=hash_password("Password123!"),
        role="STUDENT",
    )
    token = create_access_token(user_id=student_id, role="STUDENT")
    return {
        "user_id": student_id,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture
async def seed_audit_scenario(teacher_a_auth, teacher_b_auth, admin_auth, student_auth):
    db = mongodb.get_database()

    # 1. Session A owned by Teacher A
    session_a = {
        "session_id": "session_a_100",
        "course_name": "Operating Systems",
        "classroom_id": "ROOM_101",
        "start_time": datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
        "end_time": datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
        "required_presence_percentage": 75.0,
        "status": "COMPLETED",
        "created_by": teacher_a_auth["user_id"],
        "created_at": datetime(2026, 10, 1, 8, 30, tzinfo=timezone.utc),
    }
    await db["sessions"].insert_one(session_a)

    # 2. Session B owned by Teacher B
    session_b = {
        "session_id": "session_b_200",
        "course_name": "Databases",
        "classroom_id": "ROOM_202",
        "start_time": datetime(2026, 10, 1, 11, 0, tzinfo=timezone.utc),
        "end_time": datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
        "required_presence_percentage": 80.0,
        "status": "SCHEDULED",
        "created_by": teacher_b_auth["user_id"],
        "created_at": datetime(2026, 10, 1, 10, 30, tzinfo=timezone.utc),
    }
    await db["sessions"].insert_one(session_b)

    # 3. Audit events for Session A (chronological sequence)
    await record_audit_event(
        actor_user_id=teacher_a_auth["user_id"],
        actor_role="TEACHER",
        action="SESSION_CREATED",
        resource_type="SESSION",
        resource_id=session_a["session_id"],
        timestamp=datetime(2026, 10, 1, 8, 30, tzinfo=timezone.utc),
        metadata={"course_name": "Operating Systems"},
    )
    await record_audit_event(
        actor_user_id=teacher_a_auth["user_id"],
        actor_role="TEACHER",
        action="ATTENDANCE_FINALIZED",
        resource_type="SESSION",
        resource_id=session_a["session_id"],
        timestamp=datetime(2026, 10, 1, 10, 5, tzinfo=timezone.utc),
        metadata={"attendance_record_count": 15},
    )

    # 4. Audit event for Session B
    await record_audit_event(
        actor_user_id=teacher_b_auth["user_id"],
        actor_role="TEACHER",
        action="SESSION_CREATED",
        resource_type="SESSION",
        resource_id=session_b["session_id"],
        timestamp=datetime(2026, 10, 1, 10, 30, tzinfo=timezone.utc),
        metadata={"course_name": "Databases"},
    )

    # 5. User audit event for Student
    await record_audit_event(
        actor_user_id=student_auth["user_id"],
        actor_role="STUDENT",
        action="USER_REGISTERED",
        resource_type="USER",
        resource_id=student_auth["user_id"],
        timestamp=datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc),
        metadata={"email": "student@university.edu"},
    )

    return {
        "session_a": session_a,
        "session_b": session_b,
    }


# ------------------------------------------------------------------------------
# 1. Teacher Authorization & Ownership Scoping Tests
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_teacher_can_retrieve_own_session_audit_history(
    setup_test_db, teacher_a_auth, seed_audit_scenario
):
    transport = ASGITransport(app=app)
    session_id = seed_audit_scenario["session_a"]["session_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/audit?resource_type=SESSION&resource_id={session_id}",
            headers=teacher_a_auth["headers"],
        )

    assert response.status_code == 200
    events = response.json()
    assert len(events) == 2
    assert events[0]["action"] == "SESSION_CREATED"
    assert events[1]["action"] == "ATTENDANCE_FINALIZED"
    for ev in events:
        assert ev["resource_id"] == session_id
        assert ev["actor_user_id"] == teacher_a_auth["user_id"]
        assert ev["actor_role"] == "TEACHER"


@pytest.mark.anyio
async def test_teacher_cannot_retrieve_another_teachers_session_history(
    setup_test_db, teacher_a_auth, seed_audit_scenario
):
    transport = ASGITransport(app=app)
    foreign_session_id = seed_audit_scenario["session_b"]["session_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/audit?resource_type=SESSION&resource_id={foreign_session_id}",
            headers=teacher_a_auth["headers"],
        )

    # Teacher A must be blocked from inspecting Teacher B's session audits
    assert response.status_code == 403
    assert "Forbidden" in response.json()["detail"]


@pytest.mark.anyio
async def test_teacher_cannot_access_user_or_system_audit_types(
    setup_test_db, teacher_a_auth, seed_audit_scenario
):
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp_user = await client.get(
            "/api/v1/audit?resource_type=USER",
            headers=teacher_a_auth["headers"],
        )
        assert resp_user.status_code == 403

        resp_system = await client.get(
            "/api/v1/audit?resource_type=SYSTEM",
            headers=teacher_a_auth["headers"],
        )
        assert resp_system.status_code == 403


# ------------------------------------------------------------------------------
# 2. Admin & Student RBAC Tests
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_admin_can_retrieve_authorized_audit_data(
    setup_test_db, admin_auth, student_auth, seed_audit_scenario
):
    transport = ASGITransport(app=app)
    session_b_id = seed_audit_scenario["session_b"]["session_id"]
    student_id = student_auth["user_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Admin can view Teacher B's session
        resp_session = await client.get(
            f"/api/v1/audit?resource_type=SESSION&resource_id={session_b_id}",
            headers=admin_auth["headers"],
        )
        assert resp_session.status_code == 200
        assert len(resp_session.json()) == 1

        # Admin can view student's user registration event
        resp_user = await client.get(
            f"/api/v1/audit?resource_type=USER&resource_id={student_id}",
            headers=admin_auth["headers"],
        )
        assert resp_user.status_code == 200
        assert len(resp_user.json()) == 1
        assert resp_user.json()[0]["action"] == "USER_REGISTERED"

        # Admin can retrieve global audit list without filters
        resp_all = await client.get(
            "/api/v1/audit",
            headers=admin_auth["headers"],
        )
        assert resp_all.status_code == 200
        assert len(resp_all.json()) >= 4


@pytest.mark.anyio
async def test_student_receives_403(
    setup_test_db, student_auth, seed_audit_scenario
):
    transport = ASGITransport(app=app)
    session_id = seed_audit_scenario["session_a"]["session_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # General audit query
        resp1 = await client.get(
            "/api/v1/audit",
            headers=student_auth["headers"],
        )
        assert resp1.status_code == 403

        # Scoped session audit query
        resp2 = await client.get(
            f"/api/v1/audit?resource_type=SESSION&resource_id={session_id}",
            headers=student_auth["headers"],
        )
        assert resp2.status_code == 403


# ------------------------------------------------------------------------------
# 3. Filtering & Chronological Ordering
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_filtering_and_chronological_ordering(
    setup_test_db, teacher_a_auth, seed_audit_scenario
):
    transport = ASGITransport(app=app)
    session_id = seed_audit_scenario["session_a"]["session_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/audit?resource_type=SESSION&resource_id={session_id}",
            headers=teacher_a_auth["headers"],
        )

    assert response.status_code == 200
    events = response.json()
    assert len(events) == 2

    # Verify chronological ascending order
    ts0 = datetime.fromisoformat(events[0]["timestamp"])
    ts1 = datetime.fromisoformat(events[1]["timestamp"])
    assert ts0 <= ts1
    assert events[0]["action"] == "SESSION_CREATED"
    assert events[1]["action"] == "ATTENDANCE_FINALIZED"


# ------------------------------------------------------------------------------
# 4. Error Handling: Nonexistent Resource, Invalid Filter, Auth Failures
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_nonexistent_resource_returns_404(
    setup_test_db, teacher_a_auth, admin_auth
):
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Teacher queries nonexistent session
        resp_teacher = await client.get(
            "/api/v1/audit?resource_type=SESSION&resource_id=session_nonexistent_999",
            headers=teacher_a_auth["headers"],
        )
        assert resp_teacher.status_code == 404

        # Admin queries nonexistent user
        resp_admin = await client.get(
            "/api/v1/audit?resource_type=USER&resource_id=user_nonexistent_999",
            headers=admin_auth["headers"],
        )
        assert resp_admin.status_code == 404


@pytest.mark.anyio
async def test_invalid_filter_values_return_400(
    setup_test_db, teacher_a_auth, admin_auth
):
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Invalid resource_type
        resp1 = await client.get(
            "/api/v1/audit?resource_type=INVALID_RESOURCE_TYPE",
            headers=teacher_a_auth["headers"],
        )
        assert resp1.status_code == 400
        assert "Invalid resource_type" in resp1.json()["detail"]

        resp2 = await client.get(
            "/api/v1/audit?resource_type=HACK_INJECTION",
            headers=admin_auth["headers"],
        )
        assert resp2.status_code == 400


@pytest.mark.anyio
async def test_authentication_failures_return_401(setup_test_db):
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Missing token
        resp1 = await client.get("/api/v1/audit")
        assert resp1.status_code == 401

        # Malformed / invalid token
        resp2 = await client.get(
            "/api/v1/audit",
            headers={"Authorization": "Bearer invalid.token.value"},
        )
        assert resp2.status_code == 401


# ------------------------------------------------------------------------------
# 5. Immutability Contract: Mutation HTTP Methods Rejected
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_audit_records_remain_immutable_via_http(
    setup_test_db, admin_auth
):
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # POST /api/v1/audit -> 405 Method Not Allowed
        post_resp = await client.post(
            "/api/v1/audit",
            headers=admin_auth["headers"],
            json={"audit_id": "fake_hack"},
        )
        assert post_resp.status_code == 405

        # PUT /api/v1/audit -> 405 Method Not Allowed
        put_resp = await client.put(
            "/api/v1/audit",
            headers=admin_auth["headers"],
            json={"audit_id": "fake_hack"},
        )
        assert put_resp.status_code == 405

        # DELETE /api/v1/audit -> 405 Method Not Allowed
        del_resp = await client.delete(
            "/api/v1/audit",
            headers=admin_auth["headers"],
        )
        assert del_resp.status_code == 405

        # PATCH /api/v1/audit -> 405 Method Not Allowed
        patch_resp = await client.patch(
            "/api/v1/audit",
            headers=admin_auth["headers"],
            json={"audit_id": "fake_hack"},
        )
        assert patch_resp.status_code == 405
