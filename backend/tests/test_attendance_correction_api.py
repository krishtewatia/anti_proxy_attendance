from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.database.attendance import create_attendance, get_attendance_record
from app.database.attendance_corrections import get_corrections_for_attendance
from app.database.users import create_user
from app.main import app
from app.schemas.attendance import AttendanceRecord
from app.security.jwt import create_access_token
from app.security.passwords import hash_password


@pytest.fixture(autouse=True)
async def setup_test_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await db["sessions"].delete_many({})
    await db["attendance_records"].delete_many({})
    await db["attendance_corrections"].delete_many({})
    await db["users"].delete_many({})
    yield
    await db["sessions"].delete_many({})
    await db["attendance_records"].delete_many({})
    await db["attendance_corrections"].delete_many({})
    await db["users"].delete_many({})


@pytest.fixture
async def teacher_a_headers():
    teacher_id = "teacher_a_corr"
    await create_user(
        user_id=teacher_id,
        email="teacher.a@university.edu",
        password_hash=hash_password("SecurePass123!"),
        role="TEACHER",
    )
    token = create_access_token(user_id=teacher_id, role="TEACHER")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def teacher_b_headers():
    teacher_id = "teacher_b_corr"
    await create_user(
        user_id=teacher_id,
        email="teacher.b@university.edu",
        password_hash=hash_password("SecurePass123!"),
        role="TEACHER",
    )
    token = create_access_token(user_id=teacher_id, role="TEACHER")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def student_headers():
    student_id = "student_corr_user"
    await create_user(
        user_id=student_id,
        email="student@university.edu",
        password_hash=hash_password("SecurePass123!"),
        role="STUDENT",
    )
    token = create_access_token(user_id=student_id, role="STUDENT")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def admin_headers():
    admin_id = "admin_corr_user"
    await create_user(
        user_id=admin_id,
        email="admin@university.edu",
        password_hash=hash_password("SecurePass123!"),
        role="ADMIN",
    )
    token = create_access_token(user_id=admin_id, role="ADMIN")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def sample_session_and_attendance():
    db = mongodb.get_database()
    session_id = "sess_corr_demo"
    await db["sessions"].insert_one({
        "session_id": session_id,
        "course_name": "Operating Systems",
        "classroom_id": "ROOM_101",
        "start_time": datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc),
        "end_time": datetime(2026, 10, 20, 11, 0, tzinfo=timezone.utc),
        "required_presence_percentage": 70.0,
        "status": "COMPLETED",
        "created_by": "teacher_a_corr",
    })

    att_id = "att_corr_p1"
    await create_attendance(
        AttendanceRecord(
            attendance_id=att_id,
            session_id=session_id,
            identity="person_01",
            presence_intervals=[],
            presence_duration_seconds=3000.0,
            presence_percentage=83.33,
            required_presence_percentage=70.0,
            status="PRESENT",
        )
    )

    return {"session_id": session_id, "attendance_id": att_id}


# ------------------------------------------------------------------------------
# 1. Authentication Tests
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_correction_anonymous_rejected_401(sample_session_and_attendance):
    data = sample_session_and_attendance
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            f"/api/v1/attendance/{data['session_id']}/records/{data['attendance_id']}",
            json={
                "new_status": "ABSENT",
                "new_presence_seconds": 1200.0,
                "reason": "Anonymous attempt",
            },
        )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_correction_invalid_jwt_rejected_401(sample_session_and_attendance):
    data = sample_session_and_attendance
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            f"/api/v1/attendance/{data['session_id']}/records/{data['attendance_id']}",
            headers={"Authorization": "Bearer invalid.fake.token"},
            json={
                "new_status": "ABSENT",
                "new_presence_seconds": 1200.0,
                "reason": "Invalid token attempt",
            },
        )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_correction_student_role_rejected_403(
    sample_session_and_attendance, student_headers
):
    data = sample_session_and_attendance
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            f"/api/v1/attendance/{data['session_id']}/records/{data['attendance_id']}",
            headers=student_headers,
            json={
                "new_status": "PRESENT",
                "new_presence_seconds": 3600.0,
                "reason": "Student self-correction attempt",
            },
        )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_correction_admin_role_rejected_403(
    sample_session_and_attendance, admin_headers
):
    data = sample_session_and_attendance
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            f"/api/v1/attendance/{data['session_id']}/records/{data['attendance_id']}",
            headers=admin_headers,
            json={
                "new_status": "PRESENT",
                "new_presence_seconds": 3600.0,
                "reason": "Admin correction attempt",
            },
        )
    assert resp.status_code == 403


