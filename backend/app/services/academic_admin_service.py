"""Managing the academic catalog: classes and subjects.

A class or a subject is ACTIVE or ARCHIVED (a record with no status is
ACTIVE). Archiving hides it from registration, from new sessions and from new
assignments, and keeps everything that already refers to it. Deleting is only
possible while nothing refers to it.

Once something refers to a class its code, branch and section can no longer
change, and likewise a subject's name: students, teachers and sessions hold
those values, so changing them would silently detach the history.

Audit entries hold codes, IDs and counts only.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database.academic import ACADEMIC_CLASSES_COLLECTION, SUBJECTS_COLLECTION
from app.database.student_profiles import normalize_class_code
from app.services.audit_service import record_audit_event

STATUS_ACTIVE = "ACTIVE"
STATUS_ARCHIVED = "ARCHIVED"

CLASS_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9&_\-]{1,19}$")


class AcademicAdminError(Exception):
    """A request that cannot be carried out. ``status_code`` is the HTTP status to return."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def record_status(doc: dict[str, Any] | None) -> str:
    return (doc or {}).get("status") or STATUS_ACTIVE


def is_active(doc: dict[str, Any] | None) -> bool:
    return doc is not None and record_status(doc) == STATUS_ACTIVE


def _same_text(pattern_text: str) -> dict[str, Any]:
    """A case-insensitive exact match for a name typed by a person."""
    return {"$regex": f"^{re.escape(pattern_text.strip())}$", "$options": "i"}


async def _audit(actor: dict[str, Any], action: str, resource_id: str, metadata: dict) -> None:
    await record_audit_event(
        actor_user_id=actor["user_id"],
        actor_role=actor.get("role", "ADMIN"),
        action=action,
        resource_type="ACADEMIC",
        resource_id=resource_id,
        metadata=metadata,
    )


# ------------------------------------------------------------------ classes


async def find_class(db: AsyncIOMotorDatabase, class_code: str) -> dict[str, Any] | None:
    return await db[ACADEMIC_CLASSES_COLLECTION].find_one(
        {"class_code": class_code.strip().upper()}, {"_id": 0}
    )


async def class_usage(db: AsyncIOMotorDatabase, class_code: str) -> dict[str, int]:
    """How many students, teachers and sessions refer to the class."""
    code = class_code.strip().upper()
    return {
        "students": await db["student_profiles"].count_documents({"class_code": code}),
        "teachers": await db["teacher_profiles"].count_documents({"assigned_classes": code}),
        "sessions": await db["sessions"].count_documents({"class_code": code}),
    }


def _in_use(usage: dict[str, int]) -> bool:
    return any(usage.values())


def _usage_text(usage: dict[str, int]) -> str:
    return ", ".join(f"{count} {name}" for name, count in usage.items() if count)


async def resolve_active_class(
    db: AsyncIOMotorDatabase,
    *,
    class_code: Optional[str] = None,
    branch: Optional[str] = None,
    section: Optional[str] = None,
) -> dict[str, Any] | None:
    """The active class a form means: by its code, or by its branch and section.

    Returns None when no active class matches.
    """
    classes = db[ACADEMIC_CLASSES_COLLECTION]
    if class_code and class_code.strip():
        found = await find_class(db, class_code)
        return found if is_active(found) else None
    if not (branch and branch.strip() and section and section.strip()):
        return None
    found = await classes.find_one(
        {"branch": _same_text(branch), "section": section.strip().upper()}, {"_id": 0}
    )
    if found is None:
        # A branch and section written the long way round, e.g. "Data Science" + "B" = DS-B.
        found = await find_class(db, normalize_class_code(branch, section))
    return found if is_active(found) else None


async def list_classes_for_admin(db: AsyncIOMotorDatabase) -> list[dict[str, Any]]:
    """Every class, archived ones included, with its status and what refers to it."""
    result = []
    async for doc in db[ACADEMIC_CLASSES_COLLECTION].find({}, {"_id": 0}).sort("class_code", 1):
        usage = await class_usage(db, doc["class_code"])
        result.append(
            {
                "class_id": doc.get("class_id") or doc["class_code"],
                "class_code": doc["class_code"],
                "branch": doc.get("branch", ""),
                "section": doc.get("section", ""),
                "semester": doc.get("semester"),
                "status": record_status(doc),
                "usage": usage,
                "in_use": _in_use(usage),
            }
        )
    return result


