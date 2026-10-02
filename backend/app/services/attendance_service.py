from datetime import datetime
from uuid import uuid4

from app.database.attendance import create_attendance
from app.schemas.attendance import AttendanceInterval, AttendanceRecord
from app.services.presence_engine import (
    calculate_presence_percentage,
    calculate_session_presence,
    determine_attendance_status,
)


async def generate_attendance_record(
    *,
    session_id: str,
    identity: str,
    events: list[dict],
    session_start: datetime,
    session_end: datetime,
    required_presence_percentage: float,
) -> dict:
    """Calculate and persist attendance for one identity in one session."""

    presence_result = calculate_session_presence(
        events=events,
        session_start=session_start,
        session_end=session_end,
    )

    presence_percentage = calculate_presence_percentage(
        total_presence_seconds=presence_result.total_presence_seconds,
        session_start=session_start,
        session_end=session_end,
    )

    status = determine_attendance_status(
        presence_percentage=presence_percentage,
        required_presence_percentage=required_presence_percentage,
    )

    intervals = [
        AttendanceInterval(
            entry_time=interval.entry_time,
            exit_time=interval.exit_time,
        )
        for interval in presence_result.intervals
    ]

    record = AttendanceRecord(
        attendance_id=f"att_{uuid4().hex}",
        session_id=session_id,
        identity=identity,
        presence_intervals=intervals,
        presence_duration_seconds=presence_result.total_presence_seconds,
        presence_percentage=presence_percentage,
        required_presence_percentage=required_presence_percentage,
        status=status,
    )

    return await create_attendance(record)
