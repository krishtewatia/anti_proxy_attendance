from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.attendance import (
    AttendanceInterval,
    AttendanceRecord,
)


def test_valid_attendance_record():
    record = AttendanceRecord(
        attendance_id="att_001",
        session_id="session_001",
        identity="person_01",
        presence_intervals=[
            AttendanceInterval(
                entry_time=datetime(
                    2026, 9, 29, 10, 0, tzinfo=timezone.utc
                ),
                exit_time=datetime(
                    2026, 9, 29, 10, 50, tzinfo=timezone.utc
                ),
            )
        ],
        presence_duration_seconds=3000,
        presence_percentage=83.33,
        required_presence_percentage=75.0,
        status="PRESENT",
    )

    assert record.identity == "person_01"
    assert record.presence_duration_seconds == 3000
    assert record.status == "PRESENT"


def test_invalid_attendance_status():
    with pytest.raises(ValidationError):
        AttendanceRecord(
            attendance_id="att_001",
            session_id="session_001",
            identity="person_01",
            presence_intervals=[],
            presence_duration_seconds=3000,
            presence_percentage=83.33,
            required_presence_percentage=75.0,
            status="UNKNOWN",
        )


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        AttendanceRecord(
            attendance_id="att_001",
            session_id="session_001",
            identity="person_01",
            presence_intervals=[],
            presence_duration_seconds=3000,
            presence_percentage=83.33,
            required_presence_percentage=75.0,
            status="PRESENT",
            proxy_flag=True,
        )