# ------------------------------------------------------------------------------
# 2. Ownership & Authorization Tests
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_correction_other_teacher_rejected_403(
    sample_session_and_attendance, teacher_b_headers
):
    data = sample_session_and_attendance
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            f"/api/v1/attendance/{data['session_id']}/records/{data['attendance_id']}",
            headers=teacher_b_headers,
            json={
                "new_status": "ABSENT",
                "new_presence_seconds": 0.0,
                "reason": "Non-owner teacher attempting modification",
            },
        )
    assert resp.status_code == 403
    assert "own this session" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_correction_session_not_found_returns_404(teacher_a_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            "/api/v1/attendance/nonexistent_session/records/att_any",
            headers=teacher_a_headers,
            json={
                "new_status": "ABSENT",
                "new_presence_seconds": 0.0,
                "reason": "Nonexistent session attempt",
            },
        )
    assert resp.status_code == 404
    assert "session not found" in resp.json()["detail"].lower()


# ------------------------------------------------------------------------------
# 3. Attendance Isolation & Session Boundary Tests
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_correction_attendance_not_found_returns_404(
    sample_session_and_attendance, teacher_a_headers
):
    data = sample_session_and_attendance
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            f"/api/v1/attendance/{data['session_id']}/records/nonexistent_att_id",
            headers=teacher_a_headers,
            json={
                "new_status": "ABSENT",
                "new_presence_seconds": 0.0,
                "reason": "Nonexistent attendance record",
            },
        )
    assert resp.status_code == 404
    assert "attendance record not found" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_correction_cross_session_isolation_rejected_404(teacher_a_headers):
    db = mongodb.get_database()

    # Session A owned by Teacher A
    sess_a = "sess_owned_a"
    await db["sessions"].insert_one({
        "session_id": sess_a,
        "created_by": "teacher_a_corr",
    })

    # Session B (different session) with an attendance record
    sess_b = "sess_other_b"
    att_b = "att_record_in_session_b"
    await create_attendance(
        AttendanceRecord(
            attendance_id=att_b,
            session_id=sess_b,
            identity="person_victim",
            presence_intervals=[],
            presence_duration_seconds=3600.0,
            presence_percentage=100.0,
            required_presence_percentage=70.0,
            status="PRESENT",
        )
    )

    # Attack attempt: Teacher A targets their own session A URL, but passes att_b in the path
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            f"/api/v1/attendance/{sess_a}/records/{att_b}",
            headers=teacher_a_headers,
            json={
                "new_status": "ABSENT",
                "new_presence_seconds": 0.0,
                "reason": "Cross-session tampering attempt",
            },
        )

    assert resp.status_code == 404
    assert "does not belong to this session" in resp.json()["detail"]


# ------------------------------------------------------------------------------
# 4. Successful Correction Workflow
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_successful_correction_by_owner_teacher(
    sample_session_and_attendance, teacher_a_headers
):
    data = sample_session_and_attendance
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            f"/api/v1/attendance/{data['session_id']}/records/{data['attendance_id']}",
            headers=teacher_a_headers,
            json={
                "new_status": "ABSENT",
                "new_presence_seconds": 2400.0,
                "reason": "Student stepped out early without permission.",
            },
        )

    assert resp.status_code == 200
    res = resp.json()

    # Verify complete response payload
    assert res["correction_id"].startswith("corr_")
    assert res["attendance_id"] == data["attendance_id"]
    assert res["session_id"] == data["session_id"]
    assert res["identity"] == "person_01"
    assert res["corrected_by"] == "teacher_a_corr"
    assert res["previous_status"] == "PRESENT"
    assert res["new_status"] == "ABSENT"
    assert res["previous_presence_seconds"] == 3000.0
    assert res["new_presence_seconds"] == 2400.0
    assert res["reason"] == "Student stepped out early without permission."
    assert "corrected_at" in res

    # Verify updated attendance record in DB
    updated = await get_attendance_record(data["attendance_id"])
    assert updated["status"] == "ABSENT"
    assert updated["presence_duration_seconds"] == 2400.0
    # Recalculated: 2400 / 3600 * 100 = 66.67%
    assert updated["presence_percentage"] == 66.67
    assert updated["manually_corrected"] is True
    assert updated["last_corrected_by"] == "teacher_a_corr"

    # Verify audit collection record
    audit_history = await get_corrections_for_attendance(data["attendance_id"])
    assert len(audit_history) == 1
    assert audit_history[0]["correction_id"] == res["correction_id"]


