from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.database.audit import AUDIT_EVENTS_COLLECTION, ensure_audit_indexes, get_audit_events
from app.database.users import create_user
from app.main import app
from app.schemas.session_roster import SessionRoster
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from app.services.session_enrollment import enroll_session_roster


@pytest.fixture
async def setup_test_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await db["sessions"].delete_many({})
    await db["session_rosters"].delete_many({})
    await db["attendance_events"].delete_many({})
    await db["attendance_records"].delete_many({})
    await db["users"].delete_many({})
    await db[AUDIT_EVENTS_COLLECTION].delete_many({})
    await ensure_audit_indexes(db)
    yield
    await db["sessions"].delete_many({})
    await db["session_rosters"].delete_many({})
    await db["attendance_events"].delete_many({})
    await db["attendance_records"].delete_many({})
    await db["users"].delete_many({})
    await db[AUDIT_EVENTS_COLLECTION].delete_many({})


@pytest.fixture
async def teacher_auth():
    teacher_id = "teacher_att_audit_001"
    await create_user(
        user_id=teacher_id,
        email="teacher.audit@attendance.com",
        password_hash=hash_password("Password123!"),
        role="TEACHER",
    )
    token = create_access_token(user_id=teacher_id, role="TEACHER")
    return {
        "user_id": teacher_id,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture
async def other_teacher_auth():
    teacher_id = "teacher_att_audit_002"
    await create_user(
        user_id=teacher_id,
        email="other.teacher@attendance.com",
        password_hash=hash_password("Password123!"),
        role="TEACHER",
    )
    token = create_access_token(user_id=teacher_id, role="TEACHER")
    return {
        "user_id": teacher_id,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture
async def student_auth():
    student_id = "student_att_audit_001"
    await create_user(
        user_id=student_id,
        email="student.audit@attendance.com",
        password_hash=hash_password("Password123!"),
        role="STUDENT",
    )
    token = create_access_token(user_id=student_id, role="STUDENT")
    return {
        "user_id": student_id,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture
async def seeded_session_and_roster(teacher_auth):
    db = mongodb.get_database()
    session_id = "session_finalize_audit_001"
    session_doc = {
        "session_id": session_id,
        "course_name": "Operating Systems",
        "classroom_id": "ROOM_202",
        "start_time": datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
        "end_time": datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
        "required_presence_percentage": 75.0,
        "status": "SCHEDULED",
        "created_by": teacher_auth["user_id"],
        "created_at": datetime.now(timezone.utc),
    }
    await db["sessions"].insert_one(session_doc)

    await enroll_session_roster(
        session_id=session_id,
        identities=["student_01", "student_02", "student_03"],
    )

    return session_doc


# ------------------------------------------------------------------------------
# 1. ATTENDANCE_FINALIZED Audit Tests
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_teacher_finalizes_session_records_audit_event(
    setup_test_db, teacher_auth, seeded_session_and_roster
):
    transport = ASGITransport(app=app)
    session_id = seeded_session_and_roster["session_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers=teacher_auth["headers"],
        )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == session_id
    assert len(body["records"]) == 3

    events = await get_audit_events(resource_type="SESSION", resource_id=session_id)
    assert len(events) == 1

    ev = events[0]
    assert ev["audit_id"].startswith("audit_")
    assert ev["actor_user_id"] == teacher_auth["user_id"]
    assert ev["actor_role"] == "TEACHER"
    assert ev["action"] == "ATTENDANCE_FINALIZED"
    assert ev["resource_type"] == "SESSION"
    assert ev["resource_id"] == session_id
    assert ev["metadata"]["attendance_record_count"] == 3
    assert ev["metadata"]["required_presence_percentage"] == 75.0


@pytest.mark.anyio
async def test_failed_or_unauthorized_finalization_creates_no_audit_event(
    setup_test_db, teacher_auth, other_teacher_auth, student_auth, seeded_session_and_roster
):
    transport = ASGITransport(app=app)
    session_id = seeded_session_and_roster["session_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Non-owning teacher -> 403
        resp1 = await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers=other_teacher_auth["headers"],
        )
        assert resp1.status_code == 403

        # 2. Student attempt -> 403
        resp2 = await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers=student_auth["headers"],
        )
        assert resp2.status_code == 403

        # 3. Non-existent session -> 404
        resp3 = await client.post(
            "/api/v1/sessions/non_existent_session_999/finalize",
            headers=teacher_auth["headers"],
        )
        assert resp3.status_code == 404

    events = await get_audit_events(resource_type="SESSION")
    finalized_events = [e for e in events if e.get("action") == "ATTENDANCE_FINALIZED"]
    assert len(finalized_events) == 0


@pytest.mark.anyio
async def test_audit_failure_does_not_prevent_finalization(
    setup_test_db, teacher_auth, seeded_session_and_roster
):
    transport = ASGITransport(app=app)
    session_id = seeded_session_and_roster["session_id"]

    with patch(
        "app.api.routes.session_finalization.record_audit_event",
        side_effect=RuntimeError("Simulated audit database connection outage"),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/sessions/{session_id}/finalize",
                headers=teacher_auth["headers"],
            )

    # Primary business operation succeeds
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == session_id
    assert len(body["records"]) == 3


@pytest.mark.anyio
async def test_repeated_finalization_records_chronological_audit_events(
    setup_test_db, teacher_auth, seeded_session_and_roster
):
    transport = ASGITransport(app=app)
    session_id = seeded_session_and_roster["session_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp1 = await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers=teacher_auth["headers"],
        )
        assert resp1.status_code == 200

        resp2 = await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers=teacher_auth["headers"],
        )
        assert resp2.status_code == 200

    events = await get_audit_events(resource_type="SESSION", resource_id=session_id)
    assert len(events) == 2

    assert events[0]["action"] == "ATTENDANCE_FINALIZED"
    assert events[1]["action"] == "ATTENDANCE_FINALIZED"
    assert events[0]["audit_id"] != events[1]["audit_id"]
    assert events[0]["timestamp"] <= events[1]["timestamp"]
    assert events[0]["metadata"]["attendance_record_count"] == 3
    assert events[1]["metadata"]["attendance_record_count"] == 3


# ------------------------------------------------------------------------------
# 2. ATTENDANCE_CORRECTED Audit Tests
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_successful_correction_records_audit_event(
    setup_test_db, teacher_auth, seeded_session_and_roster
):
    transport = ASGITransport(app=app)
    session_id = seeded_session_and_roster["session_id"]
    attendance_id = f"att_{session_id}_student_01"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Finalize session first
        fin_resp = await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers=teacher_auth["headers"],
        )
        assert fin_resp.status_code == 200

        # 2. Submit attendance correction
        corr_payload = {
            "new_status": "PRESENT",
            "new_presence_seconds": 3000.0,
            "reason": "Student attended and verified manually by teacher.",
        }
        corr_resp = await client.patch(
            f"/api/v1/attendance/{session_id}/records/{attendance_id}",
            headers=teacher_auth["headers"],
            json=corr_payload,
        )
        assert corr_resp.status_code == 200

    # 3. Verify ATTENDANCE_CORRECTED audit event
    events = await get_audit_events(resource_type="ATTENDANCE", resource_id=attendance_id)
    assert len(events) == 1

    ev = events[0]
    assert ev["audit_id"].startswith("audit_")
    assert ev["actor_user_id"] == teacher_auth["user_id"]
    assert ev["actor_role"] == "TEACHER"
    assert ev["action"] == "ATTENDANCE_CORRECTED"
    assert ev["resource_type"] == "ATTENDANCE"
    assert ev["resource_id"] == attendance_id
    assert ev["metadata"]["session_id"] == session_id
    assert ev["metadata"]["identity"] == "student_01"
    assert ev["metadata"]["previous_status"] == "ABSENT"
    assert ev["metadata"]["new_status"] == "PRESENT"
    assert ev["metadata"]["previous_presence_seconds"] == 0.0
    assert ev["metadata"]["new_presence_seconds"] == 3000.0
    assert ev["metadata"]["reason"] == "Student attended and verified manually by teacher."


