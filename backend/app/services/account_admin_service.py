"""Account management by an administrator.

Creating, editing, resetting and deleting accounts. Rules that hold here:

* An account an administrator creates, and an account whose password an
  administrator resets, must choose a new password at the next login.
* A password is never read back. A reset generates a temporary password that
  is returned once, to the administrator who asked for it, and is not stored
  or logged in clear.
* Replacing a password always invalidates the tokens issued before it.
* The last administrator cannot be deleted, and nobody deletes themself.
* Deleting a teacher keeps the sessions and attendance they recorded.

A student's ID is a label on the student record. Photos, face templates,
rosters and attendance rows are keyed by the internal ``identity``, which never
changes, and every view reads the ID from the student record. Changing the ID
is therefore one document update.

Audit entries written here hold IDs, roles and field names only: no names,
emails, passwords or images.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import re
import secrets
from typing import Any, Optional
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from app.core.account_status import ACCOUNT_APPROVED, is_approved
from app.database.student_profiles import normalize_class_code
from app.database.users import create_user
from app.security.passwords import hash_password
from app.services.academic_admin_service import archived_subjects, resolve_active_class
from app.services.approval_service import _clean_codes, _known_class_codes, delete_teacher_account
from app.services.audit_service import record_audit_event
from app.services.auth_service import set_password
from app.services.student_deletion import _refresh_vision_gallery

logger = logging.getLogger(__name__)

STUDENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{1,63}$")


class AccountAdminError(Exception):
    """A request that cannot be carried out. ``status_code`` is the HTTP status to return."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def student_photo_url(identity: str) -> str:
    """The photo address of a student. Built from the identity, so it survives an ID change."""
    return f"/api/v1/students/{identity}/photo"


async def _audit(
    actor: dict[str, Any], action: str, user_id: str, metadata: dict[str, Any]
) -> None:
    await record_audit_event(
        actor_user_id=actor["user_id"],
        actor_role=actor.get("role", "ADMIN"),
        action=action,
        resource_type="USER",
        resource_id=user_id,
        metadata=metadata,
    )


async def _account(db: AsyncIOMotorDatabase, user_id: str, role: str) -> dict[str, Any]:
    user = await db["users"].find_one({"user_id": user_id})
    if user is None or user.get("role") != role:
        raise AccountAdminError(f"{role.capitalize()} account not found", 404)
    return user


async def _change_email(db: AsyncIOMotorDatabase, user: dict[str, Any], email: str) -> bool:
    """Move the account to a new email address. Returns whether it changed."""
    new_email = email.strip().lower()
    if "@" not in new_email:
        raise AccountAdminError("Enter a valid email address", 400)
    if new_email == user.get("email"):
        return False
    taken = await db["users"].find_one({"email": new_email, "user_id": {"$ne": user["user_id"]}})
    if taken is not None:
        raise AccountAdminError("Another account already uses this email address", 409)
    try:
        await db["users"].update_one({"user_id": user["user_id"]}, {"$set": {"email": new_email}})
    except DuplicateKeyError as exc:
        raise AccountAdminError("Another account already uses this email address", 409) from exc
    return True


# ------------------------------------------------------------------ creation


async def mark_created_by_admin(
    db: AsyncIOMotorDatabase, user_id: str, *, role: str, created_by: dict[str, Any]
) -> None:
    """The administrator chose the first password, so the owner must replace it."""
    await db["users"].update_one(
        {"user_id": user_id},
        {
            "$set": {
                "must_change_password": True,
                "created_by": created_by["user_id"],
                "approved_by": created_by["user_id"],
                "approved_at": datetime.now(timezone.utc),
            }
        },
    )
    await _audit(created_by, "ACCOUNT_CREATED", user_id, {"role": role})


