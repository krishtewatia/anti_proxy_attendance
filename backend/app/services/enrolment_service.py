"""Student self-setup and its approval (the pilot's enrolment).

A student who has signed up chooses, in one request:

* their year (cohort) and section; the section's core classes follow from it;
* one option + group in each elective set (DE-II, DE-III) and the DLDA
  workshop group, by code only;
* two or three face photos (first request; optional on a later change),
  after accepting the photo notice.

An administrator approves or rejects the request, one by one or in bulk.
Approval of the first request makes the student eligible for attendance:
the account becomes APPROVED, so they appear on rosters, and their face
template becomes ACTIVE, so they can be recognised. A later change creates a
new request; the approved enrolment and face template stay in force until the
change is approved. Rejecting keeps the account; the student sees the reason
and can send a new request.

Audit entries hold IDs, codes and counts only; photos and embeddings are
never logged.
"""

from __future__ import annotations

from datetime import datetime, timezone
import base64
import binascii
import logging
import shutil
from typing import Any, Optional
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.account_status import ACCOUNT_APPROVED, ACCOUNT_PENDING, TEMPLATE_ACTIVE
from app.core.uploads import enrolment_photo_dir, enrolment_photo_path, student_photo_path
from app.services import organisation_service as org
from app.services import photo_quality
from app.services import student_biometric_service
from app.services import student_deletion
from app.services.audit_service import record_audit_event
from app.services.registration_rules import (
    CONSENT_NOTICE_VERSION,
    RegistrationRuleError,
    check_consent_version,
    record_consent,
)

logger = logging.getLogger(__name__)

REQUESTS = "enrolment_requests"
ENROLMENTS = "enrolments"

PENDING = "PENDING"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
WITHDRAWN = "WITHDRAWN"
SUPERSEDED = "SUPERSEDED"
FIRST = "FIRST"
CHANGE = "CHANGE"


