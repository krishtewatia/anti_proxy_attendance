from datetime import datetime, timedelta, timezone

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.database.attendance import create_attendance
from app.database.sessions import create_session
from app.database.users import create_user
from app.main import app
from app.schemas.attendance import AttendanceInterval, AttendanceRecord
from app.schemas.session import SessionCreate
from app.security.config import JWT_ALGORITHM, JWT_SECRET_KEY
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from app.services.session_enrollment import enroll_session_roster
from tests.conftest import assign_teacher_classes


@pytest.fixture(autouse=True)
async def setup_test_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await db["sessions"].delete_many({})
    await db["session_rosters"].delete_many({})
    await db["attendance_events"].delete_many({})
    await db["attendance_records"].delete_many({})
    await db["users"].delete_many({})
    yield
    await db["sessions"].delete_many({})
    await db["session_rosters"].delete_many({})
    await db["attendance_events"].delete_many({})
    await db["attendance_records"].delete_many({})
    await db["users"].delete_many({})


@pytest.fixture
async def rbac_fixture():
    pw_hash = hash_password("Password123!")

    teacher = await create_user(
        user_id="user_teacher_rbac",
        email="teacher.rbac@test.com",
        password_hash=pw_hash,
        role="TEACHER",
    )
    await assign_teacher_classes("user_teacher_rbac")
    student = await create_user(
        user_id="user_student_rbac",
        email="student.rbac@test.com",
        password_hash=pw_hash,
        role="STUDENT",
    )
    admin = await create_user(
        user_id="user_admin_rbac",
        email="admin.rbac@test.com",
        password_hash=pw_hash,
        role="ADMIN",
    )
    inactive = await create_user(
        user_id="user_inactive_rbac",
        email="inactive.rbac@test.com",
        password_hash=pw_hash,
        role="TEACHER",
    )
    await assign_teacher_classes("user_inactive_rbac")

    db = mongodb.get_database()
    await db["users"].update_one(
        {"user_id": "user_inactive_rbac"},
        {"$set": {"is_active": False}},
    )

    # Pre-seed a session with roster and attendance record for testing
    session = SessionCreate(
        course_name="Security 101",
        classroom_id="ROOM_SEC",
        start_time=datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 9, 29, 11, 0, tzinfo=timezone.utc),
        required_presence_percentage=75.0,
    )
    created_session = await create_session(session, created_by="user_teacher_rbac")
    session_id = created_session["session_id"]

    await enroll_session_roster(
        session_id=session_id,
        identities=["student_01", "student_02"],
    )

    record = AttendanceRecord(
        attendance_id=f"att_{session_id}_student_01",
        session_id=session_id,
        identity="student_01",
        presence_intervals=[],
        presence_duration_seconds=0,
        presence_percentage=0,
        required_presence_percentage=75.0,
        status="ABSENT",
    )
    await create_attendance(record)

    teacher_token = create_access_token(user_id="user_teacher_rbac", role="TEACHER")
    student_token = create_access_token(user_id="user_student_rbac", role="STUDENT")
    admin_token = create_access_token(user_id="user_admin_rbac", role="ADMIN")
    inactive_token = create_access_token(user_id="user_inactive_rbac", role="TEACHER")

    return {
        "session_id": session_id,
        "teacher_token": teacher_token,
        "student_token": student_token,
        "admin_token": admin_token,
        "inactive_token": inactive_token,
    }


# =========================================================================
# Authentication Layer Tests (401 Expected)
# =========================================================================

@pytest.mark.anyio
async def test_endpoint_no_token_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/sessions", json={})

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.anyio
async def test_endpoint_malformed_token_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/sessions",
            headers={"Authorization": "Bearer malformed.token.value"},
            json={},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired token"