def _clean_class_fields(
    class_code: str, branch: str, section: str, semester: Optional[int]
) -> dict[str, Any]:
    code = class_code.strip().upper()
    if not CLASS_CODE_PATTERN.fullmatch(code):
        raise AcademicAdminError(
            "A class code is 2 to 20 letters, digits, '-', '_' or '&' (for example DS-B)", 400
        )
    branch_clean = branch.strip()
    section_clean = section.strip().upper()
    if not branch_clean or not section_clean:
        raise AcademicAdminError("A class needs a branch and a section", 400)
    if semester is not None and not 1 <= semester <= 12:
        raise AcademicAdminError("A semester is a number from 1 to 12", 400)
    return {
        "class_code": code,
        "branch": branch_clean,
        "section": section_clean,
        "semester": semester,
    }


async def _refuse_duplicate_pair(
    db: AsyncIOMotorDatabase, branch: str, section: str, *, except_code: Optional[str] = None
) -> None:
    """One class per branch and section, so a branch and section always mean one class."""
    query: dict[str, Any] = {"branch": _same_text(branch), "section": section}
    if except_code:
        query["class_code"] = {"$ne": except_code}
    other = await db[ACADEMIC_CLASSES_COLLECTION].find_one(query, {"class_code": 1})
    if other is not None:
        raise AcademicAdminError(
            f"{branch} section {section} already exists as class {other['class_code']}", 409
        )


async def create_class(
    db: AsyncIOMotorDatabase,
    *,
    class_code: str,
    branch: str,
    section: str,
    semester: Optional[int],
    created_by: dict[str, Any],
) -> dict[str, Any]:
    fields = _clean_class_fields(class_code, branch, section, semester)
    existing = await find_class(db, fields["class_code"])
    if existing is not None:
        hint = " It is archived: restore it instead." if not is_active(existing) else ""
        raise AcademicAdminError(f"Class {fields['class_code']} already exists.{hint}", 409)
    await _refuse_duplicate_pair(db, fields["branch"], fields["section"])

    now = datetime.now(timezone.utc)
    doc = {
        "class_id": f"cls_{fields['class_code'].lower().replace('-', '_')}",
        **fields,
        "status": STATUS_ACTIVE,
        "created_at": now,
        "updated_at": now,
    }
    await db[ACADEMIC_CLASSES_COLLECTION].insert_one(dict(doc))
    await _audit(created_by, "CLASS_CREATED", fields["class_code"], {})
    return doc


async def _existing_class(db: AsyncIOMotorDatabase, class_code: str) -> dict[str, Any]:
    found = await find_class(db, class_code)
    if found is None:
        raise AcademicAdminError("Class not found", 404)
    return found


async def update_class(
    db: AsyncIOMotorDatabase,
    class_code: str,
    *,
    updated_by: dict[str, Any],
    new_class_code: Optional[str] = None,
    branch: Optional[str] = None,
    section: Optional[str] = None,
    semester: Optional[int] = None,
    clear_semester: bool = False,
) -> dict[str, Any]:
    current = await _existing_class(db, class_code)
    code = current["class_code"]
    wanted = _clean_class_fields(
        new_class_code if new_class_code is not None else code,
        branch if branch is not None else current.get("branch", ""),
        section if section is not None else current.get("section", ""),
        None if clear_semester else (semester if semester is not None else current.get("semester")),
    )
    changes = {key: value for key, value in wanted.items() if value != current.get(key)}
    if not changes:
        return {"class_code": code, "changed": []}

    identifying = sorted(set(changes) & {"class_code", "branch", "section"})
    if identifying:
        usage = await class_usage(db, code)
        if _in_use(usage):
            raise AcademicAdminError(
                f"The code, branch and section of class {code} cannot change while it is in use "
                f"({_usage_text(usage)}). Archive it and create a new class instead.",
                409,
            )
        if "class_code" in changes and await find_class(db, changes["class_code"]) is not None:
            raise AcademicAdminError(f"Class {changes['class_code']} already exists", 409)
        if {"branch", "section"} & set(changes):
            await _refuse_duplicate_pair(db, wanted["branch"], wanted["section"], except_code=code)

    changes["updated_at"] = datetime.now(timezone.utc)
    await db[ACADEMIC_CLASSES_COLLECTION].update_one({"class_code": code}, {"$set": changes})
    changed = sorted(key for key in changes if key != "updated_at")
    await _audit(
        updated_by,
        "CLASS_UPDATED",
        wanted["class_code"],
        {"fields": changed, **({"previous_class_code": code} if "class_code" in changes else {})},
    )
    return {"class_code": wanted["class_code"], "changed": changed}


