"""Organisation model for the pilot: terms, branches, cohorts, sections,
year-wide group sets, the subject catalog, classes and timetable versions.

A SUBJECT is a catalog entry (official ERP code, name, type). A CLASS is a
subject taught to one audience in one term: one section, or one group of a
year-wide group set. Attendance, teachers and timetable slots attach to
classes. Year-wide groups belong to the cohort (the year), not to a section,
because they mix students of every section.

Timetables are imported as versions. A version is a draft until an
administrator activates it from a date; the timetable in force on a day is the
active version with the latest effective date not after that day, so a change
in the middle of the semester never alters lectures before it.

This module runs alongside the older flat class/subject model; nothing that
exists today reads these collections yet.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import hashlib
import io
from types import ModuleType
from typing import Any
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.seed import pilot_catalog

TERMS = "org_terms"
BRANCHES = "org_branches"
COHORTS = "org_cohorts"
SECTIONS = "org_sections"
GROUP_SETS = "org_group_sets"
SUBJECTS = "catalog_subjects"
CLASSES = "org_classes"
VERSIONS = "timetable_versions"
SLOTS = "timetable_slots"

DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]
TIMETABLE_COLUMNS = [
    "scope",
    "group",
    "day",
    "start",
    "end",
    "periods",
    "subject_short",
    "subject_name",
    "room",
    "note",
]
MAX_TIMETABLE_BYTES = 1_000_000
# A period is about 50 minutes; anything well outside this is worth a look.
MINUTES_PER_PERIOD = (40, 65)


class OrganisationError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------------------
# Seeding the structure and catalog
# ------------------------------------------------------------------------------


def _subject_doc(entry: dict) -> dict:
    return {
        "key": entry["key"],
        "code": entry["code"],
        "name": entry["name"],
        "type": entry["type"],
        "tracked": entry.get("tracked", True),
        "code_status": entry.get("code_status", "CONFIRMED"),
        "code_note": entry.get("code_note", ""),
        "short_names": sorted({entry["key"], *entry.get("short_names", [])}),
    }


async def seed_structure(db: AsyncIOMotorDatabase, catalog: ModuleType = pilot_catalog) -> dict:
    """Create or update the term, branch, cohort, sections, group sets and subjects.

    Safe to run again: everything is keyed, so a second run changes nothing
    that has not changed in the catalog. It never assigns teachers and never
    touches classes, timetables or students.
    """
    now = _now()
    term = dict(catalog.TERM)
    existing_term = await db[TERMS].find_one({"term_id": term["term_id"]}) or {}
    # Dates the administrator has filled in are kept.
    for name in ("start_date", "end_date"):
        if existing_term.get(name):
            term[name] = existing_term[name]
    await db[TERMS].update_one(
        {"term_id": term["term_id"]},
        {
            "$set": {**term, "status": existing_term.get("status", "ACTIVE"), "updated_at": now},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    await db[BRANCHES].update_one(
        {"code": catalog.BRANCH["code"]},
        {"$set": {**catalog.BRANCH, "updated_at": now}, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    cohort_id = catalog.COHORT["cohort_id"]
    await db[COHORTS].update_one(
        {"cohort_id": cohort_id},
        {"$set": {**catalog.COHORT, "updated_at": now}, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    for code in catalog.SECTIONS:
        await db[SECTIONS].update_one(
            {"cohort_id": cohort_id, "code": code},
            {
                "$set": {"cohort_id": cohort_id, "code": code, "updated_at": now},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
    subject_keys = set()
    for entry in catalog.SUBJECTS:
        doc = _subject_doc(entry)
        subject_keys.add(doc["key"])
        await db[SUBJECTS].update_one(
            {"key": doc["key"]},
            {"$set": {**doc, "updated_at": now}, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
    for group_set in catalog.GROUP_SETS:
        for option in group_set["options"]:
            unknown = set(option["subject_keys"]) - subject_keys
            if unknown:
                raise OrganisationError(
                    f"group set {group_set['set_code']} names unknown subjects {sorted(unknown)}"
                )
        await db[GROUP_SETS].update_one(
            {"cohort_id": cohort_id, "set_code": group_set["set_code"]},
            {
                "$set": {**group_set, "cohort_id": cohort_id, "updated_at": now},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
    return {
        "term_id": term["term_id"],
        "cohort_id": cohort_id,
        "sections": len(catalog.SECTIONS),
        "subjects": len(catalog.SUBJECTS),
        "group_sets": len(catalog.GROUP_SETS),
    }


# ------------------------------------------------------------------------------
# Reading the timetable sheet
# ------------------------------------------------------------------------------


@dataclass
class ImportPlan:
    """What an import would do, worked out without writing anything."""

    cohort_id: str
    term_id: str
    rows: int = 0
    errors: list[dict] = field(default_factory=list)
    slots: list[dict] = field(default_factory=list)
    classes: dict[str, dict] = field(default_factory=dict)

    @property
    def flagged(self) -> list[dict]:
        return [slot for slot in self.slots if slot["flags"]]

    def report(self) -> dict:
        flag_counts: dict[str, int] = {}
        for slot in self.slots:
            for flag in slot["flags"]:
                flag_counts[flag["kind"]] = flag_counts.get(flag["kind"], 0) + 1
        section_classes = [c for c in self.classes.values() if c["audience"]["kind"] == "SECTION"]
        return {
            "cohort_id": self.cohort_id,
            "rows": self.rows,
            "slots": len(self.slots),
            "classes": len(self.classes),
            "section_classes": len(section_classes),
            "group_classes": len(self.classes) - len(section_classes),
            "errors": self.errors,
            "flag_counts": flag_counts,
            "flagged_rows": [
                {"row": slot["row"], "summary": slot["summary"], "flags": slot["flags"]}
                for slot in self.flagged
            ],
        }


def _minutes(value: str) -> int | None:
    try:
        hours, minutes = value.strip().split(":")
        result = int(hours) * 60 + int(minutes)
    except ValueError:
        return None
    return result if 0 <= result < 24 * 60 else None


def class_id_for(term_id: str, cohort_id: str, audience: dict, subject_key: str) -> str:
    """A readable, stable id: the same class always gets the same id."""
    if audience["kind"] == "SECTION":
        target = audience["section"]
    else:
        target = f"{audience['set_code']}/{audience['option_code']}/{audience['group_code']}"
    return f"{term_id}:{cohort_id}:{target}:{subject_key}"


async def plan_timetable_import(db: AsyncIOMotorDatabase, cohort_id: str, text: str) -> ImportPlan:
    """Check a timetable sheet against the catalog and work out its classes and slots."""
    cohort = await db[COHORTS].find_one({"cohort_id": cohort_id})
    if cohort is None:
        raise OrganisationError(f"unknown cohort {cohort_id}", status_code=404)
    plan = ImportPlan(cohort_id=cohort_id, term_id=cohort["term_id"])

    sections = {
        doc["code"] async for doc in db[SECTIONS].find({"cohort_id": cohort_id}, {"code": 1})
    }
    subjects = [doc async for doc in db[SUBJECTS].find({})]
    by_short: dict[str, dict] = {}
    for subject in subjects:
        for short in subject.get("short_names") or [subject["key"]]:
            by_short[short.upper()] = subject
    # Which option and set each grouped subject belongs to.
    grouped: dict[str, tuple[dict, dict]] = {}
    async for group_set in db[GROUP_SETS].find({"cohort_id": cohort_id}):
        for option in group_set["options"]:
            for key in option["subject_keys"]:
                grouped[key] = (group_set, option)

    reader = csv.DictReader(io.StringIO(text))
    header = [name.strip() for name in (reader.fieldnames or [])]
    missing = [name for name in TIMETABLE_COLUMNS if name not in header]
    if missing:
        raise OrganisationError(f"the sheet is missing the column(s): {', '.join(missing)}")

    for number, raw in enumerate(reader, start=2):  # row 1 is the header
        row = {key.strip(): (value or "").strip() for key, value in raw.items() if key}
        if not any(row.values()):
            continue
        plan.rows += 1

        def error(message: str, row_number: int = number) -> None:
            plan.errors.append({"row": row_number, "message": message})

        scope = row["scope"].upper()
        day = row["day"].upper()
        start, end = _minutes(row["start"]), _minutes(row["end"])
        subject = by_short.get(row["subject_short"].upper())
        if day not in DAYS:
            error(f"unknown day {row['day']!r}")
            continue
        if start is None or end is None or end <= start:
            error(f"times {row['start']!r} to {row['end']!r} are not a valid range")
            continue
        try:
            periods = int(row["periods"])
        except ValueError:
            periods = 0
        if periods not in (1, 2, 3):
            error(f"periods must be 1, 2 or 3, not {row['periods']!r}")
            continue
        if subject is None:
            error(f"subject {row['subject_short']!r} is not in the catalog")
            continue
        if not subject.get("tracked", True):
            error(f"{subject['name']} is not tracked by this system and cannot have slots")
            continue

        if scope == "ALL":
            if subject["key"] not in grouped:
                error(
                    f"{subject['name']} is not a year-wide group subject, but the row is for all sections"
                )
                continue
            group_set, option = grouped[subject["key"]]
            group_code = row["group"].upper()
            if group_code not in option["groups"]:
                error(
                    f"group {row['group']!r} is not a group of {option['name']} "
                    f"(valid: {', '.join(option['groups'])})"
                )
                continue
            audience = {
                "kind": "GROUP",
                "set_code": group_set["set_code"],
                "set_kind": group_set["kind"],
                "option_code": option["option_code"],
                "group_code": group_code,
            }
            audience_label = f"{group_set['set_code']} {option['name']} {group_code}"
        else:
            if scope not in sections:
                error(f"section {row['scope']!r} does not exist in this cohort")
                continue
            if row["group"]:
                error("a section row must leave the group column empty")
                continue
            if subject["key"] in grouped:
                error(f"{subject['name']} is taught in year-wide groups, not to one section")
                continue
            audience = {"kind": "SECTION", "section": scope}
            audience_label = f"Section {scope}"

        class_id = class_id_for(plan.term_id, cohort_id, audience, subject["key"])
        plan.classes.setdefault(
            class_id,
            {
                "class_id": class_id,
                "term_id": plan.term_id,
                "cohort_id": cohort_id,
                "subject_key": subject["key"],
                "audience": audience,
                "label": f"{subject['name']} - {audience_label}",
            },
        )

        flags = []
        note = row["note"]
        if "confirm" in note.lower():
            flags.append({"kind": "CONFIRM", "text": note})
        if subject.get("code_status") == "INCOMPLETE":
            flags.append({"kind": "INCOMPLETE_CODE", "text": subject.get("code_note", "")})
        if subject.get("code_status") == "MISMATCH":
            flags.append({"kind": "CODE_MISMATCH", "text": subject.get("code_note", "")})
        if not row["room"]:
            flags.append({"kind": "NO_ROOM", "text": "No room given in the sheet."})
        per_period = (end - start) / periods
        if not MINUTES_PER_PERIOD[0] <= per_period <= MINUTES_PER_PERIOD[1]:
            flags.append(
                {
                    "kind": "PERIODS_CHECK",
                    "text": f"{end - start} minutes for {periods} period(s): check the number of periods.",
                }
            )

        plan.slots.append(
            {
                "row": number,
                "class_id": class_id,
                "subject_key": subject["key"],
                "audience": audience,
                "day": day,
                "start": row["start"],
                "end": row["end"],
                "start_minute": start,
                "end_minute": end,
                "periods": periods,
                "room": row["room"],
                "note": note,
                "flags": flags,
                "summary": f"{day} {row['start']}-{row['end']} {subject['name']} ({audience_label})",
            }
        )

    _check_clashes(plan)
    return plan


def _check_clashes(plan: ImportPlan) -> None:
    """Two slots for the same audience at overlapping times are an error; a
    section slot at the same time as a year-wide group slot is flagged,
    because every student of the section is also in one of those groups."""
    by_day: dict[str, list[dict]] = {}
    for slot in plan.slots:
        by_day.setdefault(slot["day"], []).append(slot)
    for slots in by_day.values():
        for i, first in enumerate(slots):
            for second in slots[i + 1 :]:
                if (
                    first["start_minute"] >= second["end_minute"]
                    or second["start_minute"] >= first["end_minute"]
                ):
                    continue
                a, b = first["audience"], second["audience"]
                if a == b:
                    plan.errors.append(
                        {
                            "row": second["row"],
                            "message": f"overlaps row {first['row']} for the same class audience",
                        }
                    )
                    continue
                if a["kind"] == "SECTION" and b["kind"] == "SECTION":
                    # Two different sections at the same time: normal.
                    continue
                if a["kind"] == "GROUP" and b["kind"] == "GROUP" and a["set_code"] == b["set_code"]:
                    # Different groups of the same set run in parallel: normal.
                    continue
                for slot, other in ((first, second), (second, first)):
                    slot["flags"].append(
                        {
                            "kind": "CLASH",
                            "text": f"Same time as row {other['row']}: {other['summary']}.",
                        }
                    )


# ------------------------------------------------------------------------------
# Writing an import, activating a version
# ------------------------------------------------------------------------------


async def import_timetable(
    db: AsyncIOMotorDatabase,
    cohort_id: str,
    text: str,
    *,
    source_name: str,
    actor_user_id: str,
) -> dict:
    """Store a checked sheet as a DRAFT version. Refused while the sheet has errors."""
    plan = await plan_timetable_import(db, cohort_id, text)
    if plan.errors:
        raise OrganisationError(
            f"the sheet has {len(plan.errors)} error(s); nothing was imported", status_code=422
        )
    now = _now()
    version_id = f"ttv_{uuid4().hex}"
    for doc in plan.classes.values():
        # Classes belong to the term, not to a timetable version: a later
        # version reuses them, and their teachers and attendance stay attached.
        await db[CLASSES].update_one(
            {"class_id": doc["class_id"]},
            {
                "$set": {**doc, "updated_at": now},
                "$setOnInsert": {
                    "teacher_ids": [],
                    "status": "ACTIVE",
                    "created_at": now,
                    "created_by_version": version_id,
                },
            },
            upsert=True,
        )
    slots = [
        {
            **{k: v for k, v in slot.items() if k != "summary"},
            "slot_id": f"tts_{uuid4().hex}",
            "version_id": version_id,
            "cohort_id": cohort_id,
            "label": slot["summary"],
        }
        for slot in plan.slots
    ]
    if slots:
        await db[SLOTS].insert_many(slots)
    version = {
        "version_id": version_id,
        "cohort_id": cohort_id,
        "term_id": plan.term_id,
        "status": "DRAFT",
        "effective_from": None,
        "source_name": source_name,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "rows": plan.rows,
        "slots": len(slots),
        "flagged_slots": len(plan.flagged),
        "created_by": actor_user_id,
        "created_at": now,
    }
    await db[VERSIONS].insert_one(dict(version))
    return {**version, "report": plan.report()}


async def activate_version(
    db: AsyncIOMotorDatabase, version_id: str, effective_from: date, *, actor_user_id: str
) -> dict:
    """Put a draft version in force from a date. Earlier dates keep the earlier version."""
    version = await db[VERSIONS].find_one({"version_id": version_id})
    if version is None:
        raise OrganisationError("timetable version not found", status_code=404)
    if version["status"] != "DRAFT":
        raise OrganisationError("only a draft version can be activated", status_code=409)
    latest = await db[VERSIONS].find_one(
        {"cohort_id": version["cohort_id"], "status": "ACTIVE"}, sort=[("effective_from", -1)]
    )
    day = effective_from.isoformat()
    if latest and latest["effective_from"] >= day:
        raise OrganisationError(
            f"the version in force since {latest['effective_from']} would be overridden for past dates; "
            "choose a later effective date",
            status_code=409,
        )
    await db[VERSIONS].update_one(
        {"version_id": version_id},
        {
            "$set": {
                "status": "ACTIVE",
                "effective_from": day,
                "activated_by": actor_user_id,
                "activated_at": _now(),
            }
        },
    )
    return await db[VERSIONS].find_one({"version_id": version_id}, {"_id": 0})


async def version_in_force(db: AsyncIOMotorDatabase, cohort_id: str, on: date) -> dict | None:
    """The active version with the latest effective date not after ``on``."""
    return await db[VERSIONS].find_one(
        {"cohort_id": cohort_id, "status": "ACTIVE", "effective_from": {"$lte": on.isoformat()}},
        {"_id": 0},
        sort=[("effective_from", -1)],
    )


# ------------------------------------------------------------------------------
# Reading back
# ------------------------------------------------------------------------------


async def structure(db: AsyncIOMotorDatabase) -> dict[str, Any]:
    """Branch -> cohort (year, semester, term) -> sections, plus the cohort's group sets by kind."""
    branches = [doc async for doc in db[BRANCHES].find({}, {"_id": 0})]
    cohorts = [doc async for doc in db[COHORTS].find({}, {"_id": 0})]
    for cohort in cohorts:
        cohort["sections"] = sorted(
            [doc["code"] async for doc in db[SECTIONS].find({"cohort_id": cohort["cohort_id"]})]
        )
        sets = [
            doc async for doc in db[GROUP_SETS].find({"cohort_id": cohort["cohort_id"]}, {"_id": 0})
        ]
        cohort["elective_sets"] = [s for s in sets if s["kind"] == "ELECTIVE"]
        cohort["workshop_sets"] = [s for s in sets if s["kind"] == "WORKSHOP"]
    for branch in branches:
        branch["cohorts"] = [c for c in cohorts if c["branch"] == branch["code"]]
    terms = [doc async for doc in db[TERMS].find({}, {"_id": 0})]
    return {"terms": terms, "branches": branches}


