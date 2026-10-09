"""Complete, audited deletion of a student.

Deleting a student removes everything the system holds about them:

* the user account and the student profile;
* the enrolled face template;
* the stored profile photo;
* their attendance records and the corrections made to them;
* their doorway (entry/exit) events;
* their entries on session rosters.

One audit entry records who deleted whom and how much was removed. The entry
holds the student's ID and counts only, never the name, email or any image
data, so the audit trail does not keep the personal data that was deleted.
The vision service is asked to reload its gallery so the face stops being
recognized straight away.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
from typing import Any

import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import settings
from app.core.uploads import pending_photo_path, student_photo_path
from app.services.audit_service import record_audit_event
from app.services.vision_client import vision_service_headers

logger = logging.getLogger(__name__)


class StudentNotFound(Exception):
    """No student account or profile exists for this user ID."""


class NotAStudentAccount(Exception):
    """The user ID belongs to an account that is not a student."""


@dataclass(frozen=True)
class StudentDeletionResult:
    user_id: str
    student_id: str
    account_deleted: bool
    profile_deleted: bool
    face_templates_deleted: int
    photo_files_deleted: int
    attendance_records_deleted: int
    attendance_corrections_deleted: int
    doorway_events_deleted: int
    roster_entries_removed: int
    vision_gallery_refreshed: bool

    def counts(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("user_id")
        data.pop("student_id")
        return data


def _delete_photo_files(keys: set[str]) -> int:
    removed = 0
    for key in sorted(keys):
        try:
            path = student_photo_path(key)
        except ValueError:
            continue  # not usable as a file name, so no photo was ever stored under it
        try:
            if path.is_file():
                path.unlink()
                removed += 1
        except OSError as exc:
            logger.warning(
                "Could not delete a stored photo during student deletion: %s", type(exc).__name__
            )
    return removed


async def _refresh_vision_gallery() -> bool:
    """Ask the vision service to drop the deleted face now. Best effort."""
    url = f"{settings.VISION_SERVICE_URL.rstrip('/')}/reload-gallery"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(url, json={}, headers=vision_service_headers())
        return response.status_code == 200
    except httpx.HTTPError as exc:
        # The gallery is also re-read from the backend periodically, so the
        # face disappears there within the refresh window even if this fails.
        logger.warning(
            "Vision gallery was not refreshed after a student deletion: %s", type(exc).__name__
        )
        return False


async def delete_student_completely(
    db: AsyncIOMotorDatabase, user_id: str, *, deleted_by: dict[str, Any]
) -> StudentDeletionResult:
    """Remove everything held about one student and record a single audit entry."""
    user = await db["users"].find_one({"user_id": user_id})
    profile = await db["student_profiles"].find_one({"user_id": user_id})
    if user is None and profile is None:
        raise StudentNotFound(user_id)
    # This route must never be a way to delete a teacher or an administrator.
    if user is not None and user.get("role") != "STUDENT":
        raise NotAStudentAccount(user_id)

    keys = {
        str(v) for v in ((profile or {}).get("identity"), (profile or {}).get("student_id")) if v
    }
    student_id = str(
        (profile or {}).get("student_id") or (profile or {}).get("identity") or user_id
    )
    key_list = sorted(keys)

    templates = attendance = corrections = events = roster_entries = 0
    if key_list:
        templates = (
            await db["biometric_profiles"].delete_many({"identity": {"$in": key_list}})
        ).deleted_count

        by_student = {"$or": [{"identity": {"$in": key_list}}, {"student_id": {"$in": key_list}}]}
        attendance = (await db["attendance_records"].delete_many(by_student)).deleted_count
        corrections = (
            await db["attendance_corrections"].delete_many({"identity": {"$in": key_list}})
        ).deleted_count
        events = (
            await db[settings.EVENTS_COLLECTION].delete_many({"identity": {"$in": key_list}})
        ).deleted_count

        async for roster in db["session_rosters"].find(
            {"identities": {"$in": key_list}}, {"identities": 1}
        ):
            roster_entries += sum(
                1 for identity in roster.get("identities", []) if identity in keys
            )
        await db["session_rosters"].update_many(
            {"identities": {"$in": key_list}}, {"$pull": {"identities": {"$in": key_list}}}
        )

    photos = _delete_photo_files(keys)
    if key_list:
        await db["photo_change_requests"].delete_many({"identity": {"$in": key_list}})
        for key in key_list:
            try:
                waiting = pending_photo_path(key)
                if waiting.is_file():
                    waiting.unlink()
                    photos += 1
            except (ValueError, OSError):
                pass
    profile_deleted = (
        await db["student_profiles"].delete_one({"user_id": user_id})
    ).deleted_count > 0
    account_deleted = (await db["users"].delete_one({"user_id": user_id})).deleted_count > 0
    gallery_refreshed = await _refresh_vision_gallery() if templates else False

    result = StudentDeletionResult(
        user_id=user_id,
        student_id=student_id,
        account_deleted=account_deleted,
        profile_deleted=profile_deleted,
        face_templates_deleted=templates,
        photo_files_deleted=photos,
        attendance_records_deleted=attendance,
        attendance_corrections_deleted=corrections,
        doorway_events_deleted=events,
        roster_entries_removed=roster_entries,
        vision_gallery_refreshed=gallery_refreshed,
    )

    # Identifiers and counts only: the audit entry must not preserve the
    # name, email or anything else that was just deleted.
    await record_audit_event(
        actor_user_id=deleted_by["user_id"],
        actor_role=deleted_by.get("role", "ADMIN"),
        action="STUDENT_DELETED",
        resource_type="STUDENT_PROFILE",
        resource_id=student_id,
        metadata={"deleted_user_id": user_id, "identities": key_list, **result.counts()},
    )
    logger.info("Student %s deleted by %s", student_id, deleted_by["user_id"])
    return result
