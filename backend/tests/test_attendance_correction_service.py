from datetime import datetime, timezone
import pytest
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.database.attendance import (
    ATTENDANCE_COLLECTION,
    create_attendance,
    get_attendance_record,
)
from app.database.attendance_corrections import (
    ATTENDANCE_CORRECTIONS_COLLECTION,
    get_corrections_for_attendance,
)
from app.database.sessions import SESSIONS_COLLECTION
from app.schemas.attendance import AttendanceRecord
from app.services.attendance_correction import (
    AttendanceNotFoundError,
    correct_attendance,
    get_correction_history,
)


@pytest.fixture(autouse=True)
def setup_mock_db():
    mongodb._client = AsyncMongoMockClient()
    yield
    mongodb._client = None


@pytest.mark.anyio
async def test_correction_audit_record_created_and_attendance_updated():
    db = mongodb.get_database()

    # 1. Provision 1-hour session (10:00 to 11:00 UTC = 3600 seconds)
    session_id = "sess_demo_01"
    await db[SESSIONS_COLLECTION].insert_one({
        "session_id": session_id,
        "course_name": "Distributed Systems",
        "classroom_id": "ROOM_101",
        "start_time": datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc),
        "end_time": datetime(2026, 10, 20, 11, 0, tzinfo=timezone.utc),
        "required_presence_percentage": 70.0,
        "status": "COMPLETED",
        "created_by": "teacher_001",
    })

    # 2. Provision initial attendance record
    att_id = "att_sess_demo_01_person_01"
    initial_record = AttendanceRecord(
        attendance_id=att_id,
        session_id=session_id,
        identity="person_01",
        presence_intervals=[],
        presence_duration_seconds=3000.0,
        presence_percentage=83.33,
        required_presence_percentage=70.0,
        status="PRESENT",
    )
    await create_attendance(initial_record)

    # 3. Teacher applies correction: 3000s -> 2400s (ABSENT)
    correction = await correct_attendance(
        attendance_id=att_id,
        new_status="ABSENT",
        new_presence_seconds=2400.0,
        reason="Student left 20 minutes before class concluded.",
        corrected_by="teacher_001",
    )

    # 4. Verify correction response contains complete audit trail
    assert correction.correction_id.startswith("corr_")
    assert correction.attendance_id == att_id
    assert correction.session_id == session_id
    assert correction.identity == "person_01"
    assert correction.corrected_by == "teacher_001"
    assert correction.previous_status == "PRESENT"
    assert correction.new_status == "ABSENT"
    assert correction.previous_presence_seconds == 3000.0
    assert correction.new_presence_seconds == 2400.0
    assert correction.reason == "Student left 20 minutes before class concluded."
    assert correction.corrected_at is not None

    # 5. Verify current attendance record updated in MongoDB
    updated_attendance = await get_attendance_record(att_id)
    assert updated_attendance is not None
    assert updated_attendance["status"] == "ABSENT"
    assert updated_attendance["presence_duration_seconds"] == 2400.0
    # 2400 / 3600 * 100 = 66.67%
    assert updated_attendance["presence_percentage"] == 66.67
    assert updated_attendance["manually_corrected"] is True
    assert updated_attendance["last_corrected_by"] == "teacher_001"
    assert updated_attendance["last_correction_id"] == correction.correction_id

    # 6. Verify immutable audit document in attendance_corrections collection
    audit_docs = await get_corrections_for_attendance(att_id)
    assert len(audit_docs) == 1
    stored_audit = audit_docs[0]
    assert stored_audit["correction_id"] == correction.correction_id
    assert stored_audit["previous_status"] == "PRESENT"
    assert stored_audit["new_status"] == "ABSENT"
    assert stored_audit["previous_presence_seconds"] == 3000.0
    assert stored_audit["new_presence_seconds"] == 2400.0
    assert stored_audit["previous_presence_percentage"] == 83.33
    assert stored_audit["new_presence_percentage"] == 66.67
    assert stored_audit["reason"] == "Student left 20 minutes before class concluded."