async def create_admin(
    db: AsyncIOMotorDatabase, *, email: str, password: str, name: str, created_by: dict[str, Any]
) -> dict[str, Any]:
    address = email.strip().lower()
    if "@" not in address:
        raise AccountAdminError("Enter a valid email address", 400)
    if await db["users"].find_one({"email": address}) is not None:
        raise AccountAdminError("Another account already uses this email address", 409)

    user_id = f"user_{uuid4().hex}"
    try:
        await create_user(
            user_id=user_id,
            email=address,
            password_hash=hash_password(password),
            role="ADMIN",
            status=ACCOUNT_APPROVED,
        )
    except Exception as exc:
        raise AccountAdminError("Another account already uses this email address", 409) from exc
    await db["users"].update_one({"user_id": user_id}, {"$set": {"name": name.strip()}})
    await mark_created_by_admin(db, user_id, role="ADMIN", created_by=created_by)
    return await admin_summary(db, user_id)


async def admin_summary(db: AsyncIOMotorDatabase, user_id: str) -> dict[str, Any]:
    user = await db["users"].find_one({"user_id": user_id}, {"password_hash": 0}) or {}
    return {
        "user_id": user.get("user_id", user_id),
        "email": user.get("email", ""),
        "name": user.get("name") or "",
        "must_change_password": bool(user.get("must_change_password")),
        "created_at": user.get("created_at"),
    }


async def list_admins(db: AsyncIOMotorDatabase) -> list[dict[str, Any]]:
    admins = []
    async for user in (
        db["users"].find({"role": "ADMIN"}, {"password_hash": 0}).sort("created_at", 1)
    ):
        admins.append(
            {
                "user_id": user["user_id"],
                "email": user.get("email", ""),
                "name": user.get("name") or "",
                "must_change_password": bool(user.get("must_change_password")),
                "created_at": user.get("created_at"),
            }
        )
    return admins


# ------------------------------------------------------------------ passwords


async def reset_password(
    db: AsyncIOMotorDatabase, user_id: str, *, reset_by: dict[str, Any]
) -> dict[str, Any]:
    """Give the account a temporary password. It is returned once and must be changed at login."""
    user = await db["users"].find_one({"user_id": user_id})
    if user is None:
        raise AccountAdminError("Account not found", 404)
    if user_id == reset_by["user_id"]:
        raise AccountAdminError("Use the change-password form to change your own password", 400)
    if not is_approved(user):
        raise AccountAdminError("This account is still waiting for approval", 409)

    temporary_password = secrets.token_urlsafe(12)
    await set_password(user_id, temporary_password, must_change_password=True)
    await _audit(reset_by, "PASSWORD_RESET", user_id, {"role": user.get("role")})
    return {
        "status": "password_reset",
        "user_id": user_id,
        "temporary_password": temporary_password,
        "must_change_password": True,
    }


# ------------------------------------------------------------------ students


