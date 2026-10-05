"""Student profile database operations for Multi-Role Attendance Management."""

from datetime import datetime, timezone
import re
from typing import Any

from pymongo.errors import DuplicateKeyError

from app.database.mongodb import get_database

STUDENT_PROFILES_COLLECTION = "student_profiles"


class DuplicateStudentProfileRecordError(Exception):
    """Raised when a student profile violates a unique constraint."""


def normalize_class_code(branch: str, section: str) -> str:
    """Derive standard class code like DS-B, CS-A, AIML-B from branch and section."""
    branch_clean = branch.strip()
    sec_clean = section.strip().upper()

    # Map standard branch names to acronyms if needed
    acronyms = {
        "Data Science": "DS",
        "Computer Science": "CS",
        "AI & ML": "AIML",
        "Artificial Intelligence": "AI",
        "Information Technology": "IT",
    }
    prefix = acronyms.get(branch_clean)
    if not prefix:
        words = re.findall(r"[A-Za-z]+", branch_clean)
        prefix = "".join(w[0].upper() for w in words) if words else branch_clean.upper()

    return f"{prefix}-{sec_clean}"


async def create_student_profile(
    *,
    user_id: str,
    identity: str,
) -> dict[str, Any]:
    """Legacy helper: Create student profile document with minimal fields."""
    db = get_database()
    coll = db[STUDENT_PROFILES_COLLECTION]
    now = datetime.now(timezone.utc)

    doc = {
        "user_id": user_id,
        "identity": identity,
        "student_id": identity,
        "name": identity.replace("_", " ").title(),
        "created_at": now,
        "updated_at": now,
    }

    try:
        await coll.insert_one(doc)
    except DuplicateKeyError as exc:
        raise DuplicateStudentProfileRecordError(
            "Student profile with this user_id or identity already exists"
        ) from exc

    return doc


async def upsert_student_profile(
    *,
    user_id: str,
    identity: str,
    name: str,
    email: str,
    student_id: str,
    roll_number: str,
    branch: str,
    section: str,
    class_code: str | None = None,
    photo_base64: str | None = None,
    has_biometric: bool = False,
) -> dict[str, Any]:
    """Create or update full student profile with academic grouping."""
    db = get_database()
    coll = db[STUDENT_PROFILES_COLLECTION]
    now = datetime.now(timezone.utc)

    computed_class_code = class_code or normalize_class_code(branch, section)

    doc = {
        "user_id": user_id,
        "identity": identity,
        "name": name,
        "email": email.lower(),
        "student_id": student_id,
        "roll_number": roll_number,
        "branch": branch,
        "section": section.upper(),
        "class_code": computed_class_code,
        "has_biometric": has_biometric,
        "updated_at": now,
    }
    if photo_base64:
        doc["photo_base64"] = photo_base64

    await coll.update_one(
        {"user_id": user_id},
        {
            "$set": doc,
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    return await coll.find_one({"user_id": user_id}, {"_id": 0})


async def get_student_profile_by_user_id(user_id: str) -> dict[str, Any] | None:
    """Find a student profile by user_id."""
    db = get_database()
    return await db[STUDENT_PROFILES_COLLECTION].find_one({"user_id": user_id}, {"_id": 0})


async def get_student_profile_by_identity(identity: str) -> dict[str, Any] | None:
    """Find a student profile by student identity or student_id."""
    db = get_database()
    return await db[STUDENT_PROFILES_COLLECTION].find_one(
        {"$or": [{"identity": identity}, {"student_id": identity}]},
        {"_id": 0},
    )


async def get_students_by_class(
    *,
    class_code: str | None = None,
    branch: str | None = None,
    section: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve all students enrolled in a specific class / branch + section."""
    db = get_database()
    query: dict[str, Any] = {}

    if class_code:
        # Match class_code directly or derive branch/section
        query["$or"] = [
            {"class_code": class_code.upper()},
            {"class_code": class_code},
        ]
        # Also handle potential branch/section query if class_code is like "DS-B"
        if "-" in class_code:
            parts = class_code.split("-", 1)
            prefix, sec = parts[0].upper(), parts[1].upper()
            branch_map = {
                "DS": "Data Science",
                "CS": "Computer Science",
                "AIML": "AI & ML",
                "IT": "Information Technology",
            }
            if prefix in branch_map:
                query["$or"].append({"branch": branch_map[prefix], "section": sec})
    elif branch and section:
        query = {
            "branch": branch,
            "section": section.upper(),
        }
    elif branch:
        query = {"branch": branch}

    cursor = db[STUDENT_PROFILES_COLLECTION].find(query, {"_id": 0}).sort("roll_number", 1)
    return await cursor.to_list(length=None)


async def list_all_students_full() -> list[dict[str, Any]]:
    """Retrieve all student profiles across all classes."""
    db = get_database()
    cursor = db[STUDENT_PROFILES_COLLECTION].find({}, {"_id": 0}).sort("name", 1)
    return await cursor.to_list(length=None)


async def update_biometric_status(identity: str, has_biometric: bool) -> bool:
    """Update biometric registration flag for student."""
    db = get_database()
    res = await db[STUDENT_PROFILES_COLLECTION].update_many(
        {"$or": [{"identity": identity}, {"student_id": identity}]},
        {"$set": {"has_biometric": has_biometric, "updated_at": datetime.now(timezone.utc)}},
    )
    return res.modified_count > 0


async def delete_student_profile(user_id: str) -> bool:
    """Delete a student profile by user_id."""
    db = get_database()
    res = await db[STUDENT_PROFILES_COLLECTION].delete_one({"user_id": user_id})
    return res.deleted_count > 0
