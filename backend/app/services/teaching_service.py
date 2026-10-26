"""Teachers on the timetable: class assignment, the teacher's timetable, and
starting a session from a timetable slot.

A session started from a slot gets its roster from the approved enrolments of
that class (``enrolments.class_ids``), so every section and every group runs
its own session with its own students, all at the same time. There is at most
one session per slot and day (a unique index): two co-teachers pressing Start
together get the same session. Everything after creation (start, frames,
manual marks, finalize, export) is the existing session machinery.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import logging
from typing import Any, Optional
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from app.core.account_status import ACCOUNT_APPROVED, ACCOUNT_PENDING
from app.services import enrolment_service as enrolment
from app.services import organisation_service as org
from app.services.audit_service import record_audit_event

logger = logging.getLogger(__name__)

ASSIGNMENTS = "teacher_assignments"
# The college's clock: timetable times are India Standard Time.
COLLEGE_TZ = timezone(timedelta(hours=5, minutes=30))
DAY_CODES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


class TeachingError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ assignment


async def _check_teachers(db: AsyncIOMotorDatabase, teacher_ids: list[str]) -> None:
    found = {
        u["user_id"]
        async for u in db["users"].find(
            {"user_id": {"$in": teacher_ids}, "role": "TEACHER"}, {"user_id": 1}
        )
    }
    missing = sorted(set(teacher_ids) - found)
    if missing:
        raise TeachingError(f"Not a teacher account: {', '.join(missing)}", 404)


async def _record_changes(
    db: AsyncIOMotorDatabase, class_id: str, before: set[str], after: set[str], actor: dict
) -> None:
    now = _now()
    for teacher_id in sorted(after - before):
        await db[ASSIGNMENTS].insert_one(
            {
                "class_id": class_id,
                "teacher_id": teacher_id,
                "from": now,
                "to": None,
                "by": actor["user_id"],
            }
        )
    for teacher_id in sorted(before - after):
        await db[ASSIGNMENTS].update_many(
            {"class_id": class_id, "teacher_id": teacher_id, "to": None},
            {"$set": {"to": now, "ended_by": actor["user_id"]}},
        )


async def _approve_assigned(db: AsyncIOMotorDatabase, teacher_ids: set[str], actor: dict) -> None:
    """A teacher waiting for approval is approved by being given classes."""
    if teacher_ids:
        await db["users"].update_many(
            {"user_id": {"$in": sorted(teacher_ids)}, "role": "TEACHER", "status": ACCOUNT_PENDING},
            {
                "$set": {
                    "status": ACCOUNT_APPROVED,
                    "approved_by": actor["user_id"],
                    "approved_at": _now(),
                }
            },
        )


async def set_class_teachers(
    db: AsyncIOMotorDatabase, class_id: str, teacher_ids: list[str], actor: dict
) -> dict:
    cls = await db[org.CLASSES].find_one({"class_id": class_id})
    if cls is None:
        raise TeachingError("Class not found.", 404)
    wanted = list(dict.fromkeys(teacher_ids))
    await _check_teachers(db, wanted)
    before = set(cls.get("teacher_ids") or [])
    await db[org.CLASSES].update_one(
        {"class_id": class_id}, {"$set": {"teacher_ids": wanted, "updated_at": _now()}}
    )
    await _record_changes(db, class_id, before, set(wanted), actor)
    await _approve_assigned(db, set(wanted), actor)
    await record_audit_event(
        actor_user_id=actor["user_id"],
        actor_role=actor.get("role", "ADMIN"),
        action="TEACHER_ASSIGNED",
        resource_type="ACADEMIC",
        resource_id=class_id,
        metadata={"teacher_ids": wanted},
    )
    return {"class_id": class_id, "teacher_ids": wanted}


async def set_teacher_classes(
    db: AsyncIOMotorDatabase, teacher_id: str, class_ids: list[str], actor: dict
) -> dict:
    await _check_teachers(db, [teacher_id])
    wanted = set(class_ids)
    known = {
        c["class_id"]
        async for c in db[org.CLASSES].find({"class_id": {"$in": sorted(wanted)}}, {"class_id": 1})
    }
    if wanted - known:
        raise TeachingError(f"Unknown class: {', '.join(sorted(wanted - known))}", 404)
    current = {
        c["class_id"]
        async for c in db[org.CLASSES].find({"teacher_ids": teacher_id}, {"class_id": 1})
    }
    for class_id in sorted(wanted - current):
        await db[org.CLASSES].update_one(
            {"class_id": class_id}, {"$addToSet": {"teacher_ids": teacher_id}}
        )
        await _record_changes(db, class_id, set(), {teacher_id}, actor)
    for class_id in sorted(current - wanted):
        await db[org.CLASSES].update_one(
            {"class_id": class_id}, {"$pull": {"teacher_ids": teacher_id}}
        )
        await _record_changes(db, class_id, {teacher_id}, set(), actor)
    if wanted:
        await _approve_assigned(db, {teacher_id}, actor)
    await record_audit_event(
        actor_user_id=actor["user_id"],
        actor_role=actor.get("role", "ADMIN"),
        action="TEACHER_ASSIGNED",
        resource_type="USER",
        resource_id=teacher_id,
        metadata={"added": len(wanted - current), "removed": len(current - wanted)},
    )
    return {"teacher_id": teacher_id, "class_ids": sorted(wanted)}


# ------------------------------------------------------------------ timetable


async def _teacher_classes(db: AsyncIOMotorDatabase, teacher_id: str) -> dict[str, dict]:
    return {
        c["class_id"]: c
        async for c in db[org.CLASSES].find({"teacher_ids": teacher_id}, {"_id": 0})
    }


async def _slots_on(db: AsyncIOMotorDatabase, classes: dict[str, dict], day: date) -> list[dict]:
    """The teacher's slots on one day, from the version in force for each cohort, minus holidays."""
    if not classes:
        return []
    cohorts = sorted({c["cohort_id"] for c in classes.values()})
    versions = []
    for cohort_id in cohorts:
        version = await org.version_in_force(db, cohort_id, day)
        if version:
            versions.append(version["version_id"])
    if not versions:
        return []
    exceptions = [
        e
        async for e in db[org.CALENDAR].find(
            {"cohort_id": {"$in": cohorts}, "date": day.isoformat()}, {"_id": 0}
        )
    ]
    off_cohorts = {e["cohort_id"] for e in exceptions if not e.get("class_id")}
    off_classes = {e["class_id"] for e in exceptions if e.get("class_id")}
    slots = []
    query = {
        "version_id": {"$in": versions},
        "day": DAY_CODES[day.weekday()],
        "class_id": {"$in": sorted(classes)},
    }
    async for slot in db[org.SLOTS].find(query, {"_id": 0}).sort("start_minute", 1):
        cls = classes[slot["class_id"]]
        if cls["cohort_id"] in off_cohorts or slot["class_id"] in off_classes:
            continue
        slots.append(slot)
    return slots


