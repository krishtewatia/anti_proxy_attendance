"""Registration approval.

Every public registration starts PENDING. An administrator approves it
(assigning a teacher's classes, or confirming a student's class) or rejects
it. Rejecting removes everything the registration created. A registration
nobody acts on is removed the same way after 14 days.

A student who is already approved can ask to replace their photo; the photo
and template in use stay unchanged until an administrator approves the new
ones. Without that, approval could be bypassed afterwards by swapping in
someone else's face.

Audit entries written here hold IDs and counts only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.account_status import (
    ACCOUNT_APPROVED,
    ACCOUNT_PENDING,
    PENDING_REGISTRATION_MAX_AGE_DAYS,
    TEMPLATE_ACTIVE,
)
from app.core.uploads import pending_photo_path, student_photo_path
from app.database.student_profiles import normalize_class_code
from app.services.academic_admin_service import archived_subjects, resolve_active_class
from app.services.audit_service import record_audit_event
from app.services.student_biometric_service import PHOTO_CHANGE_REQUESTS_COLLECTION
from app.services.student_deletion import _refresh_vision_gallery, delete_student_completely

logger = logging.getLogger(__name__)

SYSTEM_ACTOR = {"user_id": "system", "role": "SYSTEM"}


class ApprovalError(Exception):
    """An approval request that cannot be carried out. ``status_code`` is the HTTP status to return."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _clean_codes(values: Optional[list[str]]) -> list[str]:
    seen: list[str] = []
    for value in values or []:
        code = str(value).strip().upper()
        if code and code not in seen:
            seen.append(code)
    return seen


async def _known_class_codes(db: AsyncIOMotorDatabase) -> set[str]:
    codes = set()
    async for doc in db["academic_classes"].find({}, {"class_code": 1, "status": 1}):
        if (doc.get("status") or "ACTIVE") == "ACTIVE" and doc.get("class_code"):
            codes.add(str(doc["class_code"]).upper())
    return codes


async def _pending_user(db: AsyncIOMotorDatabase, user_id: str) -> dict[str, Any]:
    user = await db["users"].find_one({"user_id": user_id})
    if user is None:
        raise ApprovalError("Registration not found", 404)
    if user.get("status") != ACCOUNT_PENDING:
        raise ApprovalError("This account is not waiting for approval", 409)
    return user


async def list_pending(db: AsyncIOMotorDatabase) -> dict[str, Any]:
    """Everything waiting for an administrator, oldest first."""
    students: list[dict[str, Any]] = []
    teachers: list[dict[str, Any]] = []
    accounts: list[dict[str, Any]] = []

    cursor = (
        db["users"].find({"status": ACCOUNT_PENDING}, {"password_hash": 0}).sort("created_at", 1)
    )
    async for user in cursor:
        base = {
            "user_id": user["user_id"],
            "email": user.get("email"),
            "role": user.get("role"),
            "registered_at": user.get("created_at"),
        }
        if user.get("role") == "STUDENT":
            profile = await db["student_profiles"].find_one({"user_id": user["user_id"]}) or {}
            if profile:
                students.append(
                    {
                        **base,
                        "name": profile.get("name"),
                        "student_id": profile.get("student_id"),
                        "roll_number": profile.get("roll_number"),
                        "branch": profile.get("branch"),
                        "section": profile.get("section"),
                        "class_code": profile.get("class_code"),
                        "has_photo": bool(profile.get("has_biometric")),
                        "photo_url": profile.get("photo_url"),
                    }
                )
                continue
        elif user.get("role") == "TEACHER":
            profile = await db["teacher_profiles"].find_one({"user_id": user["user_id"]}) or {}
            if profile:
                teachers.append(
                    {
                        **base,
                        "name": profile.get("name"),
                        "teacher_id": profile.get("teacher_id"),
                        "department": profile.get("department"),
                        "requested_classes": profile.get("requested_classes") or [],
                        "requested_subjects": profile.get("requested_subjects") or [],
                    }
                )
                continue
        # Registered through the bare account route: no profile to show.
        accounts.append(base)

    photo_changes: list[dict[str, Any]] = []
    async for request in db[PHOTO_CHANGE_REQUESTS_COLLECTION].find({}).sort("requested_at", 1):
        profile = await db["student_profiles"].find_one({"identity": request["identity"]}) or {}
        photo_changes.append(
            {
                "identity": request["identity"],
                "student_id": profile.get("student_id") or request["identity"],
                "name": profile.get("name"),
                "class_code": profile.get("class_code"),
                "requested_at": request.get("requested_at"),
                "current_photo_url": profile.get("photo_url"),
                "new_photo_url": f"/api/v1/admin/approvals/photos/{request['identity']}/image",
            }
        )

    return {
        "students": students,
        "teachers": teachers,
        "accounts": accounts,
        "photo_changes": photo_changes,
        "counts": {
            "students": len(students),
            "teachers": len(teachers),
            "accounts": len(accounts),
            "photo_changes": len(photo_changes),
            "total": len(students) + len(teachers) + len(accounts) + len(photo_changes),
        },
    }


