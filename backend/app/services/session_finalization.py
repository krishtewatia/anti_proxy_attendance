import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional

from app.database.attendance import get_attendance_by_session, upsert_attendance
from app.database.events import get_events_for_session
from app.database.mongodb import get_database
from app.database.sessions import get_session, update_session_status
from app.schemas.attendance import AttendanceInterval, AttendanceRecord
from app.schemas.session_roster import SessionRoster
from app.services.presence_engine import (
    calculate_presence_percentage,
    calculate_session_presence,
    determine_attendance_status,
)

logger = logging.getLogger(__name__)


async def finalize_session_attendance(
    *,
    session_id: str,
    roster: SessionRoster,
    session_start: Optional[datetime] = None,
    session_end: Optional[datetime] = None,
    required_presence_percentage: Optional[float] = None,
) -> list[dict]:
    """Finalize attendance for one session.

    Every lookup is scoped to ``session_id``; evidence from any other session
    (attendance records or doorway events) never affects the result.

    - A student marked PRESENT by one-time recognition in this session, or
      manually corrected in this session, keeps that status.
    - Otherwise status comes from this session's doorway ENTRY/EXIT events
      via the presence engine.
    - Rostered students with no evidence in this session are ABSENT.
    - Session status is locked to 'FINALIZED'.
    """
    db = get_database()

    # Fall back to the stored session window when the caller did not pass one
    if session_start is None or session_end is None or required_presence_percentage is None:
        session = await get_session(session_id)
        if session:
            session_start = session_start or session.get("start_time")
            session_end = session_end or session.get("end_time")
            if required_presence_percentage is None:
                required_presence_percentage = session.get("required_presence_percentage")
    if required_presence_percentage is None:
        required_presence_percentage = 100.0

    # A zero-length or inverted window has no measurable doorway presence
    has_window = (
        session_start is not None and session_end is not None and session_end > session_start
    )

    # 1. Fetch student profiles for human-friendly metadata
    cursor = db["student_profiles"].find({})
    student_docs = await cursor.to_list(length=None)
    student_map = {
        d.get("identity"): {
            "student_id": d.get("student_id", d.get("identity")),
            "name": d.get("name", d.get("identity")),
        }
        for d in student_docs
        if d.get("identity")
    }

    # 2. One-time-mark records belonging to this session only
    existing_records = await get_attendance_by_session(session_id)
    records_by_ident = {r["identity"]: r for r in existing_records}

    # 3. Doorway events belonging to this session only
    events_by_identity: dict[str, list[dict]] = defaultdict(list)
    if has_window:
        # Strictly session-scoped: an event without this session_id is never
        # attributed by time window, so concurrent sessions cannot share events.
        events = await get_events_for_session(session_id)
        for event in events:
            if event.get("direction") in {"ENTRY", "EXIT"}:
                ts = event["timestamp"]
                if ts.tzinfo is None and session_start.tzinfo is not None:
                    event["timestamp"] = ts.replace(tzinfo=session_start.tzinfo)
                elif ts.tzinfo is not None and session_start.tzinfo is None:
                    event["timestamp"] = ts.replace(tzinfo=None)
                events_by_identity[event["identity"]].append(event)

    final_records = []

    for identity in roster.identities:
        s_info = student_map.get(identity, {})
        stu_id = s_info.get("student_id", identity)
        stu_name = s_info.get("name", identity)

        existing = records_by_ident.get(identity)

        # Manual corrections are authoritative and must survive re-finalization
        if existing and existing.get("manually_corrected"):
            # The row keeps its status; the ID and name shown are the current ones.
            final_records.append({**existing, "student_id": stu_id, "student_name": stu_name})
            continue

        intervals: list[AttendanceInterval] = []
        presence_seconds = 0.0
        presence_percentage = 0.0
        requires_review = False
        anomalies: list[str] = []
        status = "ABSENT"

        if has_window:
            presence_result = calculate_session_presence(
                events_by_identity.get(identity, []),
                session_start,
                session_end,
            )
            presence_seconds = presence_result.total_presence_seconds
            presence_percentage = calculate_presence_percentage(
                presence_seconds,
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
            requires_review = presence_result.requires_review
            anomalies = list(presence_result.anomalies)

        # One-time recognition in this session marks the student PRESENT
        marked_at = existing.get("marked_at") if existing else None
        if existing and existing.get("status") == "PRESENT" and marked_at is not None:
            status = "PRESENT"

        record = AttendanceRecord(
            attendance_id=f"att_{session_id}_{identity}",
            session_id=session_id,
            identity=identity,
            student_id=stu_id,
            student_name=stu_name,
            status=status,
            marked_at=marked_at,
            presence_intervals=intervals,
            presence_duration_seconds=presence_seconds,
            presence_percentage=presence_percentage,
            required_presence_percentage=required_presence_percentage,
            requires_review=requires_review,
            anomalies=anomalies,
        )

        stored = await upsert_attendance(record)
        final_records.append(stored)

    # 4. Lock session as FINALIZED
    await update_session_status(session_id, "FINALIZED")
    logger.info("Session %s attendance finalized: %d total records", session_id, len(final_records))

    return final_records