def _slot_window(slot: dict, day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(
        day, time(slot["start_minute"] // 60, slot["start_minute"] % 60), COLLEGE_TZ
    )
    end = datetime.combine(day, time(slot["end_minute"] // 60, slot["end_minute"] % 60), COLLEGE_TZ)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


async def timetable(db: AsyncIOMotorDatabase, teacher_id: str, day: date) -> dict:
    classes = await _teacher_classes(db, teacher_id)
    subjects = {s["key"]: s async for s in db[org.SUBJECTS].find({}, {"_id": 0})}
    monday = day - timedelta(days=day.weekday())
    week_days = [monday + timedelta(days=i) for i in range(6)]
    today_slots = await _slots_on(db, classes, day)
    sessions = {
        s["slot_id"]: s
        async for s in db["sessions"].find(
            {"slot_id": {"$in": [s["slot_id"] for s in today_slots]}, "date": day.isoformat()},
            {"_id": 0},
        )
    }
    now = _now()

    def describe(slot: dict) -> dict:
        cls = classes[slot["class_id"]]
        subject = subjects.get(slot["subject_key"], {})
        return {
            "slot_id": slot["slot_id"],
            "class_id": slot["class_id"],
            "label": cls.get("label") or slot.get("label"),
            "subject": subject.get("name", slot["subject_key"]),
            "code": subject.get("code", ""),
            "audience": cls["audience"],
            "day": slot["day"],
            "start": slot["start"],
            "end": slot["end"],
            "periods": slot["periods"],
            "room": slot.get("room", ""),
        }

    today = []
    for slot in today_slots:
        session = sessions.get(slot["slot_id"])
        start, end = _slot_window(slot, day)
        if session is not None and session.get("status") == "FINALIZED":
            state = "DONE"
        elif session is not None and session.get("status") == "ACTIVE":
            state = "LIVE"
        elif now > end:
            state = "NOT_TAKEN"
        else:
            state = "UPCOMING"
        today.append(
            {
                **describe(slot),
                "state": state,
                "session_id": session["session_id"] if session else None,
                "starts_at": start,
            }
        )

    week = []
    for d in week_days:
        for slot in await _slots_on(db, classes, d):
            week.append({**describe(slot), "date": d.isoformat()})
    return {"date": day.isoformat(), "today": today, "week": week, "class_count": len(classes)}


# ------------------------------------------------------------------ start from a slot


async def _roster(db: AsyncIOMotorDatabase, class_id: str) -> list[dict]:
    """Approved students of this class: one query on the enrolments, one on the profiles."""
    user_ids = [
        e["user_id"]
        async for e in db[enrolment.ENROLMENTS].find({"class_ids": class_id}, {"user_id": 1})
    ]
    if not user_ids:
        return []
    approved = {
        u["user_id"]
        async for u in db["users"].find(
            {"user_id": {"$in": user_ids}, "status": ACCOUNT_APPROVED}, {"user_id": 1}
        )
    }
    profiles = (
        db["student_profiles"]
        .find({"user_id": {"$in": sorted(approved)}}, {"_id": 0})
        .sort("roll_number", 1)
    )
    return [p async for p in profiles if p.get("identity") or p.get("student_id")]


async def start_from_slot(db: AsyncIOMotorDatabase, teacher: dict, slot_id: str, day: date) -> dict:
    slot = await db[org.SLOTS].find_one({"slot_id": slot_id}, {"_id": 0})
    if slot is None:
        raise TeachingError("Timetable slot not found.", 404)
    cls = await db[org.CLASSES].find_one({"class_id": slot["class_id"]}, {"_id": 0})
    if cls is None or teacher["user_id"] not in (cls.get("teacher_ids") or []):
        raise TeachingError("This class is not assigned to you.", 403)

    existing = await db["sessions"].find_one(
        {"slot_id": slot_id, "date": day.isoformat()}, {"_id": 0}
    )
    if existing is not None:
        return {**existing, "created": False}
    if not any(s["slot_id"] == slot_id for s in await _slots_on(db, {cls["class_id"]: cls}, day)):
        raise TeachingError(
            "This slot is not on the timetable that day (or the day is a holiday).", 409
        )

    subject = await db[org.SUBJECTS].find_one({"key": slot["subject_key"]}, {"_id": 0}) or {}
    cohort = await db[org.COHORTS].find_one({"cohort_id": cls["cohort_id"]}, {"_id": 0}) or {}
    start, end = _slot_window(slot, day)
    session_id = f"session_{_now().strftime('%Y%m%d%H%M%S%f')}_{uuid4().hex[:6]}"
    audience = cls["audience"]
    document = {
        "session_id": session_id,
        "course_name": subject.get("name", slot["subject_key"]),
        "classroom_id": slot.get("room") or "ROOM",
        "start_time": start,
        "end_time": end,
        "class_code": cls.get("label") or cls["class_id"],
        "subject": subject.get("name", slot["subject_key"]),
        "branch": cohort.get("branch"),
        "section": audience.get("section") if audience["kind"] == "SECTION" else None,
        "required_presence_percentage": 100.0,
        "status": "SCHEDULED",
        "created_by": teacher["user_id"],
        "created_at": _now(),
        # The pilot's own fields: which class, slot and day, and how many periods.
        "class_id": cls["class_id"],
        "cohort_id": cls["cohort_id"],
        "slot_id": slot_id,
        "date": day.isoformat(),
        "periods": slot["periods"],
    }
    try:
        await db["sessions"].insert_one(dict(document))
    except DuplicateKeyError:
        # A co-teacher started the same slot at the same moment: use that session.
        existing = await db["sessions"].find_one(
            {"slot_id": slot_id, "date": day.isoformat()}, {"_id": 0}
        )
        return {**(existing or document), "created": False}

    students = await _roster(db, cls["class_id"])
    identities = [s.get("identity") or s.get("student_id") for s in students]
    # No roster document while nobody in the class is approved yet (a roster
    # always names at least one student).
    if identities:
        await db["session_rosters"].update_one(
            {"session_id": session_id},
            {"$set": {"session_id": session_id, "identities": identities}},
            upsert=True,
        )
    if students:
        now = _now()
        await db["attendance_records"].insert_many(
            [
                {
                    "attendance_id": f"att_{session_id}_{ident}",
                    "session_id": session_id,
                    "identity": ident,
                    "student_id": s.get("student_id", ident),
                    "student_name": s.get("name", ident),
                    "roll_number": s.get("roll_number"),
                    "status": "ABSENT",
                    "marked_at": None,
                    "presence_intervals": [],
                    "presence_duration_seconds": 0.0,
                    "presence_percentage": 0.0,
                    "required_presence_percentage": 0.0,
                    "requires_review": False,
                    "anomalies": [],
                    "updated_at": now,
                }
                for s, ident in zip(students, identities)
            ]
        )
    await record_audit_event(
        actor_user_id=teacher["user_id"],
        actor_role=teacher.get("role", "TEACHER"),
        action="SESSION_CREATED",
        resource_type="SESSION",
        resource_id=session_id,
        metadata={
            "class_id": cls["class_id"],
            "slot_id": slot_id,
            "date": day.isoformat(),
            "roster": len(identities),
        },
    )
    return {**document, "roster_size": len(identities), "created": True}


def parse_day(value: Optional[str]) -> date:
    if not value:
        return datetime.now(COLLEGE_TZ).date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise TeachingError("Give the date as YYYY-MM-DD.") from exc


def public_session(doc: dict[str, Any]) -> dict:
    keep = (
        "session_id",
        "course_name",
        "class_code",
        "class_id",
        "slot_id",
        "date",
        "periods",
        "status",
        "start_time",
        "end_time",
        "created",
        "roster_size",
    )
    return {k: doc.get(k) for k in keep if k in doc}
