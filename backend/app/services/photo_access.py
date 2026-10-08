"""Who may view a student's profile photo.

A profile photo is biometric data. It may be viewed by:

* the student it belongs to;
* an administrator;
* a teacher who teaches that student: the student's class is one of the
  teacher's assigned classes, or the student is on the roster of a session
  the teacher created.

Everyone else is refused, whether or not the student exists, so the route
cannot be used to find out which student IDs are real.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase


async def find_student_profile(db: AsyncIOMotorDatabase, student_id: str) -> dict[str, Any] | None:
    return await db["student_profiles"].find_one(
        {"$or": [{"student_id": student_id}, {"identity": student_id}]}
    )


def _student_keys(student_id: str, profile: dict[str, Any] | None) -> set[str]:
    """Every identifier under which this student can appear on a roster."""
    keys = {student_id}
    if profile:
        for field in ("student_id", "identity"):
            value = profile.get(field)
            if value:
                keys.add(str(value))
    return keys


async def _teacher_teaches_student(
    db: AsyncIOMotorDatabase,
    teacher_user_id: str,
    student_keys: set[str],
    profile: dict[str, Any] | None,
) -> bool:
    # 1. The student's class is assigned to this teacher.
    class_code = str((profile or {}).get("class_code") or "").strip().upper()
    if class_code:
        teacher_profile = await db["teacher_profiles"].find_one({"user_id": teacher_user_id}) or {}
        assigned = {str(c).strip().upper() for c in teacher_profile.get("assigned_classes") or []}
        if class_code in assigned:
            return True

    # 2. The student is on the roster of one of this teacher's sessions.
    session_ids = [
        doc["session_id"]
        async for doc in db["sessions"].find({"created_by": teacher_user_id}, {"session_id": 1})
        if doc.get("session_id")
    ]
    if not session_ids:
        return False
    roster = await db["session_rosters"].find_one(
        {"session_id": {"$in": session_ids}, "identities": {"$in": sorted(student_keys)}},
        {"_id": 1},
    )
    return roster is not None


async def can_view_student_photo(
    db: AsyncIOMotorDatabase,
    current_user: dict[str, Any],
    student_id: str,
    profile: dict[str, Any] | None,
) -> bool:
    role = current_user.get("role")
    user_id = current_user.get("user_id")
    if not user_id:
        return False

    if role == "ADMIN":
        return True
    if role == "STUDENT":
        return profile is not None and profile.get("user_id") == user_id
    if role == "TEACHER":
        return await _teacher_teaches_student(
            db, user_id, _student_keys(student_id, profile), profile
        )
    return False
