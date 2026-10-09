from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.database.attendance import create_attendance
from app.database.mongodb import init_indexes
from app.database.sessions import create_session
from app.database.users import DuplicateUserRecordError, create_user
from app.main import app
from app.schemas.attendance import AttendanceRecord
from app.schemas.session import SessionCreate
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from app.services.session_enrollment import enroll_session_roster
from tests.conftest import assign_teacher_classes


@pytest.fixture(autouse=True)
async def setup_test_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await init_indexes(db)
    await db["sessions"].delete_many({})
    await db["session_rosters"].delete_many({})
    await db["attendance_records"].delete_many({})
    await db["users"].delete_many({})
    yield
    await db["sessions"].delete_many({})
    await db["session_rosters"].delete_many({})
    await db["attendance_records"].delete_many({})
    await db["users"].delete_many({})


@pytest.mark.anyio
async def test_database_unique_email_constraint():
    pw_hash = hash_password("Password123!")

    # First user
    await create_user(
        user_id="user_email_1",
        email="unique.teacher@example.com",
        password_hash=pw_hash,
        role="TEACHER",
    )
    await assign_teacher_classes("user_email_1")

    # Second user directly inserted via repository with case variation
    with pytest.raises(DuplicateUserRecordError, match="already exists"):
        await create_user(
            user_id="user_email_2",
            email="UNIQUE.TEACHER@EXAMPLE.COM",
            password_hash=pw_hash,
            role="STUDENT",
        )


@pytest.fixture
async def ownership_context():
    pw_hash = hash_password("Password123!")

    teacher_a = await create_user(
        user_id="teacher_a_id",
        email="teacher_a@test.com",
        password_hash=pw_hash,
        role="TEACHER",
    )
    await assign_teacher_classes("teacher_a_id")
    teacher_b = await create_user(
        user_id="teacher_b_id",
        email="teacher_b@test.com",
        password_hash=pw_hash,
        role="TEACHER",
    )
    await assign_teacher_classes("teacher_b_id")
    student = await create_user(
        user_id="student_id",
        email="student@test.com",
        password_hash=pw_hash,
        role="STUDENT",
    )
    admin = await create_user(
        user_id="admin_id",
        email="admin@test.com",
        password_hash=pw_hash,
        role="ADMIN",
    )

    # Teacher A creates Session A
    session = SessionCreate(
        course_name="Distributed Systems",
        classroom_id="ROOM_A",
        start_time=datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 9, 29, 11, 0, tzinfo=timezone.utc),
        required_presence_percentage=75.0,
    )
    created_session = await create_session(session, created_by=teacher_a["user_id"])
    session_id = created_session["session_id"]

    await enroll_session_roster(
        session_id=session_id,
        identities=["student_alice", "student_bob"],
    )

    record = AttendanceRecord(
        attendance_id=f"att_{session_id}_student_alice",
        session_id=session_id,
        identity="student_alice",
        presence_intervals=[],
        presence_duration_seconds=0,
        presence_percentage=0,
        required_presence_percentage=75.0,
        status="ABSENT",
    )
    await create_attendance(record)

    return {
        "session_id": session_id,
        "teacher_a_token": create_access_token(user_id=teacher_a["user_id"], role="TEACHER"),
        "teacher_b_token": create_access_token(user_id=teacher_b["user_id"], role="TEACHER"),
        "student_token": create_access_token(user_id=student["user_id"], role="STUDENT"),
        "admin_token": create_access_token(user_id=admin["user_id"], role="ADMIN"),
    }


