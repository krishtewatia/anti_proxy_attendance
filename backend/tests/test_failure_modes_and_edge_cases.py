from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.database.attendance import create_attendance, get_attendance_record
from app.database.attendance_corrections import (
    create_correction,
    get_correction_by_id,
    get_corrections_for_attendance,
)
from app.database.audit import create_audit_event
from app.database.mongodb import init_indexes
from app.database.sessions import create_session
from app.database.users import create_user
from app.main import app
from app.schemas.attendance import AttendanceRecord
from app.schemas.session import SessionCreate
from app.schemas.vision_event import VisionEventCreate
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from app.services.session_enrollment import enroll_session_roster


@pytest.fixture(autouse=True)
async def setup_test_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await init_indexes(db)
    await db["sessions"].delete_many({})
    await db["session_rosters"].delete_many({})
    await db["attendance_records"].delete_many({})
    await db["attendance_corrections"].delete_many({})
    await db["audit_events"].delete_many({})
    await db["vision_events"].delete_many({})
    await db["users"].delete_many({})
    yield
    await db["sessions"].delete_many({})
    await db["session_rosters"].delete_many({})
    await db["attendance_records"].delete_many({})
    await db["attendance_corrections"].delete_many({})
    await db["audit_events"].delete_many({})
    await db["vision_events"].delete_many({})
    await db["users"].delete_many({})


@pytest.fixture
async def teacher_a_auth():
    uid = "teacher_owner_alpha"
    await create_user(
        user_id=uid,
        email="teacher.alpha@university.edu",
        password_hash=hash_password("Pass123!"),
        role="TEACHER",
    )
    token = create_access_token(user_id=uid, role="TEACHER")
    return {"headers": {"Authorization": f"Bearer {token}"}, "user_id": uid}


@pytest.fixture
async def teacher_b_auth():
    uid = "teacher_intruder_beta"
    await create_user(
        user_id=uid,
        email="teacher.beta@university.edu",
        password_hash=hash_password("Pass123!"),
        role="TEACHER",
    )
    token = create_access_token(user_id=uid, role="TEACHER")
    return {"headers": {"Authorization": f"Bearer {token}"}, "user_id": uid}


@pytest.fixture
async def admin_auth():
    uid = "admin_super"
    await create_user(
        user_id=uid,
        email="admin@university.edu",
        password_hash=hash_password("Pass123!"),
        role="ADMIN",
    )
    token = create_access_token(user_id=uid, role="ADMIN")
    return {"headers": {"Authorization": f"Bearer {token}"}, "user_id": uid}


@pytest.fixture
async def student_auth():
    uid = "student_regular"
    await create_user(
        user_id=uid,
        email="student@university.edu",
        password_hash=hash_password("Pass123!"),
        role="STUDENT",
    )
    token = create_access_token(user_id=uid, role="STUDENT")
    return {"headers": {"Authorization": f"Bearer {token}"}, "user_id": uid}


# =============================================================================
# 1. Cross-Teacher Ownership Isolation Across All Endpoints
# =============================================================================

