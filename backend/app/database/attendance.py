from datetime import datetime, timezone

from app.database.mongodb import get_database
from app.database.sessions import session_was_taken
from app.schemas.attendance import AttendanceRecord


ATTENDANCE_COLLECTION = "attendance_records"


async def create_attendance(record: AttendanceRecord) -> dict:
    """Persist an attendance record in MongoDB."""

    db = get_database()
    collection = db[ATTENDANCE_COLLECTION]

    document = record.model_dump()

    document["created_at"] = datetime.now(timezone.utc)

    await collection.insert_one(document)

    return document


async def upsert_attendance(record: AttendanceRecord) -> dict:
    db = get_database()
    collection = db[ATTENDANCE_COLLECTION]

    document = record.model_dump()
    document["updated_at"] = datetime.now(timezone.utc)

    await collection.update_one(
        {
            "session_id": record.session_id,
            "identity": record.identity,
        },
        {
            "$set": document,
        },
        upsert=True,
    )

    stored_record = await collection.find_one(
        {
            "session_id": record.session_id,
            "identity": record.identity,
        }
    )

    return stored_record


async def get_attendance_by_session(
    session_id: str,
) -> list[dict]:
    """Return all attendance records belonging to a session."""

    db = get_database()
    collection = db[ATTENDANCE_COLLECTION]

    cursor = collection.find({"session_id": session_id})

    records = await cursor.to_list(length=None)

    return records


async def get_attendance_record(
    attendance_id: str,
) -> dict | None:
    """Retrieve a single attendance record by attendance_id."""

    db = get_database()
    collection = db[ATTENDANCE_COLLECTION]

    return await collection.find_one({"attendance_id": attendance_id})


async def update_attendance_record(
    attendance_id: str,
    update_fields: dict,
) -> dict | None:
    """Update fields of an attendance record and return the updated document."""

    db = get_database()
    collection = db[ATTENDANCE_COLLECTION]

    fields = dict(update_fields)
    fields["updated_at"] = datetime.now(timezone.utc)

    await collection.update_one(
        {"attendance_id": attendance_id},
        {"$set": fields},
    )

    return await collection.find_one({"attendance_id": attendance_id})


async def update_attendance_status(
    attendance_id: str,
    status: str,
) -> dict | None:
    """Manually update attendance status (PRESENT <-> ABSENT)."""
    db = get_database()
    collection = db[ATTENDANCE_COLLECTION]
    now = datetime.now(timezone.utc)

    await collection.update_one(
        {"attendance_id": attendance_id},
        {"$set": {"status": status.upper(), "updated_at": now}},
    )
    return await collection.find_one({"attendance_id": attendance_id})


async def compute_student_attendance_metrics(
    identity: str,
    class_code: str,
) -> dict:
    """Calculate overall and subject-wise attendance for a student.

    Only sessions in which attendance was actually taken are counted. A
    session that was never taken appears in the history as NOT_TAKEN and is
    left out of every total and percentage.
    """
    db = get_database()

    # 1. Find all applicable sessions (matching student class_code or where student is in roster)
    sess_query = {
        "$or": [
            {"class_code": class_code.upper()},
            {"class_code": class_code},
        ]
    }
    sessions_cursor = db["sessions"].find(sess_query).sort("created_at", -1)
    sessions = await sessions_cursor.to_list(length=None)

    # Also check if student was rostered in any sessions without class_code
    roster_cursor = db["session_rosters"].find({"identities": identity})
    rostered_sessions = await roster_cursor.to_list(length=None)
    rostered_ids = {r["session_id"] for r in rostered_sessions}

    # Merge unique sessions
    session_map = {s["session_id"]: s for s in sessions}
    for r_id in rostered_ids:
        if r_id not in session_map:
            extra_s = await db["sessions"].find_one({"session_id": r_id})
            if extra_s:
                session_map[r_id] = extra_s

    all_applicable_sessions = list(session_map.values())
    all_applicable_sessions.sort(key=lambda s: s.get("created_at") or datetime.min, reverse=True)

    # 2. Fetch all attendance records for this student
    att_cursor = db[ATTENDANCE_COLLECTION].find({"identity": identity})
    records = await att_cursor.to_list(length=None)
    att_by_session = {r["session_id"]: r.get("status", "ABSENT") for r in records}

    # Whether a session was taken depends on everybody's records, not only
    # this student's.
    session_records: dict[str, list[dict]] = {}
    async for rec in db[ATTENDANCE_COLLECTION].find(
        {"session_id": {"$in": [s["session_id"] for s in all_applicable_sessions]}},
        {"session_id": 1, "status": 1, "marked_at": 1, "manually_corrected": 1},
    ):
        session_records.setdefault(rec["session_id"], []).append(rec)

    overall_present = 0
    overall_total = 0
    not_taken = 0

    subject_counts: dict[str, dict[str, int]] = {}
    history = []

    for s in all_applicable_sessions:
        s_id = s["session_id"]
        subj = s.get("subject") or s.get("course_name") or "General"
        if session_was_taken(s, session_records.get(s_id, [])):
            st = att_by_session.get(s_id, "ABSENT")
            overall_total += 1
            counts = subject_counts.setdefault(subj, {"present": 0, "total": 0})
            counts["total"] += 1
            if st == "PRESENT":
                overall_present += 1
                counts["present"] += 1
        else:
            st = "NOT_TAKEN"
            not_taken += 1

        dt = s.get("start_time") or s.get("created_at")
        date_str = f"{dt.day} {dt:%b %Y}" if hasattr(dt, "strftime") else str(dt)[:10]

        history.append(
            {
                "session_id": s_id,
                "course_name": s.get("course_name", subj),
                "subject": subj,
                "class_code": s.get("class_code") or class_code,
                "date_str": date_str,
                "status": st,
            }
        )

    # None when no session has been taken: there is nothing to be short of.
    overall_pct = round((overall_present / overall_total * 100), 1) if overall_total > 0 else None

    subjects_list = []
    for subj_name, counts in sorted(subject_counts.items()):
        tot = counts["total"]
        pres = counts["present"]
        pct = round((pres / tot * 100), 1) if tot > 0 else 0.0
        subjects_list.append(
            {
                "subject": subj_name,
                "present": pres,
                "total": tot,
                "percentage": pct,
            }
        )

    return {
        "overall_present": overall_present,
        "overall_total": overall_total,
        "overall_percentage": overall_pct,
        "sessions_not_taken": not_taken,
        "subjects": subjects_list,
        "history": history,
    }
