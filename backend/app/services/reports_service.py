"""Attendance reports for timetable classes: the student's subject-wise view,
the lecture-wise list, a class's student list and its register.

Counting (lectures, not sessions):

* held: lectures of the class's timetable sessions in which a round was held;
* present / absent: the student's lectures in those sessions;
* not entered: timetable slots of the class from the term start (or the date
  the timetable came into force) up to today, minus holidays and cancelled
  classes, that have no held session; shown apart and never in the percentage;
* percentage = present / held.

Each report reads what it needs with a handful of indexed queries and
computes in memory: no query per student or per day.
"""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
import io
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.services import enrolment_service as enrolment
from app.services import organisation_service as org
from app.services.rounds_service import held_rounds
from app.services.teaching_service import COLLEGE_TZ, DAY_CODES

RECORD_FIELDS = {"identity": 1, "session_id": 1, "lectures": 1, "rounds": 1}


class ReportError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def today() -> date:
    return datetime.now(COLLEGE_TZ).date()


def _local_time(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(COLLEGE_TZ).strftime("%H:%M")
    return ""


def percentage(present: int, held: int) -> Optional[float]:
    return round(100.0 * present / held, 1) if held else None


# ------------------------------------------------------------------ shared reads


async def _held_sessions(
    db: AsyncIOMotorDatabase, class_ids: list[str], until: date, since: Optional[date] = None
) -> list[dict]:
    query: dict[str, Any] = {"class_id": {"$in": class_ids}, "date": {"$lte": until.isoformat()}}
    if since:
        query["date"]["$gte"] = since.isoformat()
    sessions = [s async for s in db["sessions"].find(query, {"_id": 0})]
    held = [s for s in sessions if held_rounds(s)]
    # Sorted by day and class time (the stored time may or may not carry a zone).
    return sorted(held, key=lambda s: (s["date"], _local_time(s.get("start_time"))))


async def _not_entered(
    db: AsyncIOMotorDatabase, classes: dict[str, dict], until: date
) -> dict[str, int]:
    """Lectures per class with no held session, from the term start (or the timetable's start) to ``until``."""
    if not classes:
        return {}
    cohorts = sorted({c["cohort_id"] for c in classes.values()})
    out = {cid: 0 for cid in classes}
    for cohort_id in cohorts:
        cohort = await db[org.COHORTS].find_one({"cohort_id": cohort_id}) or {}
        term = await db[org.TERMS].find_one({"term_id": cohort.get("term_id")}) or {}
        versions = [
            v
            async for v in db[org.VERSIONS]
            .find({"cohort_id": cohort_id, "status": "ACTIVE"}, {"_id": 0})
            .sort("effective_from", 1)
        ]
        if not versions:
            continue
        start = date.fromisoformat(versions[0]["effective_from"])
        if term.get("start_date"):
            start = max(start, date.fromisoformat(term["start_date"]))
        cohort_classes = [cid for cid, c in classes.items() if c["cohort_id"] == cohort_id]
        slots_by_version: dict[str, list[dict]] = {}
        async for slot in db[org.SLOTS].find(
            {
                "version_id": {"$in": [v["version_id"] for v in versions]},
                "class_id": {"$in": cohort_classes},
            },
            {"_id": 0},
        ):
            slots_by_version.setdefault(slot["version_id"], []).append(slot)
        off_days, off_classes = set(), set()
        async for e in db[org.CALENDAR].find({"cohort_id": cohort_id}, {"_id": 0}):
            if e.get("class_id"):
                off_classes.add((e["date"], e["class_id"]))
            else:
                off_days.add(e["date"])
        taken = {(s["slot_id"], s["date"]) for s in await _held_sessions(db, cohort_classes, until)}
        day = start
        while day <= until:
            iso = day.isoformat()
            in_force = [v for v in versions if v["effective_from"] <= iso]
            if in_force and iso not in off_days:
                for slot in slots_by_version.get(in_force[-1]["version_id"], []):
                    if (
                        slot["day"] == DAY_CODES[day.weekday()]
                        and (iso, slot["class_id"]) not in off_classes
                        and (slot["slot_id"], iso) not in taken
                    ):
                        out[slot["class_id"]] += int(slot.get("periods") or 1)
            day += timedelta(days=1)
    return out


async def _teacher_names(db: AsyncIOMotorDatabase, classes: dict[str, dict]) -> dict[str, str]:
    ids = sorted({t for c in classes.values() for t in (c.get("teacher_ids") or [])})
    names = {
        p["user_id"]: p.get("name") or ""
        async for p in db["teacher_profiles"].find(
            {"user_id": {"$in": ids}}, {"user_id": 1, "name": 1}
        )
    }
    return {
        cid: ", ".join(n for n in (names.get(t, "") for t in c.get("teacher_ids") or []) if n)
        for cid, c in classes.items()
    }


# ------------------------------------------------------------------ student


async def _student_context(
    db: AsyncIOMotorDatabase, user_id: str
) -> tuple[dict, dict, dict[str, dict]]:
    profile = await db["student_profiles"].find_one({"user_id": user_id}) or {}
    current = await db[enrolment.ENROLMENTS].find_one(
        {"user_id": user_id}, {"_id": 0}, sort=[("since", -1)]
    )
    if current is None:
        raise ReportError("Your setup is not approved yet, so there is no attendance to show.", 404)
    classes = {
        c["class_id"]: c
        async for c in db[org.CLASSES].find({"class_id": {"$in": current["class_ids"]}}, {"_id": 0})
    }
    return profile, current, classes


async def student_subjects(
    db: AsyncIOMotorDatabase, user_id: str, threshold: Optional[float] = None
) -> dict:
    profile, current, classes = await _student_context(db, user_id)
    identity = profile.get("identity") or profile.get("student_id")
    until = today()
    sessions = await _held_sessions(db, sorted(classes), until)
    records = {
        r["session_id"]: r
        async for r in db["attendance_records"].find(
            {"session_id": {"$in": [s["session_id"] for s in sessions]}, "identity": identity},
            RECORD_FIELDS,
        )
    }
    not_entered = await _not_entered(db, classes, until)
    teachers = await _teacher_names(db, classes)
    subjects = {s["key"]: s async for s in db[org.SUBJECTS].find({}, {"_id": 0})}
    if threshold is None:
        threshold = float((await org.get_settings(db))["shortage_threshold_percent"])

    rows: dict[str, dict] = {}
    for cid, cls in classes.items():
        subject = subjects.get(cls["subject_key"], {})
        row = rows.setdefault(
            cls["subject_key"],
            {
                "subject_key": cls["subject_key"],
                "code": subject.get("code", ""),
                "name": subject.get("name", cls["subject_key"]),
                "teacher": teachers.get(cid, ""),
                "present": 0,
                "absent": 0,
                "not_entered": 0,
                "held": 0,
            },
        )
        row["not_entered"] += not_entered.get(cid, 0)
        if not row["teacher"]:
            row["teacher"] = teachers.get(cid, "")
    for session in sessions:
        row = rows[classes[session["class_id"]]["subject_key"]]
        lectures = (records.get(session["session_id"]) or {}).get("lectures")
        if lectures is None:
            continue  # not on that session's roster (joined later)
        row["present"] += lectures.count("P")
        row["absent"] += lectures.count("A")
        row["held"] += len(lectures)
    for row in rows.values():
        row["percentage"] = percentage(row["present"], row["held"])
        row["shortage"] = row["percentage"] is not None and row["percentage"] < threshold
    total_present = sum(r["present"] for r in rows.values())
    total_held = sum(r["held"] for r in rows.values())
    untracked = [
        {"code": s.get("code", ""), "name": s.get("name", s["key"])}
        async for s in db[org.SUBJECTS].find({"tracked": False}, {"_id": 0})
    ]
    overall_pct = percentage(total_present, total_held)
    return {
        "subjects": sorted(rows.values(), key=lambda r: r["name"]),
        "overall": {
            "present": total_present,
            "absent": sum(r["absent"] for r in rows.values()),
            "not_entered": sum(r["not_entered"] for r in rows.values()),
            "held": total_held,
            "percentage": overall_pct,
            "shortage": overall_pct is not None and overall_pct < threshold,
        },
        "not_counted": untracked,
        "threshold": threshold,
    }


async def student_lectures(db: AsyncIOMotorDatabase, user_id: str, subject_key: str) -> dict:
    profile, current, classes = await _student_context(db, user_id)
    identity = profile.get("identity") or profile.get("student_id")
    mine = {cid: c for cid, c in classes.items() if c["subject_key"] == subject_key}
    if not mine:
        raise ReportError("That subject is not in your setup.", 404)
    sessions = await _held_sessions(db, sorted(mine), today())
    records = {
        r["session_id"]: r
        async for r in db["attendance_records"].find(
            {"session_id": {"$in": [s["session_id"] for s in sessions]}, "identity": identity},
            RECORD_FIELDS,
        )
    }
    items = []
    for session in sessions:
        record = records.get(session["session_id"])
        if record is None:
            continue
        marks = record.get("rounds") or {}
        for number, mark in enumerate(record.get("lectures") or [], start=1):
            items.append(
                {
                    "date": session["date"],
                    "time": _local_time(session.get("start_time")),
                    "lecture": number,
                    "status": mark,
                    "class": session.get("class_code"),
                    "entry": (marks.get("ENTRY") or {}).get("status"),
                    "exit": (marks.get("EXIT") or {}).get("status"),
                }
            )
    return {"subject_key": subject_key, "lectures": list(reversed(items))}


# ------------------------------------------------------------------ teacher


async def class_for(db: AsyncIOMotorDatabase, class_id: str, user: dict) -> dict:
    cls = await db[org.CLASSES].find_one({"class_id": class_id}, {"_id": 0})
    if cls is None:
        raise ReportError("Class not found.", 404)
    if user.get("role") != "ADMIN" and user["user_id"] not in (cls.get("teacher_ids") or []):
        raise ReportError("This class is not assigned to you.", 403)
    return cls


async def _class_students(db: AsyncIOMotorDatabase, class_id: str) -> list[dict]:
    enrolled = {
        e["user_id"]: e
        async for e in db[enrolment.ENROLMENTS].find({"class_ids": class_id}, {"_id": 0})
    }
    approved = {
        u["user_id"]: u
        async for u in db["users"].find(
            {"user_id": {"$in": sorted(enrolled)}, "status": "APPROVED"}, {"user_id": 1, "email": 1}
        )
    }
    students = []
    async for p in (
        db["student_profiles"]
        .find({"user_id": {"$in": sorted(approved)}}, {"_id": 0})
        .sort("roll_number", 1)
    ):
        students.append(
            {**p, "email": approved[p["user_id"]].get("email"), "enrolment": enrolled[p["user_id"]]}
        )
    return students


def _csv(rows: list[list[Any]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerows(rows)
    return out.getvalue()


async def teacher_classes(db: AsyncIOMotorDatabase, user: dict) -> list[dict]:
    query = {} if user.get("role") == "ADMIN" else {"teacher_ids": user["user_id"]}
    subjects = {s["key"]: s async for s in db[org.SUBJECTS].find({}, {"_id": 0})}
    out = []
    async for cls in db[org.CLASSES].find(query, {"_id": 0}).sort("class_id", 1):
        subject = subjects.get(cls["subject_key"], {})
        out.append(
            {
                "class_id": cls["class_id"],
                "label": cls.get("label"),
                "subject": subject.get("name", cls["subject_key"]),
                "code": subject.get("code", ""),
                "audience": cls["audience"],
            }
        )
    return out


async def class_list_csv(db: AsyncIOMotorDatabase, cls: dict) -> str:
    rows: list[list[Any]] = [["Roll No", "Name", "Email", "Section", "DE-II", "DE-III", "DLDA"]]
    for s in await _class_students(db, cls["class_id"]):
        choices = s["enrolment"].get("choices") or {}

        def pick(code: str) -> str:
            c = choices.get(code)
            if not c:
                return ""
            return (
                c["group"] if c["option"] in (c["group"], code) else f"{c['option']} {c['group']}"
            )

        rows.append(
            [
                s.get("roll_number", ""),
                s.get("name", ""),
                s.get("email", ""),
                s["enrolment"].get("section", ""),
                pick("DE-II"),
                pick("DE-III"),
                pick("DLDA"),
            ]
        )
    return _csv(rows)


async def register_csv(
    db: AsyncIOMotorDatabase, cls: dict, since: Optional[date], until: Optional[date]
) -> str:
    until = until or today()
    sessions = await _held_sessions(db, [cls["class_id"]], until, since)
    students = await _class_students(db, cls["class_id"])
    identities = [s.get("identity") or s.get("student_id") for s in students]
    records: dict[tuple[str, str], dict] = {}
    async for r in db["attendance_records"].find(
        {
            "session_id": {"$in": [s["session_id"] for s in sessions]},
            "identity": {"$in": identities},
        },
        RECORD_FIELDS,
    ):
        records[(r["session_id"], r["identity"])] = r
    columns: list[tuple[str, int]] = []  # (session_id, lecture index)
    header = ["Roll No", "Name"]
    for session in sessions:
        label = date.fromisoformat(session["date"]).strftime("%d %b")
        periods = int(session.get("periods") or 1)
        for i in range(periods):
            columns.append((session["session_id"], i))
            header.append(
                f"{label} {_local_time(session.get('start_time'))} L{i + 1}".replace("  ", " ")
            )
    header += ["Present", "Held", "%"]
    rows: list[list[Any]] = [header]
    for student, ident in zip(students, identities):
        cells, present, held = [], 0, 0
        for session_id, i in columns:
            lectures = (records.get((session_id, ident)) or {}).get("lectures")
            if lectures is None or i >= len(lectures):
                cells.append("-")
                continue
            cells.append(lectures[i])
            held += 1
            present += lectures[i] == "P"
        pct = percentage(present, held)
        rows.append(
            [
                student.get("roll_number", ""),
                student.get("name", ""),
                *cells,
                present,
                held,
                "" if pct is None else pct,
            ]
        )
    return _csv(rows)


async def class_sessions(db: AsyncIOMotorDatabase, cls: dict) -> list[dict]:
    out = []
    async for s in (
        db["sessions"]
        .find({"class_id": cls["class_id"]}, {"_id": 0})
        .sort([("date", -1), ("start_time", -1)])
    ):
        out.append(
            {
                "session_id": s["session_id"],
                "date": s.get("date"),
                "time": _local_time(s.get("start_time")),
                "status": s.get("status"),
                "rounds_held": held_rounds(s),
                "periods": s.get("periods"),
            }
        )
    return out