async def update_student(
    db: AsyncIOMotorDatabase,
    user_id: str,
    *,
    updated_by: dict[str, Any],
    name: Optional[str] = None,
    email: Optional[str] = None,
    student_id: Optional[str] = None,
    roll_number: Optional[str] = None,
    branch: Optional[str] = None,
    section: Optional[str] = None,
    class_code: Optional[str] = None,
) -> dict[str, Any]:
    user = await _account(db, user_id, "STUDENT")
    profile = await db["student_profiles"].find_one({"user_id": user_id})
    if profile is None:
        raise AccountAdminError("This student has no profile to edit", 404)

    identity = profile.get("identity") or profile.get("student_id")
    changes: dict[str, Any] = {}
    changed_fields: list[str] = []
    old_student_id = profile.get("student_id") or identity
    new_student_id: Optional[str] = None

    if name is not None and name.strip() and name.strip() != profile.get("name"):
        changes["name"] = name.strip()
        changed_fields.append("name")

    if roll_number is not None and roll_number.strip() != (profile.get("roll_number") or ""):
        changes["roll_number"] = roll_number.strip()
        changed_fields.append("roll_number")

    if class_code is not None or branch is not None or section is not None:
        new_branch = (branch if branch is not None else profile.get("branch") or "").strip()
        new_section = (
            (section if section is not None else profile.get("section") or "").strip().upper()
        )
        if not class_code and not (new_branch and new_section):
            raise AccountAdminError("A student needs both a branch and a section", 400)
        chosen = await resolve_active_class(
            db, class_code=class_code, branch=new_branch, section=new_section
        )
        if chosen is not None:
            new_branch, new_section = chosen["branch"], chosen["section"]
            new_code = chosen["class_code"]
        else:
            new_code = (class_code or normalize_class_code(new_branch, new_section)).upper()
        if new_code != profile.get("class_code"):
            # Moving a student needs an active class; staying where they are does not.
            if chosen is None and (class_code or await _known_class_codes(db)):
                raise AccountAdminError(f"Unknown or archived class: {new_code}", 400)
            changes.update({"branch": new_branch, "section": new_section, "class_code": new_code})
            changed_fields.append("class")

    if student_id is not None and student_id.strip() != old_student_id:
        candidate = student_id.strip()
        if not STUDENT_ID_PATTERN.fullmatch(candidate) or ".." in candidate:
            raise AccountAdminError("A student ID is 2 to 64 letters, digits, '.', '_' or '-'", 400)
        # No other student may use it, either as their ID or as their internal
        # identity: both are accepted wherever a student is looked up.
        clash = await db["student_profiles"].find_one(
            {
                "user_id": {"$ne": user_id},
                "$or": [{"identity": candidate}, {"student_id": candidate}],
            }
        )
        if clash is not None:
            raise AccountAdminError(f"Student ID '{candidate}' is already in use", 409)
        new_student_id = candidate
        changes["student_id"] = candidate
        if profile.get("photo_url"):
            changes["photo_url"] = student_photo_url(identity)

    email_changed = False
    if email is not None:
        email_changed = await _change_email(db, user, email)
        if email_changed:
            changes["email"] = email.strip().lower()
            changed_fields.append("email")

    if changes:
        changes["updated_at"] = datetime.now(timezone.utc)
        # One document: the ID, the photo address and the rest change together.
        await db["student_profiles"].update_one({"user_id": user_id}, {"$set": changes})

    gallery_refreshed = None
    if new_student_id is not None or "name" in changes:
        # The vision service shows the name and ID it was given with the gallery.
        gallery_refreshed = await _refresh_vision_gallery()

    if new_student_id is not None:
        await _audit(
            updated_by,
            "STUDENT_ID_CHANGED",
            user_id,
            {"old_student_id": old_student_id, "new_student_id": new_student_id},
        )
    if changed_fields:
        metadata: dict[str, Any] = {"role": "STUDENT", "fields": changed_fields}
        if "class" in changed_fields:
            metadata["class_code"] = changes["class_code"]
        await _audit(updated_by, "ACCOUNT_UPDATED", user_id, metadata)

    return {
        "changed": changed_fields + (["student_id"] if new_student_id is not None else []),
        "vision_gallery_refreshed": gallery_refreshed,
    }


# ------------------------------------------------------------------ teachers