@pytest.mark.anyio
async def test_session_creation_assigns_authenticated_creator(ownership_context):
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {ownership_context['teacher_a_token']}"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/sessions",
            headers=headers,
            json={
                "course_name": "Cloud Computing",
                "classroom_id": "ROOM_B",
                "class_code": "DS-B",
                "start_time": "2026-09-29T14:00:00Z",
                "end_time": "2026-09-29T15:00:00Z",
                "required_presence_percentage": 75.0,
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["created_by"] == "teacher_a_id"

    # Confirm in DB
    db = mongodb.get_database()
    saved = await db["sessions"].find_one({"session_id": body["session_id"]})
    assert saved is not None
    assert saved["created_by"] == "teacher_a_id"


@pytest.mark.anyio
async def test_roster_update_ownership(ownership_context):
    transport = ASGITransport(app=app)
    session_id = ownership_context["session_id"]
    payload = {"identities": ["student_alice", "student_bob", "student_clara"]}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Teacher A (Owner) -> 200
        res_a = await client.post(
            f"/api/v1/sessions/{session_id}/roster",
            headers={"Authorization": f"Bearer {ownership_context['teacher_a_token']}"},
            json=payload,
        )
        assert res_a.status_code == 200

        # Teacher B (Non-Owner) -> 403
        res_b = await client.post(
            f"/api/v1/sessions/{session_id}/roster",
            headers={"Authorization": f"Bearer {ownership_context['teacher_b_token']}"},
            json=payload,
        )
        assert res_b.status_code == 403

        # Student -> 403
        res_student = await client.post(
            f"/api/v1/sessions/{session_id}/roster",
            headers={"Authorization": f"Bearer {ownership_context['student_token']}"},
            json=payload,
        )
        assert res_student.status_code == 403

        # Admin -> 403
        res_admin = await client.post(
            f"/api/v1/sessions/{session_id}/roster",
            headers={"Authorization": f"Bearer {ownership_context['admin_token']}"},
            json=payload,
        )
        assert res_admin.status_code == 403

        # Nonexistent Session -> 404
        res_404 = await client.post(
            "/api/v1/sessions/nonexistent_session_id/roster",
            headers={"Authorization": f"Bearer {ownership_context['teacher_a_token']}"},
            json=payload,
        )
        assert res_404.status_code == 404


@pytest.mark.anyio
async def test_roster_retrieval_ownership(ownership_context):
    transport = ASGITransport(app=app)
    session_id = ownership_context["session_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Teacher A (Owner) -> 200
        res_a = await client.get(
            f"/api/v1/sessions/{session_id}/roster",
            headers={"Authorization": f"Bearer {ownership_context['teacher_a_token']}"},
        )
        assert res_a.status_code == 200

        # Teacher B (Non-Owner) -> 403
        res_b = await client.get(
            f"/api/v1/sessions/{session_id}/roster",
            headers={"Authorization": f"Bearer {ownership_context['teacher_b_token']}"},
        )
        assert res_b.status_code == 403

        # Student -> 403
        res_student = await client.get(
            f"/api/v1/sessions/{session_id}/roster",
            headers={"Authorization": f"Bearer {ownership_context['student_token']}"},
        )
        assert res_student.status_code == 403

        # Admin -> 403
        res_admin = await client.get(
            f"/api/v1/sessions/{session_id}/roster",
            headers={"Authorization": f"Bearer {ownership_context['admin_token']}"},
        )
        # An administrator may open any session (read-only); see test_admin_session_access.py.
        assert res_admin.status_code == 200

        # Nonexistent Session -> 404
        res_404 = await client.get(
            "/api/v1/sessions/nonexistent_session_id/roster",
            headers={"Authorization": f"Bearer {ownership_context['teacher_a_token']}"},
        )
        assert res_404.status_code == 404


@pytest.mark.anyio
async def test_session_finalization_ownership(ownership_context):
    transport = ASGITransport(app=app)
    session_id = ownership_context["session_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Teacher B (Non-Owner) -> 403
        res_b = await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers={"Authorization": f"Bearer {ownership_context['teacher_b_token']}"},
        )
        assert res_b.status_code == 403

        # Student -> 403
        res_student = await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers={"Authorization": f"Bearer {ownership_context['student_token']}"},
        )
        assert res_student.status_code == 403

        # Admin -> 403
        res_admin = await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers={"Authorization": f"Bearer {ownership_context['admin_token']}"},
        )
        assert res_admin.status_code == 403

        # Nonexistent Session -> 404
        res_404 = await client.post(
            "/api/v1/sessions/nonexistent_session_id/finalize",
            headers={"Authorization": f"Bearer {ownership_context['teacher_a_token']}"},
        )
        assert res_404.status_code == 404

        # Teacher A (Owner) -> 200
        res_a = await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers={"Authorization": f"Bearer {ownership_context['teacher_a_token']}"},
        )
        assert res_a.status_code == 200


