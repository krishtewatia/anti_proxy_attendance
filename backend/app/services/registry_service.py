"""The admin's registries, organised Year > Branch > Section.

Students: every student account, approved or not, with the status the admin
needs to act on:

* APPROVED: their setup is approved (on rosters);
* CHANGE_WAITING: approved, and a change is waiting;
* WAITING: their first setup is waiting for approval;
* NO_SETUP: signed up, nothing sent yet (no section known).

Their section and groups come from the approved setup, or from the waiting
request when there is none. Teachers: every teacher with the classes they
take (from the classes' teacher lists), grouped by the cohorts of those
classes. No photos or face templates are returned, only photo URLs.
"""

from __future__ import annotations

from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.services import enrolment_service as enrolment
from app.services import organisation_service as org

APPROVED = "APPROVED"
CHANGE_WAITING = "CHANGE_WAITING"
WAITING = "WAITING"
NO_SETUP = "NO_SETUP"


async def _cohorts(db: AsyncIOMotorDatabase) -> dict[str, dict]:
    return {c["cohort_id"]: c async for c in db[org.COHORTS].find({}, {"_id": 0})}


async def students(db: AsyncIOMotorDatabase, filters: Optional[dict] = None) -> dict:
    filters = filters or {}
    cohorts = await _cohorts(db)
    enrolled = {e["user_id"]: e async for e in db[enrolment.ENROLMENTS].find({}, {"_id": 0})}
    waiting = {
        r["user_id"]: r
        async for r in db[enrolment.REQUESTS].find(
            {"status": enrolment.PENDING}, {"_id": 0, "template": 0}
        )
    }

    rows: list[dict[str, Any]] = []
    async for user in db["users"].find({"role": "STUDENT"}, {"password_hash": 0, "_id": 0}):
        user_id = user["user_id"]
        profile = await db["student_profiles"].find_one({"user_id": user_id}) or {}
        current, request = enrolled.get(user_id), waiting.get(user_id)
        if current:
            status = CHANGE_WAITING if request else APPROVED
            source = current
        elif request:
            status, source = WAITING, request
        else:
            status, source = NO_SETUP, {}
        cohort = cohorts.get(source.get("cohort_id", ""), {})
        rows.append(
            {
                "user_id": user_id,
                "name": profile.get("name"),
                "roll_number": profile.get("roll_number"),
                "email": user.get("email"),
                "status": status,
                "cohort_id": source.get("cohort_id"),
                "year": cohort.get("year"),
                "branch": cohort.get("branch"),
                "section": source.get("section"),
                "choices": source.get("choices") or {},
                "request_id": request["request_id"] if request else None,
                "has_photo": bool(profile.get("has_biometric")),
                "photo_url": profile.get("photo_url"),
                "registered_at": user.get("created_at"),
            }
        )

    # Counts for the navigator, before the filters: year > branch > section.
    counts: dict[str, Any] = {"no_setup": 0, "cohorts": {}}
    for row in rows:
        if not row["cohort_id"]:
            counts["no_setup"] += 1
            continue
        entry = counts["cohorts"].setdefault(
            row["cohort_id"], {"total": 0, "approved": 0, "waiting": 0, "sections": {}}
        )
        section = entry["sections"].setdefault(
            row["section"], {"total": 0, "approved": 0, "waiting": 0}
        )
        for bucket in (entry, section):
            bucket["total"] += 1
            if row["status"] in (APPROVED, CHANGE_WAITING):
                bucket["approved"] += 1
            if row["status"] in (WAITING, CHANGE_WAITING):
                bucket["waiting"] += 1

    def keep(row: dict) -> bool:
        if filters.get("status") and row["status"] != filters["status"]:
            return False
        if filters.get("cohort_id") and row["cohort_id"] != filters["cohort_id"]:
            return False
        if filters.get("section") and row["section"] != filters["section"].upper():
            return False
        if filters.get("set_code"):
            choice = row["choices"].get(filters["set_code"])
            if not choice:
                return False
            if filters.get("option") and choice["option"] != filters["option"].upper():
                return False
            if filters.get("group") and choice["group"] != filters["group"].upper():
                return False
        query = (filters.get("q") or "").strip().lower()
        if (
            query
            and query
            not in f"{row['name'] or ''} {row['roll_number'] or ''} {row['email'] or ''}".lower()
        ):
            return False
        return True

    shown = sorted(
        (r for r in rows if keep(r)),
        key=lambda r: (r["section"] or "~", str(r["roll_number"] or "")),
    )
    return {"students": shown, "counts": counts}


async def teachers(db: AsyncIOMotorDatabase) -> dict:
    cohorts = await _cohorts(db)
    subjects = {s["key"]: s async for s in db[org.SUBJECTS].find({}, {"_id": 0})}
    classes_by_teacher: dict[str, list[dict]] = {}
    async for cls in db[org.CLASSES].find({"teacher_ids.0": {"$exists": True}}, {"_id": 0}):
        subject = subjects.get(cls["subject_key"], {})
        for teacher_id in cls.get("teacher_ids") or []:
            classes_by_teacher.setdefault(teacher_id, []).append(
                {
                    "class_id": cls["class_id"],
                    "cohort_id": cls["cohort_id"],
                    "subject_key": cls["subject_key"],
                    "subject": subject.get("name", cls["subject_key"]),
                    "code": subject.get("code", ""),
                    "audience": cls["audience"],
                }
            )

    rows = []
    async for user in db["users"].find({"role": "TEACHER"}, {"password_hash": 0, "_id": 0}):
        profile = await db["teacher_profiles"].find_one({"user_id": user["user_id"]}) or {}
        classes = classes_by_teacher.get(user["user_id"], [])
        cohort_ids = sorted({c["cohort_id"] for c in classes})
        rows.append(
            {
                "user_id": user["user_id"],
                "name": profile.get("name"),
                "email": user.get("email"),
                "department": profile.get("department"),
                "approved": user.get("status", "APPROVED") == "APPROVED",
                "classes": classes,
                "cohorts": [
                    {
                        "cohort_id": cid,
                        "year": cohorts.get(cid, {}).get("year"),
                        "branch": cohorts.get(cid, {}).get("branch"),
                    }
                    for cid in cohort_ids
                ],
            }
        )
    rows.sort(key=lambda r: ((r["name"] or "").lower(), r["email"] or ""))
    return {"teachers": rows}
