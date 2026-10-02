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

    cursor = collection.find(
        {"session_id": session_id}
    )

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
