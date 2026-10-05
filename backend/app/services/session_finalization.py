import logging

from app.core.config import settings
from app.database.attendance import get_attendance_by_session, upsert_attendance
from app.database.mongodb import get_database
from app.database.sessions import update_session_status
from app.schemas.attendance import AttendanceRecord
from app.schemas.session_roster import SessionRoster

logger = logging.getLogger(__name__)


async def finalize_session_attendance(
    *,
    session_id: str,
    roster: SessionRoster,
    **kwargs,
) -> list[dict]:
    """Finalize one-time attendance for a session.

    - Students recognized during the session remain PRESENT.
    - All other rostered students are finalized as ABSENT.
    - Session status is locked to 'FINALIZED'.
    - Returns the complete list of student attendance records.
    """
    db = get_database()

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

    # 2. Fetch existing records in MongoDB
    existing_records = await get_attendance_by_session(session_id)
    records_by_ident = {r["identity"]: r for r in existing_records}

    final_records = []

    for identity in roster.identities:
        s_info = student_map.get(identity, {})
        stu_id = s_info.get("student_id", identity)
        stu_name = s_info.get("name", identity)

        existing = records_by_ident.get(identity)
        current_status = existing.get("status", "ABSENT") if existing else "ABSENT"

        if current_status != "PRESENT":
            event_count = await db[settings.EVENTS_COLLECTION].count_documents(
                {
                    "$or": [
                        {"session_id": session_id, "identity": identity},
                        {"identity": identity},
                    ]
                }
            )
            if event_count > 0:
                current_status = "PRESENT"

        record = AttendanceRecord(
            attendance_id=f"att_{session_id}_{identity}",
            session_id=session_id,
            identity=identity,
            student_id=stu_id,
            student_name=stu_name,
            status=current_status,
            marked_at=existing.get("marked_at") if existing else None,
        )

        stored = await upsert_attendance(record)
        final_records.append(stored)

    # 3. Lock session as FINALIZED
    await update_session_status(session_id, "FINALIZED")
    logger.info("Session %s attendance finalized: %d total records", session_id, len(final_records))

    return final_records