@pytest.mark.anyio
async def test_recalculation_and_manual_status_override():
    db = mongodb.get_database()

    # 1-hour session = 3600 seconds
    session_id = "sess_override_01"
    await db[SESSIONS_COLLECTION].insert_one({
        "session_id": session_id,
        "course_name": "Algorithms",
        "classroom_id": "LAB_1",
        "start_time": datetime(2026, 10, 20, 14, 0, tzinfo=timezone.utc),
        "end_time": datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc),
        "required_presence_percentage": 75.0,
    })

    att_id = "att_override_01"
    await create_attendance(
        AttendanceRecord(
            attendance_id=att_id,
            session_id=session_id,
            identity="person_02",
            presence_intervals=[],
            presence_duration_seconds=0.0,
            presence_percentage=0.0,
            required_presence_percentage=75.0,
            status="ABSENT",
        )
    )

    # Teacher manually overrides to PRESENT with 1800s (50% < 75% required)
    # Authority to override status while keeping calculated percentage consistent
    await correct_attendance(
        attendance_id=att_id,
        new_status="PRESENT",
        new_presence_seconds=1800.0,
        reason="Excused early departure for athletic competition.",
        corrected_by="teacher_coach",
    )

    updated = await get_attendance_record(att_id)
    assert updated["status"] == "PRESENT"
    assert updated["presence_duration_seconds"] == 1800.0
    # 1800 / 3600 * 100 = 50.0%
    assert updated["presence_percentage"] == 50.0
    assert updated["manually_corrected"] is True


@pytest.mark.anyio
async def test_multiple_corrections_produce_multiple_audit_records():
    db = mongodb.get_database()

    session_id = "sess_multi_01"
    await db[SESSIONS_COLLECTION].insert_one({
        "session_id": session_id,
        "start_time": datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc),
        "end_time": datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc),
    })

    att_id = "att_multi_01"
    await create_attendance(
        AttendanceRecord(
            attendance_id=att_id,
            session_id=session_id,
            identity="person_03",
            presence_intervals=[],
            presence_duration_seconds=0.0,
            presence_percentage=0.0,
            required_presence_percentage=70.0,
            status="ABSENT",
        )
    )

    # 1st Correction: ABSENT -> PRESENT (1800s)
    corr1 = await correct_attendance(
        attendance_id=att_id,
        new_status="PRESENT",
        new_presence_seconds=1800.0,
        reason="First review by TA.",
        corrected_by="ta_alex",
    )

    # 2nd Correction: PRESENT -> PRESENT (3600s full credit)
    corr2 = await correct_attendance(
        attendance_id=att_id,
        new_status="PRESENT",
        new_presence_seconds=3600.0,
        reason="Second review by Professor confirmed full period present.",
        corrected_by="prof_dumbledore",
    )

    history = await get_correction_history(att_id)
    assert len(history) == 2

    # Check 1st audit entry
    assert history[0].correction_id == corr1.correction_id
    assert history[0].previous_status == "ABSENT"
    assert history[0].new_status == "PRESENT"
    assert history[0].previous_presence_seconds == 0.0
    assert history[0].new_presence_seconds == 1800.0
    assert history[0].corrected_by == "ta_alex"

    # Check 2nd audit entry
    assert history[1].correction_id == corr2.correction_id
    assert history[1].previous_status == "PRESENT"
    assert history[1].new_status == "PRESENT"
    assert history[1].previous_presence_seconds == 1800.0
    assert history[1].new_presence_seconds == 3600.0
    assert history[1].corrected_by == "prof_dumbledore"

    # Check latest attendance record in DB
    latest_att = await get_attendance_record(att_id)
    assert latest_att["presence_duration_seconds"] == 3600.0
    assert latest_att["presence_percentage"] == 100.0
    assert latest_att["last_corrected_by"] == "prof_dumbledore"


@pytest.mark.anyio
async def test_invalid_attendance_id_rejected():
    with pytest.raises((ValueError, AttendanceNotFoundError)):
        await correct_attendance(
            attendance_id="att_does_not_exist",
            new_status="PRESENT",
            new_presence_seconds=1000.0,
            reason="Valid reason",
            corrected_by="teacher_001",
        )


@pytest.mark.anyio
async def test_negative_duration_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        await correct_attendance(
            attendance_id="att_any",
            new_status="PRESENT",
            new_presence_seconds=-50.0,
            reason="Valid reason",
            corrected_by="teacher_001",
        )


@pytest.mark.anyio
async def test_invalid_status_rejected():
    with pytest.raises(ValueError, match="Invalid status"):
        await correct_attendance(
            attendance_id="att_any",
            new_status="EXCUSED",
            new_presence_seconds=100.0,
            reason="Valid reason",
            corrected_by="teacher_001",
        )


@pytest.mark.anyio
async def test_empty_reason_rejected():
    with pytest.raises(ValueError, match="non-empty reason"):
        await correct_attendance(
            attendance_id="att_any",
            new_status="PRESENT",
            new_presence_seconds=100.0,
            reason="   ",
            corrected_by="teacher_001",
        )


@pytest.mark.anyio
async def test_empty_corrected_by_rejected():
    with pytest.raises(ValueError, match="corrected_by must be provided"):
        await correct_attendance(
            attendance_id="att_any",
            new_status="PRESENT",
            new_presence_seconds=100.0,
            reason="Valid reason",
            corrected_by="",
        )
