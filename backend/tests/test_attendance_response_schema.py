import pytest
from pydantic import ValidationError

from app.schemas.attendance_response import (
    AttendanceSessionResponse,
    AttendanceSummaryItem,
)


def test_valid_attendance_session_response():
    response = AttendanceSessionResponse(
        session_id="session_001",
        records=[
            AttendanceSummaryItem(
                attendance_id="att_001",
                identity="person_01",
                presence_duration_seconds=3000,
                presence_percentage=83.33,
                required_presence_percentage=75.0,
                status="PRESENT",
            )
        ],
    )

    assert response.session_id == "session_001"
    assert len(response.records) == 1
    assert response.records[0].identity == "person_01"


def test_empty_attendance_records_are_allowed():
    response = AttendanceSessionResponse(
        session_id="session_001",
        records=[],
    )

    assert response.records == []


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        AttendanceSummaryItem(
            attendance_id="att_001",
            identity="person_01",
            presence_duration_seconds=3000,
            presence_percentage=83.33,
            required_presence_percentage=75.0,
            status="PRESENT",
            created_at="should_not_be_exposed",
        )