# ------------------------------------------------------------------------------
# 5. Tampering Protection & Schema Validation Tests
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_correction_tampering_with_extra_fields_rejected_422(
    sample_session_and_attendance, teacher_a_headers
):
    data = sample_session_and_attendance
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            f"/api/v1/attendance/{data['session_id']}/records/{data['attendance_id']}",
            headers=teacher_a_headers,
            json={
                "new_status": "PRESENT",
                "new_presence_seconds": 2700,
                "reason": "Manual verification",
                "corrected_by": "another_teacher",
                "identity": "person_999",
                "session_id": "fake_session",
            },
        )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_correction_invalid_status_rejected_422(
    sample_session_and_attendance, teacher_a_headers
):
    data = sample_session_and_attendance
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            f"/api/v1/attendance/{data['session_id']}/records/{data['attendance_id']}",
            headers=teacher_a_headers,
            json={
                "new_status": "EXCUSED",  # invalid
                "new_presence_seconds": 2700,
                "reason": "Valid reason",
            },
        )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_correction_negative_presence_rejected_422(
    sample_session_and_attendance, teacher_a_headers
):
    data = sample_session_and_attendance
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            f"/api/v1/attendance/{data['session_id']}/records/{data['attendance_id']}",
            headers=teacher_a_headers,
            json={
                "new_status": "PRESENT",
                "new_presence_seconds": -100.0,
                "reason": "Valid reason",
            },
        )
    assert resp.status_code == 422


# ------------------------------------------------------------------------------
# 6. Read-Only Correction History Tests (Part 5)
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_corrections_anonymous_rejected_401(sample_session_and_attendance):
    data = sample_session_and_attendance
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/attendance/{data['session_id']}/records/{data['attendance_id']}/corrections"
        )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_get_corrections_invalid_jwt_rejected_401(sample_session_and_attendance):
    data = sample_session_and_attendance
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/attendance/{data['session_id']}/records/{data['attendance_id']}/corrections",
            headers={"Authorization": "Bearer invalid.fake.token"},
        )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_get_corrections_student_role_rejected_403(
    sample_session_and_attendance, student_headers
):
    data = sample_session_and_attendance
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/attendance/{data['session_id']}/records/{data['attendance_id']}/corrections",
            headers=student_headers,
        )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_get_corrections_admin_role_rejected_403(
    sample_session_and_attendance, admin_headers
):
    data = sample_session_and_attendance
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/attendance/{data['session_id']}/records/{data['attendance_id']}/corrections",
            headers=admin_headers,
        )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_get_corrections_other_teacher_rejected_403(
    sample_session_and_attendance, teacher_b_headers
):
    data = sample_session_and_attendance
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/attendance/{data['session_id']}/records/{data['attendance_id']}/corrections",
            headers=teacher_b_headers,
        )
    assert resp.status_code == 403
    assert "own this session" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_get_corrections_session_not_found_returns_404(teacher_a_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/attendance/nonexistent_session/records/att_any/corrections",
            headers=teacher_a_headers,
        )
    assert resp.status_code == 404
    assert "session not found" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_get_corrections_attendance_not_found_returns_404(
    sample_session_and_attendance, teacher_a_headers
):
    data = sample_session_and_attendance
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/attendance/{data['session_id']}/records/nonexistent_att_id/corrections",
            headers=teacher_a_headers,
        )
    assert resp.status_code == 404
    assert "attendance record not found" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_get_corrections_cross_session_isolation_rejected_404(teacher_a_headers):
    db = mongodb.get_database()

    # Session A owned by Teacher A
    sess_a = "sess_owned_a"
    await db["sessions"].insert_one({
        "session_id": sess_a,
        "created_by": "teacher_a_corr",
    })

    # Session B (different session) with an attendance record
    sess_b = "sess_other_b"
    att_b = "att_record_in_session_b"
    await create_attendance(
        AttendanceRecord(
            attendance_id=att_b,
            session_id=sess_b,
            identity="person_victim",
            presence_intervals=[],
            presence_duration_seconds=3600.0,
            presence_percentage=100.0,
            required_presence_percentage=70.0,
            status="PRESENT",
        )
    )

    # Attack attempt: Teacher A targets their session A, but passes att_b in the path
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/attendance/{sess_a}/records/{att_b}/corrections",
            headers=teacher_a_headers,
        )

    assert resp.status_code == 404
    assert "does not belong to this session" in resp.json()["detail"]


