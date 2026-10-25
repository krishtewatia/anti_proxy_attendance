"""Who may register, and what a student agrees to before giving photos.

Pilot rules:

* Once the academic structure exists (a term has been created, for example by
  "Create the pilot structure"), students and teachers register only with an
  address at the college email domain (an administrator setting). Before
  that, any address is accepted, as on a development database.
* Students are known by their roll number, which is unique. The student ID
  and teacher ID are internal keys made up by the system; nobody types them.
  Photos, face templates and attendance stay keyed by the internal ID, so a
  corrected roll number is a single change.
* Before a student sends a photo of their own face they acknowledge a short
  information notice. The version they accepted is recorded. An administrator
  creating an account with a photo takes that responsibility instead.

There is no "forgot password": an administrator resets passwords.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Optional
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

CONSENTS = "consents"

# Changing the notice text means a new version: students accept it again
# before their next photo.
CONSENT_NOTICE_VERSION = "pilot-2026-10"
CONSENT_NOTICE = {
    "version": CONSENT_NOTICE_VERSION,
    "title": "Before you add your photo",
    "points": [
        "What is collected: the photos you add here, and a face template (a list of numbers) "
        "worked out from them.",
        "Why: only to mark your attendance in this pilot of the attendance system, run with the "
        "permission of the college.",
        "Who can see it: the administrators of this system, and the teachers who teach you (your "
        "photo and your attendance). Nobody can see or download the face template.",
        "How long: until the end of the pilot, then deleted. You can ask an administrator to "
        "delete your photos and face template at any time; you are then marked by hand.",
    ],
}

ROLL_NUMBER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9/_.\-]*$"
_ROLL_RE = re.compile(ROLL_NUMBER_PATTERN)


class RegistrationRuleError(ValueError):
    """A registration that breaks one of the rules above."""


def new_student_key() -> str:
    return f"stu_{uuid4().hex[:12]}"


def new_teacher_key() -> str:
    return f"tch_{uuid4().hex[:12]}"


def clean_roll_number(value: str) -> str:
    roll = (value or "").strip()
    if not roll or not _ROLL_RE.match(roll):
        raise RegistrationRuleError(
            "Enter your roll number using letters, digits, '/', '.', '_' or '-'."
        )
    return roll


async def college_email_domain(db: AsyncIOMotorDatabase) -> Optional[str]:
    """The domain registrations must use, or None while no structure exists yet."""
    from app.services.organisation_service import TERMS, get_settings

    if await db[TERMS].count_documents({}, limit=1) == 0:
        return None
    return (await get_settings(db))["college_email_domain"]


async def check_email_allowed(db: AsyncIOMotorDatabase, email: str) -> None:
    domain = await college_email_domain(db)
    if domain is None:
        return
    if not (email or "").strip().lower().endswith(f"@{domain}"):
        raise RegistrationRuleError(f"Use your college email address (ending in @{domain}).")


async def check_roll_number_free(
    db: AsyncIOMotorDatabase, roll_number: str, *, exclude_user_id: Optional[str] = None
) -> None:
    """Roll numbers are compared without regard to case or surrounding spaces."""
    pattern = f"^\\s*{re.escape(roll_number)}\\s*$"
    query: dict = {"roll_number": {"$regex": pattern, "$options": "i"}}
    if exclude_user_id:
        query["user_id"] = {"$ne": exclude_user_id}
    taken = await db["student_profiles"].find_one(query, {"_id": 1})
    if taken is not None:
        raise RegistrationRuleError(f"Roll number {roll_number} is already registered.")


def check_consent_version(version: Optional[str]) -> None:
    if version != CONSENT_NOTICE_VERSION:
        raise RegistrationRuleError(
            "Read the notice about your photo and tick that you accept it before adding a photo."
        )


async def record_consent(db: AsyncIOMotorDatabase, user_id: str, version: str) -> dict:
    now = datetime.now(timezone.utc)
    await db[CONSENTS].update_one(
        {"user_id": user_id, "notice_version": version},
        {"$setOnInsert": {"user_id": user_id, "notice_version": version, "accepted_at": now}},
        upsert=True,
    )
    return await consent_status(db, user_id)


async def consent_status(db: AsyncIOMotorDatabase, user_id: str) -> dict:
    current = await db[CONSENTS].find_one(
        {"user_id": user_id, "notice_version": CONSENT_NOTICE_VERSION}, {"_id": 0}
    )
    return {
        "accepted": current is not None,
        "accepted_at": current["accepted_at"] if current else None,
        "notice": CONSENT_NOTICE,
    }