async def update_teacher(
    db: AsyncIOMotorDatabase,
    user_id: str,
    *,
    updated_by: dict[str, Any],
    name: Optional[str] = None,
    email: Optional[str] = None,
    teacher_id: Optional[str] = None,
    department: Optional[str] = None,
    assigned_classes: Optional[list[str]] = None,
    assigned_subjects: Optional[list[str]] = None,
) -> dict[str, Any]:
    user = await _account(db, user_id, "TEACHER")
    profile = await db["teacher_profiles"].find_one({"user_id": user_id}) or {}
    changes: dict[str, Any] = {}
    changed_fields: list[str] = []

    if name is not None and name.strip() and name.strip() != profile.get("name"):
        changes["name"] = name.strip()
        changed_fields.append("name")

    if department is not None and department.strip() != (profile.get("department") or ""):
        changes["department"] = department.strip()
        changed_fields.append("department")

    if teacher_id is not None and teacher_id.strip() != (profile.get("teacher_id") or ""):
        candidate = teacher_id.strip()
        if len(candidate) < 2 or len(candidate) > 64:
            raise AccountAdminError("A teacher ID is 2 to 64 characters", 400)
        clash = await db["teacher_profiles"].find_one(
            {"teacher_id": candidate, "user_id": {"$ne": user_id}}
        )
        if clash is not None:
            raise AccountAdminError(f"Teacher ID '{candidate}' is already in use", 409)
        changes["teacher_id"] = candidate
        changed_fields.append("teacher_id")

    if assigned_classes is not None:
        classes = _clean_codes(assigned_classes)
        current_classes = profile.get("assigned_classes") or []
        if classes != current_classes:
            # A class the teacher already has may stay after it is archived;
            # only a class being added has to be active.
            unknown = sorted(set(classes) - set(current_classes) - await _known_class_codes(db))
            if unknown:
                raise AccountAdminError(f"Unknown or archived class: {', '.join(unknown)}", 400)
            changes["assigned_classes"] = classes
            changed_fields.append("assigned_classes")

    if assigned_subjects is not None:
        subjects = [s.strip() for s in assigned_subjects if s and s.strip()]
        current_subjects = profile.get("assigned_subjects") or []
        if subjects != current_subjects:
            added = [s for s in subjects if s not in current_subjects]
            retired = await archived_subjects(db, added)
            if retired:
                raise AccountAdminError(f"Archived subject: {', '.join(retired)}", 400)
            changes["assigned_subjects"] = subjects
            changed_fields.append("assigned_subjects")

    if email is not None and await _change_email(db, user, email):
        changes["email"] = email.strip().lower()
        changed_fields.append("email")

    if changes:
        now = datetime.now(timezone.utc)
        changes["updated_at"] = now
        await db["teacher_profiles"].update_one(
            {"user_id": user_id},
            {
                "$set": changes,
                "$setOnInsert": {
                    "created_at": now,
                    **{
                        key: value
                        for key, value in {
                            "teacher_id": f"T-{user_id[-8:]}",
                            "name": "",
                            "email": user.get("email", ""),
                            "department": "",
                            "assigned_classes": [],
                            "assigned_subjects": [],
                        }.items()
                        if key not in changes
                    },
                },
            },
            upsert=True,
        )
        metadata: dict[str, Any] = {"role": "TEACHER", "fields": changed_fields}
        if "assigned_classes" in changes:
            metadata["assigned_classes"] = changes["assigned_classes"]
        await _audit(updated_by, "ACCOUNT_UPDATED", user_id, metadata)

    return {"changed": changed_fields}


async def delete_teacher(
    db: AsyncIOMotorDatabase, user_id: str, *, deleted_by: dict[str, Any]
) -> dict[str, Any]:
    """Remove a teacher's account and profile. Their sessions and attendance stay as history."""
    await _account(db, user_id, "TEACHER")
    active = await db["sessions"].count_documents({"created_by": user_id, "status": "ACTIVE"})
    if active:
        raise AccountAdminError(
            "This teacher has a session in progress. End or finalize it before deleting the account.",
            409,
        )
    sessions_kept = await db["sessions"].count_documents({"created_by": user_id})
    removed = await delete_teacher_account(db, user_id)
    await _audit(
        deleted_by,
        "TEACHER_DELETED",
        user_id,
        {"removed": removed, "sessions_kept": sessions_kept},
    )
    return {"status": "deleted", "user_id": user_id, "sessions_kept": sessions_kept}


# ------------------------------------------------------------------ administrators


async def delete_admin(
    db: AsyncIOMotorDatabase, user_id: str, *, deleted_by: dict[str, Any]
) -> dict[str, Any]:
    if user_id == deleted_by["user_id"]:
        raise AccountAdminError("You cannot delete your own account", 409)
    await _account(db, user_id, "ADMIN")
    if await db["users"].count_documents({"role": "ADMIN"}) <= 1:
        raise AccountAdminError("The last administrator cannot be deleted", 409)
    await db["users"].delete_one({"user_id": user_id, "role": "ADMIN"})
    await _audit(deleted_by, "ADMIN_DELETED", user_id, {})
    return {"status": "deleted", "user_id": user_id}