@pytest.mark.anyio
async def test_cross_teacher_ownership_isolation_all_endpoints(
    teacher_a_auth, teacher_b_auth
):
    """Verifies Teacher B receives 403 Forbidden across all operations on Teacher A's session."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Teacher A creates a session
        session_doc = await create_session(
            SessionCreate(
                course_name="Quantum Computing 501",
                classroom_id="ROOM_404",
                start_time=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
                end_time=datetime(2026, 10, 1, 10, 30, tzinfo=timezone.utc),
                required_presence_percentage=75.0,
            ),
            created_by=teacher_a_auth["user_id"],
        )
        session_id = session_doc["session_id"]

        # Teacher A enrolls roster
        await enroll_session_roster(session_id, ["student_01", "student_02"])

        # Create attendance record owned by Session A
        att = await create_attendance(
            AttendanceRecord(
                attendance_id="att_test_own_01",
                session_id=session_id,
                identity="student_01",
                presence_intervals=[],
                presence_duration_seconds=3600.0,
                presence_percentage=80.0,
                required_presence_percentage=75.0,
                status="PRESENT",
            )
        )
        att_id = att["attendance_id"]

        # 1. Teacher B tries to GET roster -> 403
        resp_roster_get = await client.get(
            f"/api/v1/sessions/{session_id}/roster",
            headers=teacher_b_auth["headers"],
        )
        assert resp_roster_get.status_code == 403
        assert "Forbidden" in resp_roster_get.json()["detail"]

        # 2. Teacher B tries to POST roster -> 403
        resp_roster_post = await client.post(
            f"/api/v1/sessions/{session_id}/roster",
            json={"identities": ["student_03"]},
            headers=teacher_b_auth["headers"],
        )
        assert resp_roster_post.status_code == 403

        # 3. Teacher B tries to GET live-snapshot -> 403
        resp_live = await client.get(
            f"/api/v1/sessions/{session_id}/live-snapshot",
            headers=teacher_b_auth["headers"],
        )
        assert resp_live.status_code == 403

        # 4. Teacher B tries to POST finalize -> 403
        resp_finalize = await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers=teacher_b_auth["headers"],
        )
        assert resp_finalize.status_code == 403

        # 5. Teacher B tries to PATCH attendance record -> 403
        resp_corr = await client.patch(
            f"/api/v1/attendance/{session_id}/records/{att_id}",
            json={
                "new_status": "ABSENT",
                "new_presence_seconds": 0.0,
                "reason": "Unauthorized manual modification attempt",
            },
            headers=teacher_b_auth["headers"],
        )
        assert resp_corr.status_code == 403


# =============================================================================
# 2. Audit Trail Scoping, Visibility, and RBAC Edge Cases
# =============================================================================

@pytest.mark.anyio
async def test_audit_visibility_teacher_scoping_and_attendance_lookup(
    teacher_a_auth, teacher_b_auth, admin_auth, student_auth
):
    """
    Tests audit visibility:
    - Teacher querying ATTENDANCE audit gets 403 if session belongs to another teacher.
    - Teacher querying general audit list sees only own sessions/attendance.
    - Student querying audit is forbidden (403).
    - Admin querying non-existent resource gets 404.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create session for Teacher A
        s_a = await create_session(
            SessionCreate(
                course_name="Machine Learning 101",
                classroom_id="ROOM_A",
                start_time=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
                end_time=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
                required_presence_percentage=75.0,
            ),
            created_by=teacher_a_auth["user_id"],
        )
        s_a_id = s_a["session_id"]

        att_a = await create_attendance(
            AttendanceRecord(
                attendance_id="att_test_audit_01",
                session_id=s_a_id,
                identity="student_alpha",
                presence_intervals=[],
                presence_duration_seconds=3000.0,
                presence_percentage=83.3,
                required_presence_percentage=75.0,
                status="PRESENT",
            )
        )
        att_a_id = att_a["attendance_id"]

        # Log audit event for Teacher A attendance correction
        await create_audit_event(
            {
                "audit_id": "audit_test_corr_01",
                "actor_user_id": teacher_a_auth["user_id"],
                "actor_role": "TEACHER",
                "resource_type": "ATTENDANCE",
                "resource_id": att_a_id,
                "action": "ATTENDANCE_CORRECTED",
                "timestamp": datetime.now(timezone.utc),
                "metadata": {"session_id": s_a_id, "note": "Adjusted due to early signoff"},
            }
        )

        # 1. Student requests audit -> 403
        resp_student = await client.get("/api/v1/audit", headers=student_auth["headers"])
        assert resp_student.status_code == 403

        # 2. Teacher B queries audit for Teacher A's attendance record -> 403
        resp_t_b_att = await client.get(
            f"/api/v1/audit?resource_type=ATTENDANCE&resource_id={att_a_id}",
            headers=teacher_b_auth["headers"],
        )
        assert resp_t_b_att.status_code == 403
        assert "Forbidden" in resp_t_b_att.json()["detail"]

        # 3. Teacher B queries general audit list -> receives empty list (cannot see Teacher A events)
        resp_t_b_list = await client.get(
            "/api/v1/audit",
            headers=teacher_b_auth["headers"],
        )
        assert resp_t_b_list.status_code == 200
        assert len(resp_t_b_list.json()) == 0

        # 4. Teacher A queries general audit list -> receives own audit event
        resp_t_a_list = await client.get(
            "/api/v1/audit",
            headers=teacher_a_auth["headers"],
        )
        assert resp_t_a_list.status_code == 200
        assert len(resp_t_a_list.json()) == 1
        assert resp_t_a_list.json()[0]["resource_id"] == att_a_id

        # 5. Admin queries non-existent resource_id -> 404
        resp_admin_404 = await client.get(
            "/api/v1/audit?resource_type=SESSION&resource_id=nonexistent_session_999",
            headers=admin_auth["headers"],
        )
        assert resp_admin_404.status_code == 404

        # 6. Admin queries all audit events -> 200 with complete audit trail
        resp_admin_all = await client.get(
            "/api/v1/audit",
            headers=admin_auth["headers"],
        )
        assert resp_admin_all.status_code == 200
        assert len(resp_admin_all.json()) == 1


# =============================================================================
# 3. Correction Immutability & Audit Trail Preservation
# =============================================================================

