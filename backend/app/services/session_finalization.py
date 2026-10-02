from collections import defaultdict
from datetime import datetime

from app.database.attendance import upsert_attendance
from app.database.events import get_events_for_session
from app.schemas.attendance import AttendanceInterval, AttendanceRecord
from app.schemas.session_roster import SessionRoster
from app.services.presence_engine import (
    calculate_presence_percentage,
    calculate_session_presence,
    determine_attendance_status,
)


async def finalize_session_attendance(
    *,
    session_id: str,
    session_start: datetime,
    session_end: datetime,
    required_presence_percentage: float,
    roster: SessionRoster,
) -> list[dict]:
    events = await get_events_for_session(
        session_id=session_id,
        session_start=session_start,
        session_end=session_end,
    )

    events_by_identity: dict[str, list[dict]] = defaultdict(list)

    for event in events:
        if event["direction"] in {"ENTRY", "EXIT"}:
            ts = event["timestamp"]
            if ts.tzinfo is None and session_start.tzinfo is not None:
                event["timestamp"] = ts.replace(tzinfo=session_start.tzinfo)
            elif ts.tzinfo is not None and session_start.tzinfo is None:
                event["timestamp"] = ts.replace(tzinfo=None)
            events_by_identity[event["identity"]].append(event)

    records = []

    for identity in roster.identities:
        identity_events = events_by_identity.get(identity, [])
        presence_result = calculate_session_presence(
            identity_events,
            session_start,
            session_end,
        )

        presence_percentage = calculate_presence_percentage(
            presence_result.total_presence_seconds,
            session_start,
            session_end,
        )

        status = determine_attendance_status(
            presence_percentage,
            required_presence_percentage,
        )

        intervals = [
            AttendanceInterval(
                entry_time=interval.entry_time,
                exit_time=interval.exit_time,
            )
            for interval in presence_result.intervals
        ]

        record = AttendanceRecord(
            attendance_id=f"att_{session_id}_{identity}",
            session_id=session_id,
            identity=identity,
            presence_intervals=intervals,
            presence_duration_seconds=presence_result.total_presence_seconds,
            presence_percentage=presence_percentage,
            required_presence_percentage=required_presence_percentage,
            status=status,
        )

        stored_record = await upsert_attendance(record)
        records.append(stored_record)

    return records