@pytest.mark.anyio
async def test_endpoint_expired_token_returns_401():
    past_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    expired_payload = {
        "sub": "user_teacher_rbac",
        "role": "TEACHER",
        "iat": past_time - timedelta(minutes=60),
        "exp": past_time,
    }
    expired_token = jwt.encode(
        expired_payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {expired_token}"},
            json={},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired token"


@pytest.mark.anyio
async def test_endpoint_tampered_token_returns_401(rbac_fixture):
    token = rbac_fixture["teacher_token"]
    parts = token.split(".")
    tampered_sig = parts[2][:-4] + "abcd" if len(parts[2]) > 4 else "abcd"
    tampered_token = f"{parts[0]}.{parts[1]}.{tampered_sig}"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {tampered_token}"},
            json={},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired token"


@pytest.mark.anyio
async def test_endpoint_nonexistent_user_token_returns_401():
    token = create_access_token(user_id="user_nonexistent_999", role="TEACHER")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "User account is unavailable"


@pytest.mark.anyio
async def test_endpoint_inactive_user_token_returns_401(rbac_fixture):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {rbac_fixture['inactive_token']}"},
            json={},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "User account is unavailable"


# =========================================================================
# Explicit RBAC Matrix for Teacher-Protected Application Endpoints
# =========================================================================

@pytest.mark.anyio
async def test_rbac_create_session(rbac_fixture):
    transport = ASGITransport(app=app)
    payload = {
        "course_name": "DevSecOps",
        "classroom_id": "ROOM_101",
        "class_code": "DS-B",
        "start_time": "2026-09-29T10:00:00Z",
        "end_time": "2026-09-29T11:00:00Z",
        "required_presence_percentage": 75.0,
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # No Token -> 401
        res_no_auth = await client.post("/api/v1/sessions", json=payload)
        assert res_no_auth.status_code == 401

        # STUDENT -> 403
        res_student = await client.post(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {rbac_fixture['student_token']}"},
            json=payload,
        )
        assert res_student.status_code == 403

        # ADMIN -> 403
        res_admin = await client.post(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {rbac_fixture['admin_token']}"},
            json=payload,
        )
        assert res_admin.status_code == 403

        # TEACHER -> 201
        res_teacher = await client.post(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {rbac_fixture['teacher_token']}"},
            json=payload,
        )
        assert res_teacher.status_code == 201


@pytest.mark.anyio
async def test_rbac_manage_roster_update(rbac_fixture):
    transport = ASGITransport(app=app)
    session_id = rbac_fixture["session_id"]
    payload = {"identities": ["student_01", "student_02"]}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # No Token -> 401
        res_no_auth = await client.post(f"/api/v1/sessions/{session_id}/roster", json=payload)
        assert res_no_auth.status_code == 401

        # STUDENT -> 403
        res_student = await client.post(
            f"/api/v1/sessions/{session_id}/roster",
            headers={"Authorization": f"Bearer {rbac_fixture['student_token']}"},
            json=payload,
        )
        assert res_student.status_code == 403

        # ADMIN -> 403
        res_admin = await client.post(
            f"/api/v1/sessions/{session_id}/roster",
            headers={"Authorization": f"Bearer {rbac_fixture['admin_token']}"},
            json=payload,
        )
        assert res_admin.status_code == 403

        # TEACHER -> 200
        res_teacher = await client.post(
            f"/api/v1/sessions/{session_id}/roster",
            headers={"Authorization": f"Bearer {rbac_fixture['teacher_token']}"},
            json=payload,
        )
        assert res_teacher.status_code == 200


@pytest.mark.anyio
async def test_rbac_get_roster(rbac_fixture):
    transport = ASGITransport(app=app)
    session_id = rbac_fixture["session_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # No Token -> 401
        res_no_auth = await client.get(f"/api/v1/sessions/{session_id}/roster")
        assert res_no_auth.status_code == 401

        # STUDENT -> 403
        res_student = await client.get(
            f"/api/v1/sessions/{session_id}/roster",
            headers={"Authorization": f"Bearer {rbac_fixture['student_token']}"},
        )
        assert res_student.status_code == 403

        # ADMIN -> 403
        res_admin = await client.get(
            f"/api/v1/sessions/{session_id}/roster",
            headers={"Authorization": f"Bearer {rbac_fixture['admin_token']}"},
        )
        assert res_admin.status_code == 403

        # TEACHER -> 200
        res_teacher = await client.get(
            f"/api/v1/sessions/{session_id}/roster",
            headers={"Authorization": f"Bearer {rbac_fixture['teacher_token']}"},
        )
        assert res_teacher.status_code == 200


@pytest.mark.anyio
async def test_rbac_finalize_session(rbac_fixture):
    transport = ASGITransport(app=app)
    session_id = rbac_fixture["session_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # No Token -> 401
        res_no_auth = await client.post(f"/api/v1/sessions/{session_id}/finalize")
        assert res_no_auth.status_code == 401

        # STUDENT -> 403
        res_student = await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers={"Authorization": f"Bearer {rbac_fixture['student_token']}"},
        )
        assert res_student.status_code == 403

        # ADMIN -> 403
        res_admin = await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers={"Authorization": f"Bearer {rbac_fixture['admin_token']}"},
        )
        assert res_admin.status_code == 403

        # TEACHER -> 200
        res_teacher = await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers={"Authorization": f"Bearer {rbac_fixture['teacher_token']}"},
        )
        assert res_teacher.status_code == 200


@pytest.mark.anyio
async def test_rbac_get_attendance(rbac_fixture):
    transport = ASGITransport(app=app)
    session_id = rbac_fixture["session_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # No Token -> 401
        res_no_auth = await client.get(f"/api/v1/attendance/{session_id}")
        assert res_no_auth.status_code == 401

        # STUDENT -> 403
        res_student = await client.get(
            f"/api/v1/attendance/{session_id}",
            headers={"Authorization": f"Bearer {rbac_fixture['student_token']}"},
        )
        assert res_student.status_code == 403

        # ADMIN -> 403
        res_admin = await client.get(
            f"/api/v1/attendance/{session_id}",
            headers={"Authorization": f"Bearer {rbac_fixture['admin_token']}"},
        )
        assert res_admin.status_code == 403

        # TEACHER -> 200
        res_teacher = await client.get(
            f"/api/v1/attendance/{session_id}",
            headers={"Authorization": f"Bearer {rbac_fixture['teacher_token']}"},
        )
        assert res_teacher.status_code == 200


@pytest.mark.anyio
async def test_rbac_enforces_mongodb_role_over_forged_jwt(rbac_fixture):
    # Student creates a forged token with role "TEACHER"
    forged_token = create_access_token(user_id="user_student_rbac", role="TEACHER")

    transport = ASGITransport(app=app)
    session_id = rbac_fixture["session_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Access teacher-protected attendance endpoint
        response = await client.get(
            f"/api/v1/attendance/{session_id}",
            headers={"Authorization": f"Bearer {forged_token}"},
        )

    # Must be 403 Forbidden because MongoDB confirms this user's true role is STUDENT
    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient permissions"