@pytest.mark.anyio
async def test_attendance_retrieval_ownership(ownership_context):
    transport = ASGITransport(app=app)
    session_id = ownership_context["session_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Teacher A (Owner) -> 200
        res_a = await client.get(
            f"/api/v1/attendance/{session_id}",
            headers={"Authorization": f"Bearer {ownership_context['teacher_a_token']}"},
        )
        assert res_a.status_code == 200

        # Teacher B (Non-Owner) -> 403
        res_b = await client.get(
            f"/api/v1/attendance/{session_id}",
            headers={"Authorization": f"Bearer {ownership_context['teacher_b_token']}"},
        )
        assert res_b.status_code == 403

        # Student -> 403
        res_student = await client.get(
            f"/api/v1/attendance/{session_id}",
            headers={"Authorization": f"Bearer {ownership_context['student_token']}"},
        )
        assert res_student.status_code == 403

        # Admin -> 403
        res_admin = await client.get(
            f"/api/v1/attendance/{session_id}",
            headers={"Authorization": f"Bearer {ownership_context['admin_token']}"},
        )
        # An administrator may open any session (read-only); see test_admin_session_access.py.
        assert res_admin.status_code == 200

        # Nonexistent Session -> 404
        res_404 = await client.get(
            "/api/v1/attendance/nonexistent_session_id",
            headers={"Authorization": f"Bearer {ownership_context['teacher_a_token']}"},
        )
        assert res_404.status_code == 404


@pytest.mark.anyio
async def test_list_sessions_ownership_matrix(ownership_context):
    """
    Verify GET /api/v1/sessions:
    - No token -> 401
    - Student -> 403
    - Admin -> 403
    - Teacher A -> sees only Teacher A sessions
    - Teacher B -> sees only Teacher B sessions
    """
    transport = ASGITransport(app=app)
    session_a_id = ownership_context["session_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. No token -> 401
        res_no_auth = await client.get("/api/v1/sessions")
        assert res_no_auth.status_code == 401

        # 2. Student -> 403
        res_student = await client.get(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {ownership_context['student_token']}"},
        )
        assert res_student.status_code == 403

        # 3. Admin -> 403
        res_admin = await client.get(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {ownership_context['admin_token']}"},
        )
        # An administrator may open any session (read-only); see test_admin_session_access.py.
        assert res_admin.status_code == 200

        # 4. Teacher A -> sees Session A
        res_teacher_a = await client.get(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {ownership_context['teacher_a_token']}"},
        )
        assert res_teacher_a.status_code == 200
        sessions_a = res_teacher_a.json()
        assert len(sessions_a) == 1
        assert sessions_a[0]["session_id"] == session_a_id
        assert sessions_a[0]["created_by"] == "teacher_a_id"

        # 5. Teacher B initially has 0 sessions
        res_teacher_b_empty = await client.get(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {ownership_context['teacher_b_token']}"},
        )
        assert res_teacher_b_empty.status_code == 200
        assert res_teacher_b_empty.json() == []

        # 6. Teacher B creates Session B
        res_create_b = await client.post(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {ownership_context['teacher_b_token']}"},
            json={
                "course_name": "Machine Learning",
                "classroom_id": "ROOM_ML",
                "class_code": "DS-B",
                "start_time": "2026-09-30T10:00:00Z",
                "end_time": "2026-09-30T11:00:00Z",
                "required_presence_percentage": 75.0,
            },
        )
        assert res_create_b.status_code == 201
        session_b_id = res_create_b.json()["session_id"]

        # 7. Teacher B sees only Session B
        res_teacher_b = await client.get(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {ownership_context['teacher_b_token']}"},
        )
        assert res_teacher_b.status_code == 200
        sessions_b = res_teacher_b.json()
        assert len(sessions_b) == 1
        assert sessions_b[0]["session_id"] == session_b_id
        assert sessions_b[0]["created_by"] == "teacher_b_id"

        # 8. Teacher A still sees only Session A
        res_teacher_a_again = await client.get(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {ownership_context['teacher_a_token']}"},
        )
        assert res_teacher_a_again.status_code == 200
        sessions_a_again = res_teacher_a_again.json()
        assert len(sessions_a_again) == 1
        assert sessions_a_again[0]["session_id"] == session_a_id


@pytest.mark.anyio
async def test_get_session_details_ownership_matrix(ownership_context):
    """
    Verify GET /api/v1/sessions/{session_id}:
    - Anonymous (no token) -> 401
    - Student -> 403
    - Admin -> 403
    - Teacher B (Non-owner) -> 403
    - Nonexistent Session -> 404
    - Teacher A (Owner) -> 200 with full SessionResponse fields
    """
    transport = ASGITransport(app=app)
    session_id = ownership_context["session_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Anonymous (no token) -> 401
        res_no_auth = await client.get(f"/api/v1/sessions/{session_id}")
        assert res_no_auth.status_code == 401

        # 2. Student -> 403
        res_student = await client.get(
            f"/api/v1/sessions/{session_id}",
            headers={"Authorization": f"Bearer {ownership_context['student_token']}"},
        )
        assert res_student.status_code == 403

        # 3. Admin -> 403
        res_admin = await client.get(
            f"/api/v1/sessions/{session_id}",
            headers={"Authorization": f"Bearer {ownership_context['admin_token']}"},
        )
        # An administrator may open any session (read-only); see test_admin_session_access.py.
        assert res_admin.status_code == 200

        # 4. Teacher B (Non-owner) -> 403
        res_b = await client.get(
            f"/api/v1/sessions/{session_id}",
            headers={"Authorization": f"Bearer {ownership_context['teacher_b_token']}"},
        )
        assert res_b.status_code == 403
        assert "do not own" in res_b.json()["detail"].lower()

        # 5. Nonexistent Session -> 404
        res_404 = await client.get(
            "/api/v1/sessions/nonexistent_session_id",
            headers={"Authorization": f"Bearer {ownership_context['teacher_a_token']}"},
        )
        assert res_404.status_code == 404

        # 6. Teacher A (Owner) -> 200
        res_a = await client.get(
            f"/api/v1/sessions/{session_id}",
            headers={"Authorization": f"Bearer {ownership_context['teacher_a_token']}"},
        )
        assert res_a.status_code == 200
        body = res_a.json()
        assert body["session_id"] == session_id
        assert body["course_name"] == "Distributed Systems"
        assert body["classroom_id"] == "ROOM_A"
        assert body["required_presence_percentage"] == 75.0
        assert body["status"] == "SCHEDULED"
        assert body["created_by"] == "teacher_a_id"
        assert "start_time" in body
        assert "end_time" in body