@pytest.mark.anyio
async def test_invalid_or_unauthorized_correction_creates_no_audit_event(
    setup_test_db, teacher_auth, other_teacher_auth, student_auth, seeded_session_and_roster
):
    transport = ASGITransport(app=app)
    session_id = seeded_session_and_roster["session_id"]
    attendance_id = f"att_{session_id}_student_01"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Finalize to create base attendance record
        await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers=teacher_auth["headers"],
        )

        corr_payload = {
            "new_status": "PRESENT",
            "new_presence_seconds": 3000.0,
            "reason": "Valid reason.",
        }

        # 1. Non-owning teacher -> 403
        resp1 = await client.patch(
            f"/api/v1/attendance/{session_id}/records/{attendance_id}",
            headers=other_teacher_auth["headers"],
            json=corr_payload,
        )
        assert resp1.status_code == 403

        # 2. Student caller -> 403
        resp2 = await client.patch(
            f"/api/v1/attendance/{session_id}/records/{attendance_id}",
            headers=student_auth["headers"],
            json=corr_payload,
        )
        assert resp2.status_code == 403

        # 3. Non-existent attendance record -> 404
        resp3 = await client.patch(
            f"/api/v1/attendance/{session_id}/records/non_existent_att_999",
            headers=teacher_auth["headers"],
            json=corr_payload,
        )
        assert resp3.status_code == 404

        # 4. Invalid status value -> 422
        resp4 = await client.patch(
            f"/api/v1/attendance/{session_id}/records/{attendance_id}",
            headers=teacher_auth["headers"],
            json={
                "new_status": "LATE",
                "new_presence_seconds": 1800.0,
                "reason": "Invalid status value",
            },
        )
        assert resp4.status_code == 422

        # 5. Empty reason -> 400
        resp5 = await client.patch(
            f"/api/v1/attendance/{session_id}/records/{attendance_id}",
            headers=teacher_auth["headers"],
            json={
                "new_status": "PRESENT",
                "new_presence_seconds": 1800.0,
                "reason": "   ",
            },
        )
        assert resp5.status_code == 400

    # Verify no ATTENDANCE_CORRECTED audit events were created
    events = await get_audit_events(resource_type="ATTENDANCE")
    assert len(events) == 0