@pytest.mark.anyio
async def test_correction_immutability_and_history_preservation(teacher_a_auth):
    """
    Verifies that multiple corrections on the same attendance record:
    1. Update the parent attendance document.
    2. Maintain an append-only, immutable history in attendance_corrections.
    3. Old correction records are never modified or overwritten.
    4. get_correction_by_id returns exact immutable historical snapshot.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create session & initial attendance record
        session_doc = await create_session(
            SessionCreate(
                course_name="Security Engineering",
                classroom_id="LAB_1",
                start_time=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
                end_time=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
                required_presence_percentage=75.0,
            ),
            created_by=teacher_a_auth["user_id"],
        )
        session_id = session_doc["session_id"]

        att = await create_attendance(
            AttendanceRecord(
                attendance_id="att_test_corr_immut_01",
                session_id=session_id,
                identity="alice_cooper",
                presence_intervals=[],
                presence_duration_seconds=3000.0,
                presence_percentage=83.3,
                required_presence_percentage=75.0,
                status="PRESENT",
            )
        )
        att_id = att["attendance_id"]

        # First correction: change to ABSENT
        resp_corr_1 = await client.patch(
            f"/api/v1/attendance/{session_id}/records/{att_id}",
            json={
                "new_status": "ABSENT",
                "new_presence_seconds": 1200.0,
                "reason": "Left room early during lecture",
            },
            headers=teacher_a_auth["headers"],
        )
        assert resp_corr_1.status_code == 200
        corr_1_id = resp_corr_1.json()["correction_id"]

        # Second correction: change back to PRESENT with manual override
        resp_corr_2 = await client.patch(
            f"/api/v1/attendance/{session_id}/records/{att_id}",
            json={
                "new_status": "PRESENT",
                "new_presence_seconds": 2800.0,
                "reason": "Teacher confirmed excused laboratory task",
            },
            headers=teacher_a_auth["headers"],
        )
        assert resp_corr_2.status_code == 200
        corr_2_id = resp_corr_2.json()["correction_id"]
        assert corr_1_id != corr_2_id

        # Verify historical records via direct database lookup
        hist_1 = await get_correction_by_id(corr_1_id)
        assert hist_1 is not None
        assert hist_1["previous_status"] == "PRESENT"
        assert hist_1["new_status"] == "ABSENT"
        assert hist_1["previous_presence_seconds"] == 3000.0
        assert hist_1["new_presence_seconds"] == 1200.0
        assert hist_1["reason"] == "Left room early during lecture"

        hist_2 = await get_correction_by_id(corr_2_id)
        assert hist_2 is not None
        assert hist_2["previous_status"] == "ABSENT"
        assert hist_2["new_status"] == "PRESENT"
        assert hist_2["previous_presence_seconds"] == 1200.0
        assert hist_2["new_presence_seconds"] == 2800.0
        assert hist_2["reason"] == "Teacher confirmed excused laboratory task"

        # Verify chronology in full list
        all_corrs = await get_corrections_for_attendance(att_id)
        assert len(all_corrs) == 2
        assert all_corrs[0]["correction_id"] == corr_1_id
        assert all_corrs[1]["correction_id"] == corr_2_id


# =============================================================================
# 4. Strict Event Validation & Rejecting Malformed Sensory Payloads
# =============================================================================

@pytest.mark.anyio
async def test_strict_event_validation_edge_cases():
    """Validates boundary conditions on vision sensory input."""
    # Negative track ID rejected
    with pytest.raises(ValueError):
        VisionEventCreate(
            event_id="evt_valid_123",
            camera_id="CAM_TEST_1",
            track_id=-1,
            direction="ENTRY",
            identity="person_01",
            confidence=0.95,
            timestamp=datetime.now(timezone.utc),
        )

    # Invalid direction rejected
    with pytest.raises(ValueError):
        VisionEventCreate(
            event_id="evt_valid_124",
            camera_id="CAM_TEST_1",
            track_id=1,
            direction="STATIONARY",
            identity="person_01",
            confidence=0.95,
            timestamp=datetime.now(timezone.utc),
        )

    # Confidence out of bounds (> 1.0) rejected
    with pytest.raises(ValueError):
        VisionEventCreate(
            event_id="evt_valid_125",
            camera_id="CAM_TEST_1",
            track_id=1,
            direction="ENTRY",
            identity="person_01",
            confidence=1.5,
            timestamp=datetime.now(timezone.utc),
        )

    # Extra unknown fields strictly rejected (extra='forbid')
    with pytest.raises(ValueError):
        VisionEventCreate(
            event_id="evt_valid_126",
            camera_id="CAM_TEST_1",
            track_id=1,
            direction="ENTRY",
            identity="person_01",
            confidence=0.95,
            timestamp=datetime.now(timezone.utc),
            malicious_field="injection_attempt",
        )