class EnrolmentError(Exception):
    def __init__(self, message: str, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _decode_photo(value: str) -> bytes:
    raw = (value or "").strip()
    if "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EnrolmentError("A photo could not be read; send it again.") from exc


# ------------------------------------------------------------------ options


async def _active_cohorts(db: AsyncIOMotorDatabase) -> list[dict]:
    terms = [t["term_id"] async for t in db[org.TERMS].find({"status": {"$ne": "CLOSED"}})]
    return [c async for c in db[org.COHORTS].find({"term_id": {"$in": terms}}, {"_id": 0})]


async def _group_sets(db: AsyncIOMotorDatabase, cohort_id: str) -> list[dict]:
    sets = [s async for s in db[org.GROUP_SETS].find({"cohort_id": cohort_id}, {"_id": 0})]
    # Electives first (DE-II, DE-III), then workshops (DLDA).
    return sorted(sets, key=lambda s: (s["kind"] != "ELECTIVE", s["set_code"]))


async def _class_summary(db: AsyncIOMotorDatabase, query: dict) -> list[dict]:
    subjects = {s["key"]: s async for s in db[org.SUBJECTS].find({}, {"_id": 0})}
    classes = []
    async for doc in db[org.CLASSES].find(query, {"_id": 0}).sort("class_id", 1):
        subject = subjects.get(doc["subject_key"], {})
        classes.append(
            {
                "class_id": doc["class_id"],
                "subject_key": doc["subject_key"],
                "code": subject.get("code", ""),
                "name": subject.get("name", doc["subject_key"]),
                "type": subject.get("type", ""),
            }
        )
    return classes


async def options(db: AsyncIOMotorDatabase) -> dict:
    """What the setup wizard offers: years, sections with their core classes, and group sets."""
    cohorts = []
    for cohort in await _active_cohorts(db):
        cohort_id = cohort["cohort_id"]
        sections = []
        codes = sorted([s["code"] async for s in db[org.SECTIONS].find({"cohort_id": cohort_id})])
        for code in codes:
            sections.append(
                {
                    "code": code,
                    "core_classes": await _class_summary(
                        db,
                        {
                            "cohort_id": cohort_id,
                            "audience.kind": "SECTION",
                            "audience.section": code,
                        },
                    ),
                }
            )
        cohorts.append(
            {
                "cohort_id": cohort_id,
                "name": cohort.get("name", cohort_id),
                "branch": cohort.get("branch"),
                "year": cohort.get("year"),
                "semester": cohort.get("semester"),
                "term_id": cohort.get("term_id"),
                "sections": sections,
                "group_sets": [
                    {
                        "set_code": s["set_code"],
                        "kind": s["kind"],
                        "name": s.get("name", s["set_code"]),
                        "options": [
                            {
                                "option_code": o["option_code"],
                                "name": o.get("name", o["option_code"]),
                                "groups": o["groups"],
                            }
                            for o in s["options"]
                        ],
                    }
                    for s in await _group_sets(db, cohort_id)
                ],
            }
        )
    untracked = [
        {"code": s.get("code", ""), "name": s.get("name", s["key"])}
        async for s in db[org.SUBJECTS].find({"tracked": False}, {"_id": 0})
    ]
    return {
        "cohorts": cohorts,
        "not_counted": untracked,
        "consent_version": CONSENT_NOTICE_VERSION,
        "photos": {"min": photo_quality.MIN_PHOTOS, "max": photo_quality.MAX_PHOTOS},
    }


async def resolve_choices(
    db: AsyncIOMotorDatabase, cohort_id: str, section: str, choices: dict
) -> tuple[dict, list[str], dict]:
    """Check a section and group choices; return (choices, class_ids, cohort)."""
    cohort = next((c for c in await _active_cohorts(db) if c["cohort_id"] == cohort_id), None)
    if cohort is None:
        raise EnrolmentError("Choose your year from the list.", 400)
    section = (section or "").strip().upper()
    if await db[org.SECTIONS].find_one({"cohort_id": cohort_id, "code": section}) is None:
        raise EnrolmentError("Choose your section from the list.", 400)

    sets = await _group_sets(db, cohort_id)
    unknown = set(choices or {}) - {s["set_code"] for s in sets}
    if unknown:
        raise EnrolmentError(f"Unknown group set: {', '.join(sorted(unknown))}", 400)
    clean: dict[str, dict] = {}
    group_queries = []
    for group_set in sets:
        code = group_set["set_code"]
        choice = (choices or {}).get(code) or {}
        option = str(choice.get("option") or "").strip().upper()
        group = str(choice.get("group") or "").strip().upper()
        if not option or not group:
            raise EnrolmentError(f"Choose your {code} option and group.", 400)
        if not org.valid_group_choice(group_set, option, group):
            raise EnrolmentError(f"{option} / {group} is not a {code} group.", 400)
        clean[code] = {"option": option, "group": group}
        group_queries.append(
            {
                "audience.kind": "GROUP",
                "audience.set_code": code,
                "audience.option_code": option,
                "audience.group_code": group,
            }
        )

    query = {
        "cohort_id": cohort_id,
        "$or": [{"audience.kind": "SECTION", "audience.section": section}, *group_queries],
    }
    class_ids = [doc["class_id"] async for doc in db[org.CLASSES].find(query, {"class_id": 1})]
    return {"section": section, "groups": clean}, sorted(class_ids), cohort


# ------------------------------------------------------------------ photos


async def check_one_photo(photo_base64: str) -> photo_quality.PhotoCheck:
    data = _decode_photo(photo_base64)
    extraction = await student_biometric_service.extract_face(data)
    if extraction is None:
        raise EnrolmentError("Photos cannot be checked right now. Try again in a moment.", 503)
    return photo_quality.check_photo(data, extraction)


async def _check_photos(photos: list[str]) -> tuple[list[bytes], list[photo_quality.PhotoCheck]]:
    if not photo_quality.MIN_PHOTOS <= len(photos) <= photo_quality.MAX_PHOTOS:
        raise EnrolmentError(
            f"Add {photo_quality.MIN_PHOTOS} or {photo_quality.MAX_PHOTOS} photos of your face.",
            400,
        )
    blobs, checks = [], []
    for photo in photos:
        data = _decode_photo(photo)
        extraction = await student_biometric_service.extract_face(data)
        if extraction is None:
            raise EnrolmentError("Photos cannot be checked right now. Try again in a moment.", 503)
        blobs.append(data)
        checks.append(photo_quality.check_photo(data, extraction))
    if not all(c.ok for c in checks):
        raise EnrolmentError(
            "Some photos are not good enough.", 400, details=[c.public() for c in checks]
        )
    if not photo_quality.same_person([c.embedding or [] for c in checks]):
        raise EnrolmentError("The photos do not all show the same person.", 400)
    return blobs, checks


# ------------------------------------------------------------------ student side


def _public_request(doc: Optional[dict]) -> Optional[dict]:
    if not doc:
        return None
    return {
        key: doc.get(key)
        for key in (
            "request_id",
            "kind",
            "status",
            "cohort_id",
            "section",
            "choices",
            "class_ids",
            "photo_count",
            "submitted_at",
            "decided_at",
            "reason",
        )
    }


async def my_status(db: AsyncIOMotorDatabase, user: dict) -> dict:
    enrolment = await db[ENROLMENTS].find_one({"user_id": user["user_id"]}, {"_id": 0})
    latest = await db[REQUESTS].find_one(
        {"user_id": user["user_id"]}, {"_id": 0, "template": 0}, sort=[("submitted_at", -1)]
    )
    return {
        "eligible": user.get("status") == ACCOUNT_APPROVED,
        "enrolment": enrolment,
        "latest_request": _public_request(latest),
    }


async def submit_request(db: AsyncIOMotorDatabase, user: dict, payload: dict) -> dict:
    user_id = user["user_id"]
    profile = await db["student_profiles"].find_one({"user_id": user_id})
    if profile is None:
        raise EnrolmentError("Your student profile was not found.", 404)
    if await db[REQUESTS].find_one({"user_id": user_id, "status": PENDING}):
        raise EnrolmentError(
            "Your earlier request is still waiting. Withdraw it first to change it.", 409
        )

    choices, class_ids, cohort = await resolve_choices(
        db, payload.get("cohort_id", ""), payload.get("section", ""), payload.get("choices") or {}
    )
    current = await db[ENROLMENTS].find_one({"user_id": user_id, "term_id": cohort["term_id"]})
    kind = CHANGE if current else FIRST
    photos = payload.get("photos") or []
    if kind == FIRST and not photos:
        raise EnrolmentError(
            f"Add {photo_quality.MIN_PHOTOS} or {photo_quality.MAX_PHOTOS} photos of your face.",
            400,
        )

    template = None
    blobs: list[bytes] = []
    if photos:
        try:
            check_consent_version(payload.get("consent_version"))
        except RegistrationRuleError as exc:
            raise EnrolmentError(str(exc), 400) from exc
        blobs, checks = await _check_photos(photos)
        template = photo_quality.mean_template([c.embedding or [] for c in checks])
        await record_consent(db, user_id, CONSENT_NOTICE_VERSION)

    request_id = f"req_{uuid4().hex}"
    now = _now()
    if blobs:
        folder = enrolment_photo_dir(request_id)
        folder.mkdir(parents=True, exist_ok=True)
        for index, data in enumerate(blobs):
            enrolment_photo_path(request_id, index).write_bytes(data)

    doc = {
        "request_id": request_id,
        "user_id": user_id,
        "identity": profile.get("identity") or profile.get("student_id"),
        "term_id": cohort["term_id"],
        "cohort_id": cohort["cohort_id"],
        "branch": cohort.get("branch"),
        "year": cohort.get("year"),
        "section": choices["section"],
        "choices": choices["groups"],
        "class_ids": class_ids,
        "photo_count": len(blobs),
        "template": template,
        "kind": kind,
        "status": PENDING,
        "submitted_at": now,
    }
    await db[REQUESTS].insert_one(doc)
    await record_audit_event(
        actor_user_id=user_id,
        actor_role="STUDENT",
        action="ENROLMENT_REQUESTED",
        resource_type="USER",
        resource_id=user_id,
        metadata={
            "request_id": request_id,
            "kind": kind,
            "section": choices["section"],
            "groups": {k: f"{v['option']}/{v['group']}" for k, v in choices["groups"].items()},
            "photos": len(blobs),
        },
    )
    return _public_request(doc) or {}


def _discard_photos(request_id: str) -> None:
    try:
        folder = enrolment_photo_dir(request_id)
        if folder.is_dir():
            shutil.rmtree(folder)
    except (ValueError, OSError) as exc:
        logger.warning("Could not remove setup photos: %s", type(exc).__name__)


async def withdraw_request(db: AsyncIOMotorDatabase, user: dict) -> dict:
    request = await db[REQUESTS].find_one({"user_id": user["user_id"], "status": PENDING})
    if request is None:
        raise EnrolmentError("You have no request waiting.", 404)
    await db[REQUESTS].update_one(
        {"request_id": request["request_id"]},
        {"$set": {"status": WITHDRAWN, "decided_at": _now()}, "$unset": {"template": ""}},
    )
    _discard_photos(request["request_id"])
    await record_audit_event(
        actor_user_id=user["user_id"],
        actor_role="STUDENT",
        action="ENROLMENT_WITHDRAWN",
        resource_type="USER",
        resource_id=user["user_id"],
        metadata={"request_id": request["request_id"]},
    )
    return {"status": WITHDRAWN, "request_id": request["request_id"]}


# ------------------------------------------------------------------ admin side


async def list_requests(db: AsyncIOMotorDatabase, filters: dict) -> dict:
    """Requests (newest last) and counts of waiting ones per branch, year and section."""
    query: dict[str, Any] = {"status": filters.get("status") or PENDING}
    for key in ("cohort_id", "section"):
        if filters.get(key):
            query[key] = filters[key].upper() if key == "section" else filters[key]
    if filters.get("set_code"):
        query[f"choices.{filters['set_code']}"] = {"$exists": True}
        if filters.get("option"):
            query[f"choices.{filters['set_code']}.option"] = filters["option"].upper()
        if filters.get("group"):
            query[f"choices.{filters['set_code']}.group"] = filters["group"].upper()

    items = []
    async for doc in db[REQUESTS].find(query, {"_id": 0, "template": 0}).sort("submitted_at", 1):
        profile = await db["student_profiles"].find_one({"user_id": doc["user_id"]}) or {}
        items.append(
            {
                **(_public_request(doc) or {}),
                "user_id": doc["user_id"],
                "branch": doc.get("branch"),
                "year": doc.get("year"),
                "name": profile.get("name"),
                "roll_number": profile.get("roll_number"),
                "email": profile.get("email"),
                "photo_urls": [
                    f"/api/v1/admin/enrolment/requests/{doc['request_id']}/photos/{i}"
                    for i in range(doc.get("photo_count") or 0)
                ],
                "current_photo_url": profile.get("photo_url")
                if doc.get("kind") == CHANGE
                else None,
            }
        )

    counts: dict[str, dict] = {}
    async for doc in db[REQUESTS].find(
        {"status": PENDING}, {"branch": 1, "year": 1, "cohort_id": 1, "section": 1}
    ):
        branch = counts.setdefault(
            doc.get("branch") or "", {"branch": doc.get("branch"), "total": 0, "years": {}}
        )
        branch["total"] += 1
        year = branch["years"].setdefault(
            doc["cohort_id"],
            {"cohort_id": doc["cohort_id"], "year": doc.get("year"), "total": 0, "sections": {}},
        )
        year["total"] += 1
        year["sections"][doc["section"]] = year["sections"].get(doc["section"], 0) + 1
    tree = [
        {
            **b,
            "years": [
                {**y, "sections": dict(sorted(y["sections"].items()))} for y in b["years"].values()
            ],
        }
        for b in counts.values()
    ]
    return {"requests": items, "counts": tree}


async def _pending_request(db: AsyncIOMotorDatabase, request_id: str) -> dict:
    request = await db[REQUESTS].find_one({"request_id": request_id})
    if request is None:
        raise EnrolmentError("Setup request not found.", 404)
    if request["status"] != PENDING:
        raise EnrolmentError("This request is not waiting for a decision.", 409)
    return request


async def _apply_approval(db: AsyncIOMotorDatabase, request: dict, actor: dict) -> bool:
    """Make the request's data the student's; returns whether the face template changed."""
    now = _now()
    user_id, identity = request["user_id"], request["identity"]
    template_changed = False
    profile_update: dict[str, Any] = {
        "branch": request.get("branch") or "",
        "section": request["section"],
        "updated_at": now,
    }
    if request.get("photo_count") and request.get("template"):
        # The first photo becomes the profile photo; the template goes live.
        target = student_photo_path(identity)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(enrolment_photo_path(request["request_id"], 0).read_bytes())
        await db["biometric_profiles"].update_one(
            {"identity": identity},
            {
                "$set": {
                    "identity": identity,
                    "mean_embedding": request["template"],
                    "sample_count": request["photo_count"],
                    "quality_score": 0.95,
                    "enrolled_by": user_id,
                    "review_status": TEMPLATE_ACTIVE,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        profile_update.update(
            {"has_biometric": True, "photo_url": f"/api/v1/students/{identity}/photo"}
        )
        template_changed = True
    await db["student_profiles"].update_one({"user_id": user_id}, {"$set": profile_update})

    await db[ENROLMENTS].update_one(
        {"user_id": user_id, "term_id": request["term_id"]},
        {
            "$set": {
                "user_id": user_id,
                "identity": identity,
                "term_id": request["term_id"],
                "cohort_id": request["cohort_id"],
                "section": request["section"],
                "choices": request["choices"],
                "class_ids": request["class_ids"],
                "approved_request_id": request["request_id"],
                "since": now,
            }
        },
        upsert=True,
    )
    await db[REQUESTS].update_many(
        {"user_id": user_id, "status": APPROVED}, {"$set": {"status": SUPERSEDED}}
    )
    await db[REQUESTS].update_one(
        {"request_id": request["request_id"]},
        {
            "$set": {"status": APPROVED, "decided_by": actor["user_id"], "decided_at": now},
            "$unset": {"template": ""},
        },
    )
    # Eligible for attendance from now on.
    await db["users"].update_one(
        {"user_id": user_id, "status": ACCOUNT_PENDING},
        {"$set": {"status": ACCOUNT_APPROVED, "approved_by": actor["user_id"], "approved_at": now}},
    )
    _discard_photos(request["request_id"])
    await record_audit_event(
        actor_user_id=actor["user_id"],
        actor_role=actor.get("role", "ADMIN"),
        action="ENROLMENT_APPROVED",
        resource_type="USER",
        resource_id=user_id,
        metadata={
            "request_id": request["request_id"],
            "kind": request["kind"],
            "section": request["section"],
            "classes": len(request["class_ids"]),
            "face_template_changed": template_changed,
        },
    )
    return template_changed


async def _apply_rejection(
    db: AsyncIOMotorDatabase, request: dict, actor: dict, reason: str
) -> None:
    await db[REQUESTS].update_one(
        {"request_id": request["request_id"]},
        {
            "$set": {
                "status": REJECTED,
                "reason": reason,
                "decided_by": actor["user_id"],
                "decided_at": _now(),
            },
            "$unset": {"template": ""},
        },
    )
    _discard_photos(request["request_id"])
    await record_audit_event(
        actor_user_id=actor["user_id"],
        actor_role=actor.get("role", "ADMIN"),
        action="ENROLMENT_REJECTED",
        resource_type="USER",
        resource_id=request["user_id"],
        metadata={"request_id": request["request_id"], "kind": request["kind"]},
    )


def _clean_reason(reason: Optional[str]) -> str:
    text = (reason or "").strip()
    if not text:
        raise EnrolmentError("Give a reason; the student sees it.", 400)
    return text[:300]


async def decide(
    db: AsyncIOMotorDatabase,
    request_ids: list[str],
    *,
    action: str,
    actor: dict,
    reason: Optional[str] = None,
) -> dict:
    """Approve or reject one or more waiting requests. Each one is audited on its own."""
    if action not in ("approve", "reject"):
        raise EnrolmentError("Unknown action.", 400)
    if not request_ids:
        raise EnrolmentError("Select at least one request.", 400)
    text = _clean_reason(reason) if action == "reject" else ""
    requests = [await _pending_request(db, rid) for rid in dict.fromkeys(request_ids)]
    template_changed = False
    for request in requests:
        if action == "approve":
            template_changed = await _apply_approval(db, request, actor) or template_changed
        else:
            await _apply_rejection(db, request, actor, text)
    refreshed = await student_deletion._refresh_vision_gallery() if action == "approve" else False
    return {
        "action": action,
        "done": [r["request_id"] for r in requests],
        "vision_gallery_refreshed": refreshed,
    }


async def photo_bytes(db: AsyncIOMotorDatabase, request_id: str, index: int) -> bytes:
    request = await db[REQUESTS].find_one({"request_id": request_id})
    if request is None or index >= (request.get("photo_count") or 0):
        raise EnrolmentError("Photo not found.", 404)
    try:
        return enrolment_photo_path(request_id, index).read_bytes()
    except (ValueError, OSError) as exc:
        raise EnrolmentError("Photo not found.", 404) from exc


async def has_submitted_request(db: AsyncIOMotorDatabase, user_id: str) -> bool:
    return await db[REQUESTS].find_one({"user_id": user_id, "status": PENDING}) is not None