def valid_group_choice(group_set: dict, option_code: str, group_code: str) -> bool:
    """Only the option + group pairs the set lists are valid."""
    return any(
        option["option_code"] == option_code and group_code in option["groups"]
        for option in group_set["options"]
    )


# ------------------------------------------------------------------------------
# Administrator edits: term dates, subject codes, flags, calendar, settings
# ------------------------------------------------------------------------------

SETTINGS = "org_settings"
CALENDAR = "calendar_exceptions"
SETTINGS_ID = "pilot"
DEFAULT_SETTINGS = {
    "college_email_domain": "niet.co.in",
    # Teachers may correct a session until they finalize it or this many hours
    # after it, whichever is first; then only an administrator can unlock it.
    "edit_window_hours": 24,
    "shortage_threshold_percent": 75,
}
CODE_STATUSES = ("CONFIRMED", "INCOMPLETE", "MISMATCH")
SUBJECT_FLAG_KINDS = {"INCOMPLETE_CODE", "CODE_MISMATCH"}


async def update_term_dates(
    db: AsyncIOMotorDatabase, term_id: str, start_date: date | None, end_date: date | None
) -> dict:
    if start_date and end_date and end_date < start_date:
        raise OrganisationError("the term cannot end before it starts")
    term = await db[TERMS].find_one({"term_id": term_id})
    if term is None:
        raise OrganisationError("term not found", status_code=404)
    await db[TERMS].update_one(
        {"term_id": term_id},
        {
            "$set": {
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "updated_at": _now(),
            }
        },
    )
    return await db[TERMS].find_one({"term_id": term_id}, {"_id": 0})


