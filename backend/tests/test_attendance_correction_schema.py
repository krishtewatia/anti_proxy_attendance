from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from app.schemas.attendance_correction import (
    AttendanceCorrectionCreate,
    AttendanceCorrectionResponse,
)


def test_valid_attendance_correction_create():
    correction = AttendanceCorrectionCreate(
        new_status="PRESENT",
        new_presence_seconds=2400.0,
        reason="Manual camera occlusion review confirmed presence.",
    )

    assert correction.new_status == "PRESENT"
    assert correction.new_presence_seconds == 2400.0
    assert correction.reason == "Manual camera occlusion review confirmed presence."


def test_attendance_correction_create_invalid_status():
    with pytest.raises(ValidationError):
        AttendanceCorrectionCreate(
            new_status="EXCUSED",  # only PRESENT or ABSENT allowed
            new_presence_seconds=1200.0,
            reason="Medical note",
        )


def test_attendance_correction_create_negative_presence_rejected():
    with pytest.raises(ValidationError):
        AttendanceCorrectionCreate(
            new_status="ABSENT",
            new_presence_seconds=-5.0,  # ge=0 constraint
            reason="Correction",
        )


def test_attendance_correction_create_empty_reason_rejected():
    with pytest.raises(ValidationError):
        AttendanceCorrectionCreate(
            new_status="PRESENT",
            new_presence_seconds=100.0,
            reason="",  # min_length=1 constraint
        )


def test_attendance_correction_create_forbids_extra_fields():
    # Security: Client cannot submit internal audit fields in request payload
    with pytest.raises(ValidationError):
        AttendanceCorrectionCreate(
            new_status="PRESENT",
            new_presence_seconds=3000.0,
            reason="Valid explanation",
            corrected_by="malicious_user",  # Extra field must be rejected
        )


def test_valid_attendance_correction_response():
    now = datetime.now(timezone.utc)
    response = AttendanceCorrectionResponse(
        correction_id="corr_001",
        attendance_id="att_001",
        session_id="sess_001",
        identity="person_01",
        corrected_by="teacher_001",
        previous_status="ABSENT",
        new_status="PRESENT",
        previous_presence_seconds=0.0,
        new_presence_seconds=3000.0,
        reason="Teacher manual verification after video review",
        corrected_at=now,
    )

    assert response.correction_id == "corr_001"
    assert response.corrected_by == "teacher_001"
    assert response.previous_status == "ABSENT"
    assert response.new_status == "PRESENT"
    assert response.corrected_at == now