async def set_class_archived(
    db: AsyncIOMotorDatabase, class_code: str, *, archived: bool, changed_by: dict[str, Any]
) -> dict[str, Any]:
    current = await _existing_class(db, class_code)
    code = current["class_code"]
    target = STATUS_ARCHIVED if archived else STATUS_ACTIVE
    if record_status(current) == target:
        raise AcademicAdminError(
            f"Class {code} is already {'archived' if archived else 'active'}", 409
        )
    if archived:
        running = await db["sessions"].count_documents({"class_code": code, "status": "ACTIVE"})
        if running:
            raise AcademicAdminError(
                f"Class {code} has a session in progress. End or finalize it before archiving.",
                409,
            )
    now = datetime.now(timezone.utc)
    update: dict[str, Any] = {"$set": {"status": target, "updated_at": now}}
    if archived:
        update["$set"]["archived_at"] = now
    else:
        update["$unset"] = {"archived_at": ""}
    await db[ACADEMIC_CLASSES_COLLECTION].update_one({"class_code": code}, update)
    usage = await class_usage(db, code)
    await _audit(
        changed_by, "CLASS_ARCHIVED" if archived else "CLASS_UNARCHIVED", code, {"usage": usage}
    )
    return {"class_code": code, "status": target, "usage": usage}


async def delete_class(
    db: AsyncIOMotorDatabase, class_code: str, *, deleted_by: dict[str, Any]
) -> dict[str, Any]:
    current = await _existing_class(db, class_code)
    code = current["class_code"]
    usage = await class_usage(db, code)
    if _in_use(usage):
        raise AcademicAdminError(
            f"Class {code} is in use ({_usage_text(usage)}) and cannot be deleted. Archive it instead.",
            409,
        )
    await db[ACADEMIC_CLASSES_COLLECTION].delete_one({"class_code": code})
    await _audit(deleted_by, "CLASS_DELETED", code, {})
    return {"status": "deleted", "class_code": code}


# ------------------------------------------------------------------ subjects


async def subject_usage(db: AsyncIOMotorDatabase, name: str) -> dict[str, int]:
    return {
        "teachers": await db["teacher_profiles"].count_documents({"assigned_subjects": name}),
        "sessions": await db["sessions"].count_documents({"subject": name}),
    }


async def find_subject_by_name(db: AsyncIOMotorDatabase, name: str) -> dict[str, Any] | None:
    if not name or not name.strip():
        return None
    return await db[SUBJECTS_COLLECTION].find_one({"name": _same_text(name)}, {"_id": 0})


async def archived_subjects(db: AsyncIOMotorDatabase, names: list[str]) -> list[str]:
    """The given subject names that exist in the catalog and are archived."""
    refused = []
    for name in names:
        if not is_active(await find_subject_by_name(db, name) or {"status": STATUS_ACTIVE}):
            refused.append(name)
    return refused


async def refuse_archived_session_target(
    db: AsyncIOMotorDatabase, *, class_code: Optional[str], subject: Optional[str]
) -> None:
    """No new session for an archived class or subject. Sessions that exist are kept."""
    if class_code:
        found = await find_class(db, class_code)
        if found is not None and not is_active(found):
            raise AcademicAdminError(
                f"Class {found['class_code']} is archived; no new sessions can be created for it.",
                400,
            )
    if subject and await archived_subjects(db, [subject]):
        raise AcademicAdminError(
            f"Subject '{subject}' is archived; no new sessions can be created for it.", 400
        )


async def list_subjects_for_admin(db: AsyncIOMotorDatabase) -> list[dict[str, Any]]:
    result = []
    async for doc in db[SUBJECTS_COLLECTION].find({}, {"_id": 0}).sort("name", 1):
        usage = await subject_usage(db, doc["name"])
        result.append(
            {
                "subject_id": doc.get("subject_id") or doc["name"],
                "name": doc["name"],
                "code": doc.get("code"),
                "branch": doc.get("branch"),
                "status": record_status(doc),
                "usage": usage,
                "in_use": _in_use(usage),
            }
        )
    return result