async def update_subject(db: AsyncIOMotorDatabase, key: str, changes: dict) -> dict:
    """Correct a subject's ERP code, name or code status. The key never changes."""
    subject = await db[SUBJECTS].find_one({"key": key})
    if subject is None:
        raise OrganisationError("subject not found", status_code=404)
    update: dict = {}
    for name in ("code", "name", "code_note"):
        if changes.get(name) is not None:
            value = str(changes[name]).strip()
            if name != "code_note" and not value:
                raise OrganisationError(f"{name} cannot be empty")
            update[name] = value
    if changes.get("code_status") is not None:
        if changes["code_status"] not in CODE_STATUSES:
            raise OrganisationError(f"code status must be one of {', '.join(CODE_STATUSES)}")
        update["code_status"] = changes["code_status"]
    if "code" in update and update["code"] != subject["code"]:
        clash = await db[SUBJECTS].find_one({"code": update["code"], "key": {"$ne": key}})
        if clash:
            raise OrganisationError(
                f"code {update['code']} is already used by {clash['name']}", status_code=409
            )
    if not update:
        return {k: v for k, v in subject.items() if k != "_id"}
    update["updated_at"] = _now()
    await db[SUBJECTS].update_one({"key": key}, {"$set": update})
    return await db[SUBJECTS].find_one({"key": key}, {"_id": 0})