async def approve_registration(
    db: AsyncIOMotorDatabase,
    user_id: str,
    *,
    approved_by: dict[str, Any],
    assigned_classes: Optional[list[str]] = None,
    assigned_subjects: Optional[list[str]] = None,
    branch: Optional[str] = None,
    section: Optional[str] = None,
    class_code: Optional[str] = None,
) -> dict[str, Any]:
    user = await _pending_user(db, user_id)
    role = user.get("role")
    now = datetime.now(timezone.utc)
    details: dict[str, Any] = {"role": role}
    gallery_changed = False

    if role == "TEACHER":
        classes = _clean_codes(assigned_classes)
        if not classes:
            raise ApprovalError("Assign at least one class to approve a teacher", 400)
        unknown = sorted(set(classes) - await _known_class_codes(db))
        if unknown:
            raise ApprovalError(f"Unknown or archived class: {', '.join(unknown)}", 400)
        subjects = [s.strip() for s in (assigned_subjects or []) if s and s.strip()]
        retired = await archived_subjects(db, subjects)
        if retired:
            raise ApprovalError(f"Archived subject: {', '.join(retired)}", 400)
        # An account registered through the bare account route has no profile
        # yet; the assignment creates one, since sessions depend on it.
        await db["teacher_profiles"].update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "assigned_classes": classes,
                    "assigned_subjects": subjects,
                    "updated_at": now,
                },
                "$unset": {"requested_classes": "", "requested_subjects": ""},
                "$setOnInsert": {
                    "teacher_id": f"T-{user_id[-8:]}",
                    "name": "",
                    "email": user.get("email", ""),
                    "department": "",
                    "created_at": now,
                },
            },
            upsert=True,
        )
        details.update({"assigned_classes": classes, "assigned_subject_count": len(subjects)})

    elif role == "STUDENT":
        profile = await db["student_profiles"].find_one({"user_id": user_id})
        if profile is not None:
            new_branch = (branch or profile.get("branch") or "").strip()
            new_section = (section or profile.get("section") or "").strip().upper()
            if not class_code and not (new_branch and new_section):
                raise ApprovalError("Confirm the student's branch and section to approve", 400)
            # With nothing chosen by the administrator, the class the student
            # registered for is the one being confirmed.
            chosen = await resolve_active_class(
                db,
                class_code=class_code
                or (None if (branch or section) else profile.get("class_code")),
                branch=new_branch,
                section=new_section,
            )
            if chosen is not None:
                new_branch, new_section = chosen["branch"], chosen["section"]
                class_code = chosen["class_code"]
            else:
                wanted = class_code or normalize_class_code(new_branch, new_section)
                if class_code or await _known_class_codes(db):
                    raise ApprovalError(f"Unknown or archived class: {wanted}", 400)
                class_code = wanted
            await db["student_profiles"].update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "branch": new_branch,
                        "section": new_section,
                        "class_code": class_code,
                        "updated_at": now,
                    }
                },
            )
            keys = [k for k in {profile.get("identity"), profile.get("student_id")} if k]
            activated = await db["biometric_profiles"].update_many(
                {"identity": {"$in": keys}}, {"$set": {"review_status": TEMPLATE_ACTIVE}}
            )
            gallery_changed = activated.modified_count > 0
            details.update(
                {
                    "student_id": profile.get("student_id"),
                    "class_code": class_code,
                    "face_templates_activated": activated.modified_count,
                }
            )

    await db["users"].update_one(
        {"user_id": user_id, "status": ACCOUNT_PENDING},
        {
            "$set": {
                "status": ACCOUNT_APPROVED,
                "approved_by": approved_by["user_id"],
                "approved_at": now,
            }
        },
    )
    if gallery_changed:
        details["vision_gallery_refreshed"] = await _refresh_vision_gallery()

    await record_audit_event(
        actor_user_id=approved_by["user_id"],
        actor_role=approved_by.get("role", "ADMIN"),
        action="REGISTRATION_APPROVED",
        resource_type="USER",
        resource_id=user_id,
        metadata=details,
    )
    return {"status": "approved", "user_id": user_id, **details}


async def delete_teacher_account(db: AsyncIOMotorDatabase, user_id: str) -> dict[str, Any]:
    """Remove a teacher's account and profile. Sessions they created are not touched."""
    profile = (await db["teacher_profiles"].delete_one({"user_id": user_id})).deleted_count > 0
    account = (
        await db["users"].delete_one({"user_id": user_id, "role": "TEACHER"})
    ).deleted_count > 0
    return {"account_deleted": account, "profile_deleted": profile}


