from datetime import datetime, timezone

from app.database.mongodb import get_database
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
    """Calculate overall and subject-wise attendance for a student based on finalized sessions."""
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

    overall_present = 0
    overall_total = len(all_applicable_sessions)

    subject_counts: dict[str, dict[str, int]] = {}
    history = []

    for s in all_applicable_sessions:
        s_id = s["session_id"]
        subj = s.get("subject") or s.get("course_name") or "General"
        st = att_by_session.get(s_id, "ABSENT")

        if st == "PRESENT":
            overall_present += 1

        if subj not in subject_counts:
            subject_counts[subj] = {"present": 0, "total": 0}
        subject_counts[subj]["total"] += 1
        if st == "PRESENT":
            subject_counts[subj]["present"] += 1

        dt = s.get("start_time") or s.get("created_at")
        date_str = dt.strftime("%b %d, %Y") if hasattr(dt, "strftime") else str(dt)[:10]

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

    overall_pct = round((overall_present / overall_total * 100), 1) if overall_total > 0 else 0.0

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
        "subjects": subjects_list,
        "history": history,
    }