async def resolve_flag(
    db: AsyncIOMotorDatabase, slot_id: str, kind: str, note: str, *, actor_user_id: str
) -> dict:
    """Mark one flag of a slot as checked, with a note. The slot itself does not change:
    a correction to the timetable is made by importing a corrected sheet."""
    slot = await db[SLOTS].find_one({"slot_id": slot_id})
    if slot is None:
        raise OrganisationError("timetable slot not found", status_code=404)
    if not note.strip():
        raise OrganisationError("say what was checked")
    flags = slot.get("flags", [])
    if not any(flag["kind"] == kind for flag in flags):
        raise OrganisationError(f"this slot has no {kind} flag", status_code=404)
    for flag in flags:
        if flag["kind"] == kind:
            flag.update(
                {
                    "resolved": True,
                    "resolved_note": note.strip(),
                    "resolved_by": actor_user_id,
                    "resolved_at": _now(),
                }
            )
    await db[SLOTS].update_one({"slot_id": slot_id}, {"$set": {"flags": flags}})
    return await db[SLOTS].find_one({"slot_id": slot_id}, {"_id": 0})


async def add_calendar_exception(
    db: AsyncIOMotorDatabase,
    *,
    cohort_id: str,
    on: date,
    reason: str,
    class_id: str | None,
    actor_user_id: str,
) -> dict:
    """A day without teaching: for the whole cohort (a holiday) or one class (cancelled)."""
    if await db[COHORTS].find_one({"cohort_id": cohort_id}) is None:
        raise OrganisationError("cohort not found", status_code=404)
    if (
        class_id
        and await db[CLASSES].find_one({"class_id": class_id, "cohort_id": cohort_id}) is None
    ):
        raise OrganisationError("class not found in this cohort", status_code=404)
    if not reason.strip():
        raise OrganisationError("give a reason")
    duplicate = await db[CALENDAR].find_one(
        {"cohort_id": cohort_id, "date": on.isoformat(), "class_id": class_id}
    )
    if duplicate:
        raise OrganisationError("that day is already recorded", status_code=409)
    doc = {
        "exception_id": f"cal_{uuid4().hex}",
        "cohort_id": cohort_id,
        "date": on.isoformat(),
        "class_id": class_id,
        "reason": reason.strip(),
        "created_by": actor_user_id,
        "created_at": _now(),
    }
    await db[CALENDAR].insert_one(dict(doc))
    return doc


