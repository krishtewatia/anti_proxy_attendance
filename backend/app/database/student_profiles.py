from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.database.mongodb import get_database

STUDENT_PROFILES_COLLECTION = "student_profiles"


class DuplicateStudentProfileRecordError(Exception):
    """Raised when a student profile violates a unique constraint (user_id or identity)."""


async def create_student_profile(
    *,
    user_id: str,
    identity: str,
) -> dict:
    """Create and persist a student profile document."""
    db = get_database()
    collection = db[STUDENT_PROFILES_COLLECTION]

    document = {
        "user_id": user_id,
        "identity": identity,
        "created_at": datetime.now(timezone.utc),
    }

    try:
        await collection.insert_one(document)
    except DuplicateKeyError as exc:
        raise DuplicateStudentProfileRecordError(
            "Student profile with this user_id or identity already exists"
        ) from exc

    return document


async def get_student_profile_by_user_id(user_id: str) -> dict | None:
    """Find a student profile by user_id."""
    db = get_database()
    collection = db[STUDENT_PROFILES_COLLECTION]

    return await collection.find_one({"user_id": user_id})


async def get_student_profile_by_identity(identity: str) -> dict | None:
    """Find a student profile by student identity."""
    db = get_database()
    collection = db[STUDENT_PROFILES_COLLECTION]

    return await collection.find_one({"identity": identity})