@pytest.mark.anyio
async def test_get_corrections_empty_list_when_no_corrections(
    sample_session_and_attendance, teacher_a_headers
):
    data = sample_session_and_attendance
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/attendance/{data['session_id']}/records/{data['attendance_id']}/corrections",
            headers=teacher_a_headers,
        )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.anyio
async def test_get_corrections_single_item(
    sample_session_and_attendance, teacher_a_headers
):
    data = sample_session_and_attendance
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Perform a correction
        patch_resp = await client.patch(
            f"/api/v1/attendance/{data['session_id']}/records/{data['attendance_id']}",
            headers=teacher_a_headers,
            json={
                "new_status": "ABSENT",
                "new_presence_seconds": 2400.0,
                "reason": "Student stepped out early.",
            },
        )
        assert patch_resp.status_code == 200

        # 2. Get history
        get_resp = await client.get(
            f"/api/v1/attendance/{data['session_id']}/records/{data['attendance_id']}/corrections",
            headers=teacher_a_headers,
        )

    assert get_resp.status_code == 200
    items = get_resp.json()
    assert len(items) == 1
    assert items[0]["correction_id"].startswith("corr_")
    assert items[0]["attendance_id"] == data["attendance_id"]
    assert items[0]["session_id"] == data["session_id"]
    assert items[0]["identity"] == "person_01"
    assert items[0]["corrected_by"] == "teacher_a_corr"
    assert items[0]["previous_status"] == "PRESENT"
    assert items[0]["new_status"] == "ABSENT"
    assert items[0]["previous_presence_seconds"] == 3000.0
    assert items[0]["new_presence_seconds"] == 2400.0
    assert items[0]["reason"] == "Student stepped out early."
    assert "corrected_at" in items[0]


@pytest.mark.anyio
async def test_get_corrections_multiple_returns_chronological_list(
    sample_session_and_attendance, teacher_a_headers
):
    data = sample_session_and_attendance
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First correction: PRESENT -> ABSENT
        r1 = await client.patch(
            f"/api/v1/attendance/{data['session_id']}/records/{data['attendance_id']}",
            headers=teacher_a_headers,
            json={
                "new_status": "ABSENT",
                "new_presence_seconds": 0.0,
                "reason": "Marked absent initially by mistake.",
            },
        )
        assert r1.status_code == 200

        # Second correction: ABSENT -> PRESENT
        r2 = await client.patch(
            f"/api/v1/attendance/{data['session_id']}/records/{data['attendance_id']}",
            headers=teacher_a_headers,
            json={
                "new_status": "PRESENT",
                "new_presence_seconds": 3000.0,
                "reason": "Student verified by teacher in person.",
            },
        )
        assert r2.status_code == 200

        # Fetch history
        resp = await client.get(
            f"/api/v1/attendance/{data['session_id']}/records/{data['attendance_id']}/corrections",
            headers=teacher_a_headers,
        )

    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2

    # Oldest -> newest
    assert items[0]["previous_status"] == "PRESENT"
    assert items[0]["new_status"] == "ABSENT"
    assert items[0]["reason"] == "Marked absent initially by mistake."

    assert items[1]["previous_status"] == "ABSENT"
    assert items[1]["new_status"] == "PRESENT"
    assert items[1]["reason"] == "Student verified by teacher in person."

    # Timestamps chronological
    assert items[0]["corrected_at"] <= items[1]["corrected_at"]