async def get_settings(db: AsyncIOMotorDatabase) -> dict:
    stored = await db[SETTINGS].find_one({"settings_id": SETTINGS_ID}, {"_id": 0}) or {}
    return {**DEFAULT_SETTINGS, **{k: v for k, v in stored.items() if k in DEFAULT_SETTINGS}}


async def update_settings(db: AsyncIOMotorDatabase, changes: dict) -> dict:
    update: dict = {}
    if changes.get("college_email_domain") is not None:
        domain = str(changes["college_email_domain"]).strip().lower().lstrip("@")
        if not domain or "." not in domain or " " in domain or "@" in domain:
            raise OrganisationError("give a domain such as niet.co.in")
        update["college_email_domain"] = domain
    if changes.get("edit_window_hours") is not None:
        hours = int(changes["edit_window_hours"])
        if not 1 <= hours <= 24 * 14:
            raise OrganisationError("the edit window must be between 1 hour and 14 days")
        update["edit_window_hours"] = hours
    if changes.get("shortage_threshold_percent") is not None:
        threshold = int(changes["shortage_threshold_percent"])
        if not 1 <= threshold <= 100:
            raise OrganisationError("the shortage threshold must be between 1 and 100")
        update["shortage_threshold_percent"] = threshold
    if update:
        await db[SETTINGS].update_one(
            {"settings_id": SETTINGS_ID},
            {
                "$set": {**update, "updated_at": _now()},
                "$setOnInsert": {"settings_id": SETTINGS_ID},
            },
            upsert=True,
        )
    return await get_settings(db)


def with_current_code_flags(slots: list[dict], subjects: dict[str, dict]) -> list[dict]:
    """Code flags follow the catalog: once an administrator confirms a subject's
    code, its slots stop showing the flag; other flags stay as imported."""
    for slot in slots:
        subject = subjects.get(slot["subject_key"], {})
        kept = [f for f in slot.get("flags", []) if f["kind"] not in SUBJECT_FLAG_KINDS]
        if subject.get("code_status") == "INCOMPLETE":
            kept.append({"kind": "INCOMPLETE_CODE", "text": subject.get("code_note", "")})
        elif subject.get("code_status") == "MISMATCH":
            kept.append({"kind": "CODE_MISMATCH", "text": subject.get("code_note", "")})
        slot["flags"] = kept
        slot["open_flags"] = sum(1 for f in kept if not f.get("resolved"))
    return slots