@pytest.mark.anyio
async def test_audit_failure_does_not_prevent_attendance_correction(
    setup_test_db, teacher_auth, seeded_session_and_roster
):
    transport = ASGITransport(app=app)
    session_id = seeded_session_and_roster["session_id"]
    attendance_id = f"att_{session_id}_student_01"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Finalize first
        await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers=teacher_auth["headers"],
        )

        corr_payload = {
            "new_status": "PRESENT",
            "new_presence_seconds": 3200.0,
            "reason": "Resilience test verification.",
        }

        with patch(
            "app.services.attendance_correction.record_audit_event",
            side_effect=RuntimeError("Simulated audit database connection outage"),
        ):
            resp = await client.patch(
                f"/api/v1/attendance/{session_id}/records/{attendance_id}",
                headers=teacher_auth["headers"],
                json=corr_payload,
            )

    # Primary business operation succeeds
    assert resp.status_code == 200
    body = resp.json()
    assert body["new_status"] == "PRESENT"
    assert body["new_presence_seconds"] == 3200.0
    assert body["reason"] == "Resilience test verification."


@pytest.mark.anyio
async def test_multiple_corrections_record_chronological_audit_events(
    setup_test_db, teacher_auth, seeded_session_and_roster
):
    transport = ASGITransport(app=app)
    session_id = seeded_session_and_roster["session_id"]
    attendance_id = f"att_{session_id}_student_01"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Finalize
        await client.post(
            f"/api/v1/sessions/{session_id}/finalize",
            headers=teacher_auth["headers"],
        )

        # Correction 1: ABSENT -> PRESENT
        resp1 = await client.patch(
            f"/api/v1/attendance/{session_id}/records/{attendance_id}",
            headers=teacher_auth["headers"],
            json={
                "new_status": "PRESENT",
                "new_presence_seconds": 3000.0,
                "reason": "First manual correction.",
            },
        )
        assert resp1.status_code == 200

        # Correction 2: PRESENT -> ABSENT
        resp2 = await client.patch(
            f"/api/v1/attendance/{session_id}/records/{attendance_id}",
            headers=teacher_auth["headers"],
            json={
                "new_status": "ABSENT",
                "new_presence_seconds": 0.0,
                "reason": "Reverting correction after review.",
            },
        )
        assert resp2.status_code == 200

    events = await get_audit_events(resource_type="ATTENDANCE", resource_id=attendance_id)
    assert len(events) == 2

    assert events[0]["action"] == "ATTENDANCE_CORRECTED"
    assert events[1]["action"] == "ATTENDANCE_CORRECTED"
    assert events[0]["metadata"]["previous_status"] == "ABSENT"
    assert events[0]["metadata"]["new_status"] == "PRESENT"
    assert events[1]["metadata"]["previous_status"] == "PRESENT"
    assert events[1]["metadata"]["new_status"] == "ABSENT"
    assert events[0]["timestamp"] <= events[1]["timestamp"]
    assert events[0]["audit_id"] != events[1]["audit_id"]