async def create_subject(
    db: AsyncIOMotorDatabase,
    *,
    name: str,
    code: Optional[str],
    branch: Optional[str],
    created_by: dict[str, Any],
) -> dict[str, Any]:
    clean_name = name.strip()
    if len(clean_name) < 2:
        raise AcademicAdminError("A subject needs a name", 400)
    existing = await find_subject_by_name(db, clean_name)
    if existing is not None:
        hint = " It is archived: restore it instead." if not is_active(existing) else ""
        raise AcademicAdminError(f"Subject '{existing['name']}' already exists.{hint}", 409)

    now = datetime.now(timezone.utc)
    slug = re.sub(r"[^a-z0-9]+", "_", clean_name.lower()).strip("_") or "subject"
    subject_id = f"sub_{slug}"
    if await db[SUBJECTS_COLLECTION].find_one({"subject_id": subject_id}) is not None:
        subject_id = f"{subject_id}_{int(now.timestamp())}"
    doc = {
        "subject_id": subject_id,
        "name": clean_name,
        "code": code.strip() if code and code.strip() else None,
        "branch": branch.strip() if branch and branch.strip() else None,
        "status": STATUS_ACTIVE,
        "created_at": now,
        "updated_at": now,
    }
    await db[SUBJECTS_COLLECTION].insert_one(dict(doc))
    await _audit(created_by, "SUBJECT_CREATED", subject_id, {})
    return doc


async def _existing_subject(db: AsyncIOMotorDatabase, subject_id: str) -> dict[str, Any]:
    found = await db[SUBJECTS_COLLECTION].find_one({"subject_id": subject_id}, {"_id": 0})
    if found is None:
        raise AcademicAdminError("Subject not found", 404)
    return found


async def update_subject(
    db: AsyncIOMotorDatabase,
    subject_id: str,
    *,
    updated_by: dict[str, Any],
    name: Optional[str] = None,
    code: Optional[str] = None,
    branch: Optional[str] = None,
) -> dict[str, Any]:
    current = await _existing_subject(db, subject_id)
    changes: dict[str, Any] = {}

    if name is not None and name.strip() != current["name"]:
        clean_name = name.strip()
        if len(clean_name) < 2:
            raise AcademicAdminError("A subject needs a name", 400)
        usage = await subject_usage(db, current["name"])
        if _in_use(usage):
            raise AcademicAdminError(
                f"The name of '{current['name']}' cannot change while it is in use "
                f"({_usage_text(usage)}). Archive it and create a new subject instead.",
                409,
            )
        other = await find_subject_by_name(db, clean_name)
        if other is not None and other.get("subject_id") != subject_id:
            raise AcademicAdminError(f"Subject '{other['name']}' already exists", 409)
        changes["name"] = clean_name
    if code is not None and (code.strip() or None) != current.get("code"):
        changes["code"] = code.strip() or None
    if branch is not None and (branch.strip() or None) != current.get("branch"):
        changes["branch"] = branch.strip() or None

    if not changes:
        return {"subject_id": subject_id, "changed": []}
    changed = sorted(changes)
    changes["updated_at"] = datetime.now(timezone.utc)
    await db[SUBJECTS_COLLECTION].update_one({"subject_id": subject_id}, {"$set": changes})
    await _audit(updated_by, "SUBJECT_UPDATED", subject_id, {"fields": changed})
    return {"subject_id": subject_id, "changed": changed}


async def set_subject_archived(
    db: AsyncIOMotorDatabase, subject_id: str, *, archived: bool, changed_by: dict[str, Any]
) -> dict[str, Any]:
    current = await _existing_subject(db, subject_id)
    target = STATUS_ARCHIVED if archived else STATUS_ACTIVE
    if record_status(current) == target:
        raise AcademicAdminError(
            f"This subject is already {'archived' if archived else 'active'}", 409
        )
    now = datetime.now(timezone.utc)
    update: dict[str, Any] = {"$set": {"status": target, "updated_at": now}}
    if archived:
        update["$set"]["archived_at"] = now
    else:
        update["$unset"] = {"archived_at": ""}
    await db[SUBJECTS_COLLECTION].update_one({"subject_id": subject_id}, update)
    usage = await subject_usage(db, current["name"])
    await _audit(
        changed_by,
        "SUBJECT_ARCHIVED" if archived else "SUBJECT_UNARCHIVED",
        subject_id,
        {"usage": usage},
    )
    return {"subject_id": subject_id, "status": target, "usage": usage}


async def delete_subject(
    db: AsyncIOMotorDatabase, subject_id: str, *, deleted_by: dict[str, Any]
) -> dict[str, Any]:
    current = await _existing_subject(db, subject_id)
    usage = await subject_usage(db, current["name"])
    if _in_use(usage):
        raise AcademicAdminError(
            f"'{current['name']}' is in use ({_usage_text(usage)}) and cannot be deleted. "
            "Archive it instead.",
            409,
        )
    await db[SUBJECTS_COLLECTION].delete_one({"subject_id": subject_id})
    await _audit(deleted_by, "SUBJECT_DELETED", subject_id, {})
    return {"status": "deleted", "subject_id": subject_id}
