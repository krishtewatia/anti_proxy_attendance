"""Teacher database operations for Profiles, Class/Subject Assignments."""

from datetime import datetime, timezone
from typing import Any

from app.database.mongodb import get_database

TEACHER_PROFILES_COLLECTION = "teacher_profiles"


async def upsert_teacher_profile(
    *,
    user_id: str,
    teacher_id: str,
    name: str,
    email: str,
    department: str,
    assigned_classes: list[str] | None = None,
    assigned_subjects: list[str] | None = None,
) -> dict[str, Any]:
    """Insert or update a teacher's academic profile."""
    db = get_database()
    coll = db[TEACHER_PROFILES_COLLECTION]
    now = datetime.now(timezone.utc)

    doc = {
        "user_id": user_id,
        "teacher_id": teacher_id,
        "name": name,
        "email": email.lower(),
        "department": department,
        "assigned_classes": assigned_classes or [],
        "assigned_subjects": assigned_subjects or [],
        "updated_at": now,
    }

    await coll.update_one(
        {"user_id": user_id},
        {
            "$set": doc,
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    return await coll.find_one({"user_id": user_id}, {"_id": 0})


async def get_teacher_profile_by_user_id(user_id: str) -> dict[str, Any] | None:
    """Retrieve teacher profile by auth user_id."""
    db = get_database()
    return await db[TEACHER_PROFILES_COLLECTION].find_one({"user_id": user_id}, {"_id": 0})


async def get_teacher_profile_by_teacher_id(teacher_id: str) -> dict[str, Any] | None:
    """Retrieve teacher profile by college teacher_id (e.g. T001)."""
    db = get_database()
    return await db[TEACHER_PROFILES_COLLECTION].find_one({"teacher_id": teacher_id}, {"_id": 0})


async def list_all_teachers() -> list[dict[str, Any]]:
    """Retrieve all teacher profiles."""
    db = get_database()
    cursor = db[TEACHER_PROFILES_COLLECTION].find({}, {"_id": 0}).sort("name", 1)
    return await cursor.to_list(length=None)


async def assign_classes_to_teacher(
    teacher_id: str,
    assigned_classes: list[str],
    assigned_subjects: list[str],
) -> dict[str, Any] | None:
    """Update assigned classes and subjects for a teacher."""
    db = get_database()
    coll = db[TEACHER_PROFILES_COLLECTION]
    now = datetime.now(timezone.utc)

    result = await coll.update_one(
        {"$or": [{"teacher_id": teacher_id}, {"user_id": teacher_id}]},
        {
            "$set": {
                "assigned_classes": assigned_classes,
                "assigned_subjects": assigned_subjects,
                "updated_at": now,
            }
        },
    )
    if result.matched_count == 0:
        return None

    return await coll.find_one(
        {"$or": [{"teacher_id": teacher_id}, {"user_id": teacher_id}]},
        {"_id": 0},
    )


async def delete_teacher_profile(user_id: str) -> bool:
    """Delete teacher profile."""
    db = get_database()
    res = await db[TEACHER_PROFILES_COLLECTION].delete_one({"user_id": user_id})
    return res.deleted_count > 0
