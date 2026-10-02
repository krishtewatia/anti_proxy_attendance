from datetime import datetime, timezone

from app.database.mongodb import get_database


ATTENDANCE_CORRECTIONS_COLLECTION = "attendance_corrections"


async def ensure_correction_indexes() -> None:
    """Ensure indexes on the attendance_corrections collection."""
    db = get_database()
    collection = db[ATTENDANCE_CORRECTIONS_COLLECTION]
    await collection.create_index("correction_id", unique=True)
    await collection.create_index([("attendance_id", 1), ("corrected_at", 1)])


async def create_correction(correction: dict) -> dict:
    """
    Append an immutable attendance correction record to MongoDB.

    This collection is append-only for audit integrity.
    """
    db = get_database()
    collection = db[ATTENDANCE_CORRECTIONS_COLLECTION]

    await ensure_correction_indexes()

    document = dict(correction)
    if "corrected_at" not in document:
        document["corrected_at"] = datetime.now(timezone.utc)

    await collection.insert_one(document)

    return document


async def get_corrections_for_attendance(attendance_id: str) -> list[dict]:
    """
    Retrieve all historical correction records for a specific attendance record,
    ordered chronologically (corrected_at ASC).
    """
    db = get_database()
    collection = db[ATTENDANCE_CORRECTIONS_COLLECTION]

    cursor = collection.find({"attendance_id": attendance_id}).sort("corrected_at", 1)
    return await cursor.to_list(length=None)


async def get_correction_by_id(correction_id: str) -> dict | None:
    """Retrieve a single correction by its unique correction_id."""
    db = get_database()
    collection = db[ATTENDANCE_CORRECTIONS_COLLECTION]

    return await collection.find_one({"correction_id": correction_id})