async def purge_registration(
    db: AsyncIOMotorDatabase, user: dict[str, Any], *, actor: dict[str, Any], reason: str
) -> dict[str, Any]:
    """Remove everything a pending registration created, and record one audit entry."""
    user_id = user["user_id"]
    role = user.get("role")
    if role == "STUDENT":
        # The student deletion already removes the photo, the template and every
        # other trace, and writes its own STUDENT_DELETED audit entry.
        result = await delete_student_completely(db, user_id, deleted_by=actor)
        removed = result.counts()
    elif role == "TEACHER":
        removed = await delete_teacher_account(db, user_id)
    else:
        raise ApprovalError("Only student and teacher registrations can be rejected", 400)

    await record_audit_event(
        actor_user_id=actor["user_id"],
        actor_role=actor.get("role", "ADMIN"),
        action="REGISTRATION_REJECTED",
        resource_type="USER",
        resource_id=user_id,
        metadata={"role": role, "reason": reason, "removed": removed},
    )
    return {"status": "rejected", "user_id": user_id, "role": role, "removed": removed}


async def reject_registration(
    db: AsyncIOMotorDatabase, user_id: str, *, rejected_by: dict[str, Any]
) -> dict[str, Any]:
    user = await _pending_user(db, user_id)
    return await purge_registration(db, user, actor=rejected_by, reason="rejected_by_admin")


async def purge_stale_registrations(
    db: AsyncIOMotorDatabase,
    *,
    now: Optional[datetime] = None,
    max_age_days: int = PENDING_REGISTRATION_MAX_AGE_DAYS,
) -> list[str]:
    """Remove registrations that have been PENDING for longer than ``max_age_days``."""
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=max_age_days)
    purged: list[str] = []
    async for user in db["users"].find({"status": ACCOUNT_PENDING}):
        created = user.get("created_at")
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created > cutoff:
            continue
        try:
            await purge_registration(
                db, user, actor=SYSTEM_ACTOR, reason="pending_longer_than_14_days"
            )
            purged.append(user["user_id"])
        except Exception:
            logger.exception("Could not purge the stale registration %s", user["user_id"])
    if purged:
        logger.info(
            "Purged %d registration(s) left pending for more than %d days",
            len(purged),
            max_age_days,
        )
    return purged


# ------------------------------------------------------------------ photo changes


async def _photo_change(db: AsyncIOMotorDatabase, identity: str) -> dict[str, Any]:
    request = await db[PHOTO_CHANGE_REQUESTS_COLLECTION].find_one({"identity": identity})
    if request is None:
        raise ApprovalError("No photo change is waiting for this student", 404)
    return request


def _discard_pending_photo(identity: str) -> None:
    try:
        path = pending_photo_path(identity)
        if path.is_file():
            path.unlink()
    except (ValueError, OSError) as exc:
        logger.warning("Could not remove a pending photo: %s", type(exc).__name__)


async def approve_photo_change(
    db: AsyncIOMotorDatabase, identity: str, *, approved_by: dict[str, Any]
) -> dict[str, Any]:
    request = await _photo_change(db, identity)
    now = datetime.now(timezone.utc)

    # The new photo replaces the one in use, then the new template goes live.
    try:
        pending = pending_photo_path(identity)
        if pending.is_file():
            target = student_photo_path(identity)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(pending.read_bytes())
    except (ValueError, OSError) as exc:
        raise ApprovalError("The new photo could not be stored", 500) from exc

    await db["biometric_profiles"].update_one(
        {"identity": identity},
        {
            "$set": {
                "identity": identity,
                "mean_embedding": request["mean_embedding"],
                "sample_count": 1,
                "quality_score": 0.95,
                "enrolled_by": request.get("requested_by"),
                "review_status": TEMPLATE_ACTIVE,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    await db["student_profiles"].update_one(
        {"identity": identity}, {"$set": {"has_biometric": True, "updated_at": now}}
    )
    await db[PHOTO_CHANGE_REQUESTS_COLLECTION].delete_one({"identity": identity})
    _discard_pending_photo(identity)
    refreshed = await _refresh_vision_gallery()

    await record_audit_event(
        actor_user_id=approved_by["user_id"],
        actor_role=approved_by.get("role", "ADMIN"),
        action="PHOTO_CHANGE_APPROVED",
        resource_type="BIOMETRIC_PROFILE",
        resource_id=identity,
        metadata={
            "requested_by": request.get("requested_by"),
            "vision_gallery_refreshed": refreshed,
        },
    )
    return {"status": "approved", "identity": identity, "vision_gallery_refreshed": refreshed}


async def reject_photo_change(
    db: AsyncIOMotorDatabase, identity: str, *, rejected_by: dict[str, Any]
) -> dict[str, Any]:
    request = await _photo_change(db, identity)
    await db[PHOTO_CHANGE_REQUESTS_COLLECTION].delete_one({"identity": identity})
    _discard_pending_photo(identity)
    await record_audit_event(
        actor_user_id=rejected_by["user_id"],
        actor_role=rejected_by.get("role", "ADMIN"),
        action="PHOTO_CHANGE_REJECTED",
        resource_type="BIOMETRIC_PROFILE",
        resource_id=identity,
        metadata={"requested_by": request.get("requested_by")},
    )
    return {"status": "rejected", "identity": identity}
