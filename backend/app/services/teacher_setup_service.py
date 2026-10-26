"""Teachers choose their own classes; an administrator approves.

A teacher signs in straight after sign-up and, under My Classes, picks their
year and branch, the subjects they teach, and for each subject the sections
or groups. That is one request (a list of classes: subject x section or
group). An administrator approves it as it is, adjusts it and approves, or
rejects it with a reason. Approval goes through the same assignment as the
administrator's own "Assign classes" (history, approval of a waiting teacher,
audit). A later change is a new request; the approved classes stay in force
until it is approved.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.services import organisation_service as org
from app.services import teaching_service as teaching
from app.services.audit_service import record_audit_event

REQUESTS = "teacher_requests"
PENDING, APPROVED, REJECTED, WITHDRAWN = "PENDING", "APPROVED", "REJECTED", "WITHDRAWN"


class TeacherSetupError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _target(audience: dict) -> dict:
    if audience["kind"] == "SECTION":
        return {
            "kind": "SECTION",
            "code": audience["section"],
            "label": f"Section {audience['section']}",
        }
    plain = audience["option_code"] in (audience["group_code"], audience["set_code"])
    group = (
        audience["group_code"] if plain else f"{audience['option_code']} {audience['group_code']}"
    )
    return {
        "kind": "GROUP",
        "code": f"{audience['set_code']}/{audience['option_code']}/{audience['group_code']}",
        "label": f"{audience['set_code']} {group}",
    }


async def options(db: AsyncIOMotorDatabase) -> dict:
    """Years and branches, each subject with the sections or groups it is taught to."""
    terms = [t["term_id"] async for t in db[org.TERMS].find({"status": {"$ne": "CLOSED"}})]
    subjects = {s["key"]: s async for s in db[org.SUBJECTS].find({}, {"_id": 0})}
    cohorts = []
    async for cohort in db[org.COHORTS].find({"term_id": {"$in": terms}}, {"_id": 0}):
        by_subject: dict[str, dict] = {}
        async for cls in (
            db[org.CLASSES].find({"cohort_id": cohort["cohort_id"]}, {"_id": 0}).sort("class_id", 1)
        ):
            subject = subjects.get(cls["subject_key"], {})
            entry = by_subject.setdefault(
                cls["subject_key"],
                {
                    "subject_key": cls["subject_key"],
                    "code": subject.get("code", ""),
                    "name": subject.get("name", cls["subject_key"]),
                    "type": subject.get("type", ""),
                    "targets": [],
                },
            )
            entry["targets"].append({**_target(cls["audience"]), "class_id": cls["class_id"]})
        for entry in by_subject.values():
            # Sections first, then groups.
            entry["targets"].sort(key=lambda t: (t["kind"] != "SECTION", t["label"]))
        cohorts.append(
            {
                "cohort_id": cohort["cohort_id"],
                "name": cohort.get("name"),
                "year": cohort.get("year"),
                "branch": cohort.get("branch"),
                "subjects": sorted(by_subject.values(), key=lambda s: s["name"]),
            }
        )
    cohorts.sort(key=lambda c: (-(c["year"] or 0), c["branch"] or ""))
    return {"cohorts": cohorts}


async def _labels(db: AsyncIOMotorDatabase, class_ids: list[str]) -> list[dict]:
    subjects = {s["key"]: s async for s in db[org.SUBJECTS].find({}, {"_id": 0})}
    out = []
    async for cls in db[org.CLASSES].find({"class_id": {"$in": class_ids}}, {"_id": 0}):
        subject = subjects.get(cls["subject_key"], {})
        out.append(
            {
                "class_id": cls["class_id"],
                "cohort_id": cls["cohort_id"],
                "subject": subject.get("name", cls["subject_key"]),
                "code": subject.get("code", ""),
                **{"target": _target(cls["audience"])["label"]},
            }
        )
    return sorted(out, key=lambda c: (c["subject"], c["target"]))


def _public(doc: Optional[dict]) -> Optional[dict]:
    if not doc:
        return None
    return {
        k: doc.get(k)
        for k in ("request_id", "status", "class_ids", "reason", "submitted_at", "decided_at")
    }


async def my_status(db: AsyncIOMotorDatabase, user: dict) -> dict:
    current = [
        c["class_id"]
        async for c in db[org.CLASSES].find({"teacher_ids": user["user_id"]}, {"class_id": 1})
    ]
    latest = await db[REQUESTS].find_one(
        {"user_id": user["user_id"]}, {"_id": 0}, sort=[("submitted_at", -1)]
    )
    return {
        "approved": user.get("status", "APPROVED") == "APPROVED",
        "classes": await _labels(db, current),
        "latest_request": _public(latest),
    }


async def submit(db: AsyncIOMotorDatabase, user: dict, class_ids: list[str]) -> dict:
    wanted = list(dict.fromkeys(class_ids))
    if not wanted:
        raise TeacherSetupError("Choose at least one subject and where you teach it.")
    known = {
        c["class_id"]
        async for c in db[org.CLASSES].find({"class_id": {"$in": wanted}}, {"class_id": 1})
    }
    if set(wanted) - known:
        raise TeacherSetupError("Some of the chosen classes do not exist.", 404)
    if await db[REQUESTS].find_one({"user_id": user["user_id"], "status": PENDING}):
        raise TeacherSetupError(
            "Your earlier request is still waiting. Withdraw it first to change it.", 409
        )
    doc = {
        "request_id": f"treq_{uuid4().hex}",
        "user_id": user["user_id"],
        "class_ids": wanted,
        "status": PENDING,
        "submitted_at": _now(),
    }
    await db[REQUESTS].insert_one(dict(doc))
    await record_audit_event(
        actor_user_id=user["user_id"],
        actor_role="TEACHER",
        action="TEACHER_CLASSES_REQUESTED",
        resource_type="USER",
        resource_id=user["user_id"],
        metadata={"request_id": doc["request_id"], "classes": len(wanted)},
    )
    return _public(doc) or {}


async def withdraw(db: AsyncIOMotorDatabase, user: dict) -> dict:
    result = await db[REQUESTS].update_one(
        {"user_id": user["user_id"], "status": PENDING},
        {"$set": {"status": WITHDRAWN, "decided_at": _now()}},
    )
    if not result.modified_count:
        raise TeacherSetupError("You have no request waiting.", 404)
    return {"status": WITHDRAWN}


async def waiting(db: AsyncIOMotorDatabase) -> list[dict]:
    out: list[dict[str, Any]] = []
    async for req in db[REQUESTS].find({"status": PENDING}, {"_id": 0}).sort("submitted_at", 1):
        user = (
            await db["users"].find_one({"user_id": req["user_id"]}, {"email": 1, "status": 1}) or {}
        )
        profile = (
            await db["teacher_profiles"].find_one({"user_id": req["user_id"]}, {"name": 1}) or {}
        )
        current = [
            c["class_id"]
            async for c in db[org.CLASSES].find({"teacher_ids": req["user_id"]}, {"class_id": 1})
        ]
        out.append(
            {
                **(_public(req) or {}),
                "user_id": req["user_id"],
                "name": profile.get("name"),
                "email": user.get("email"),
                "change": bool(current),
                "classes": await _labels(db, req["class_ids"]),
            }
        )
    return out


async def _pending(db: AsyncIOMotorDatabase, request_id: str) -> dict:
    req = await db[REQUESTS].find_one({"request_id": request_id})
    if req is None:
        raise TeacherSetupError("Request not found.", 404)
    if req["status"] != PENDING:
        raise TeacherSetupError("This request is not waiting for a decision.", 409)
    return req


async def approve(
    db: AsyncIOMotorDatabase, request_id: str, actor: dict, class_ids: Optional[list[str]] = None
) -> dict:
    req = await _pending(db, request_id)
    final = list(dict.fromkeys(class_ids)) if class_ids is not None else req["class_ids"]
    try:
        await teaching.set_teacher_classes(db, req["user_id"], final, actor)
    except teaching.TeachingError as exc:
        raise TeacherSetupError(str(exc), exc.status_code) from exc
    adjusted = sorted(final) != sorted(req["class_ids"])
    await db[REQUESTS].update_one(
        {"request_id": request_id},
        {
            "$set": {
                "status": APPROVED,
                "approved_class_ids": final,
                "adjusted": adjusted,
                "decided_by": actor["user_id"],
                "decided_at": _now(),
            }
        },
    )
    await record_audit_event(
        actor_user_id=actor["user_id"],
        actor_role="ADMIN",
        action="TEACHER_CLASSES_APPROVED",
        resource_type="USER",
        resource_id=req["user_id"],
        metadata={"request_id": request_id, "classes": len(final), "adjusted": adjusted},
    )
    return {"request_id": request_id, "status": APPROVED, "class_ids": final, "adjusted": adjusted}


async def reject(db: AsyncIOMotorDatabase, request_id: str, actor: dict, reason: str) -> dict:
    text = (reason or "").strip()
    if not text:
        raise TeacherSetupError("Give a reason; the teacher sees it.")
    req = await _pending(db, request_id)
    await db[REQUESTS].update_one(
        {"request_id": request_id},
        {
            "$set": {
                "status": REJECTED,
                "reason": text[:300],
                "decided_by": actor["user_id"],
                "decided_at": _now(),
            }
        },
    )
    await record_audit_event(
        actor_user_id=actor["user_id"],
        actor_role="ADMIN",
        action="TEACHER_CLASSES_REJECTED",
        resource_type="USER",
        resource_id=req["user_id"],
        metadata={"request_id": request_id},
    )
    return {"request_id": request_id, "status": REJECTED}
