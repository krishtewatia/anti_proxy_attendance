"""The college's official section list, matched against students' setups.

An administrator uploads one list per cohort (CSV: roll number, name, email,
section, DE-II, DE-III and DLDA groups). The match report compares it, by roll
number, with what each student registered and asked for, and puts every list
row and every waiting request in exactly one category. Only requests that
agree with the list in every respect (MATCH) can be approved in one action;
everything else is decided one by one.

The list holds names and emails: it is for administrators only, audit
entries hold counts only, and it can be deleted.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import re
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.services import enrolment_service as enrolment
from app.services import organisation_service as org
from app.services.audit_service import record_audit_event
from app.services.registration_rules import ROLL_NUMBER_PATTERN

LISTS = "section_lists"
MAX_LIST_BYTES = 1_000_000
MAX_LIST_ROWS = 2000

COLUMNS = ["roll_no", "name", "email", "section", "de2", "de3", "dlda"]
TEMPLATE = ",".join(COLUMNS) + "\n"
# Header names as the college may write them -> our column.
ALIASES = {
    "roll_no": "roll_no",
    "roll no": "roll_no",
    "roll no.": "roll_no",
    "roll number": "roll_no",
    "rollno": "roll_no",
    "name": "name",
    "student name": "name",
    "email": "email",
    "email id": "email",
    "college email": "email",
    "section": "section",
    "de2": "de2",
    "de-ii": "de2",
    "de ii": "de2",
    "de3": "de3",
    "de-iii": "de3",
    "de iii": "de3",
    "dlda": "dlda",
    "dlda group": "dlda",
}
# Our column -> the group set it names.
SET_COLUMNS = {"de2": "DE-II", "de3": "DE-III", "dlda": "DLDA"}

MATCH = "MATCH"
DIFFERENT = "DIFFERENT"
EMAIL_DIFFERS = "EMAIL_DIFFERS"
NOT_REGISTERED = "NOT_REGISTERED"
NO_REQUEST = "NO_REQUEST"
NOT_ON_LIST = "NOT_ON_LIST"
APPROVED_AGREES = "APPROVED_AGREES"
APPROVED_DIFFERS = "APPROVED_DIFFERS"
CATEGORIES = [
    MATCH,
    DIFFERENT,
    EMAIL_DIFFERS,
    NOT_ON_LIST,
    NO_REQUEST,
    NOT_REGISTERED,
    APPROVED_AGREES,
    APPROVED_DIFFERS,
]

_ROLL_RE = re.compile(ROLL_NUMBER_PATTERN)
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class SectionListError(Exception):
    def __init__(self, message: str, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _norm_name(value: Optional[str]) -> str:
    return " ".join((value or "").lower().split())


def _parse_group(cell: str, group_set: dict) -> Optional[dict]:
    """'PA G2', 'PA-G2', 'PA/G2', or a group code that belongs to one option ('AJ', 'DL3')."""
    parts = [p for p in re.split(r"[\s/\-]+", (cell or "").strip().upper()) if p]
    if len(parts) == 2 and org.valid_group_choice(group_set, parts[0], parts[1]):
        return {"option": parts[0], "group": parts[1]}
    if len(parts) == 1:
        owners = [o for o in group_set["options"] if parts[0] in o["groups"]]
        if len(owners) == 1:
            return {"option": owners[0]["option_code"], "group": parts[0]}
    return None


async def parse_list(db: AsyncIOMotorDatabase, cohort_id: str, text: str) -> dict:
    """Read and check a section list; returns rows and errors (nothing is stored)."""
    cohort = await db[org.COHORTS].find_one({"cohort_id": cohort_id})
    if cohort is None:
        raise SectionListError(f"unknown cohort {cohort_id}", 404)
    if len(text.encode("utf-8")) > MAX_LIST_BYTES:
        raise SectionListError("The list is larger than 1 MB.")
    sections = {d["code"] async for d in db[org.SECTIONS].find({"cohort_id": cohort_id})}
    sets = {s["set_code"]: s async for s in db[org.GROUP_SETS].find({"cohort_id": cohort_id})}
    domain = (await org.get_settings(db))["college_email_domain"]

    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    header_row = next(reader, [])
    columns = [ALIASES.get(" ".join(h.strip().lower().split()), "") for h in header_row]
    needed = [c for c in COLUMNS if SET_COLUMNS.get(c, "") in sets or c not in SET_COLUMNS]
    missing = [c for c in needed if c not in columns]
    if missing:
        raise SectionListError(f"The list is missing the column(s): {', '.join(missing)}")

    rows: list[dict] = []
    errors: list[dict] = []
    seen: dict[str, int] = {}
    for number, raw in enumerate(reader, start=2):
        cells = {
            columns[i]: (v or "").strip()
            for i, v in enumerate(raw)
            if i < len(columns) and columns[i]
        }
        if not any(cells.values()):
            continue
        if len(rows) + len(errors) >= MAX_LIST_ROWS:
            raise SectionListError(f"The list has more than {MAX_LIST_ROWS} rows.")
        problems = []
        roll = cells.get("roll_no", "")
        if not _ROLL_RE.match(roll):
            problems.append(f"roll number {roll!r} is not 8 to 20 digits")
        elif roll in seen:
            problems.append(f"roll number {roll} is also on row {seen[roll]}")
        email = cells.get("email", "").lower()
        if not _EMAIL_RE.match(email) or not email.endswith(f"@{domain}"):
            problems.append(f"email {cells.get('email', '')!r} is not a @{domain} address")
        section = cells.get("section", "").upper()
        if section not in sections:
            problems.append(
                f"section {cells.get('section', '')!r} is not one of {', '.join(sorted(sections))}"
            )
        choices = {}
        for column, set_code in SET_COLUMNS.items():
            if set_code not in sets:
                continue
            choice = _parse_group(cells.get(column, ""), sets[set_code])
            if choice is None:
                problems.append(f"{set_code} {cells.get(column, '')!r} is not a {set_code} group")
            else:
                choices[set_code] = choice
        if problems:
            errors.append({"row": number, "message": "; ".join(problems)})
            continue
        seen[roll] = number
        rows.append(
            {
                "roll_no": roll,
                "name": cells.get("name", ""),
                "email": email,
                "section": section,
                "choices": choices,
            }
        )
    per_section: dict[str, int] = {}
    for row in rows:
        per_section[row["section"]] = per_section.get(row["section"], 0) + 1
    return {
        "cohort_id": cohort_id,
        "rows": rows,
        "errors": errors,
        "row_count": len(rows),
        "per_section": dict(sorted(per_section.items())),
    }


async def upload_list(
    db: AsyncIOMotorDatabase,
    cohort_id: str,
    text: str,
    *,
    source_name: str,
    actor: dict,
    dry_run: bool,
) -> dict:
    parsed = await parse_list(db, cohort_id, text)
    report = {k: v for k, v in parsed.items() if k != "rows"} | {
        "dry_run": dry_run,
        "stored": False,
    }
    if dry_run or parsed["errors"] or not parsed["rows"]:
        return report
    await db[LISTS].replace_one(
        {"cohort_id": cohort_id},
        {
            "cohort_id": cohort_id,
            "rows": parsed["rows"],
            "row_count": parsed["row_count"],
            "per_section": parsed["per_section"],
            "source_name": (source_name or "section_list.csv")[:120],
            "uploaded_by": actor["user_id"],
            "uploaded_at": _now(),
        },
        upsert=True,
    )
    await record_audit_event(
        actor_user_id=actor["user_id"],
        actor_role=actor.get("role", "ADMIN"),
        action="SECTION_LIST_UPLOADED",
        resource_type="ACADEMIC",
        resource_id=cohort_id,
        metadata={"rows": parsed["row_count"], "per_section": parsed["per_section"]},
    )
    return report | {"stored": True}


async def list_summary(db: AsyncIOMotorDatabase, cohort_id: str) -> dict:
    doc = await db[LISTS].find_one({"cohort_id": cohort_id}, {"_id": 0, "rows": 0})
    return {"exists": doc is not None, **(doc or {})}


async def delete_list(db: AsyncIOMotorDatabase, cohort_id: str, actor: dict) -> dict:
    deleted = (await db[LISTS].delete_one({"cohort_id": cohort_id})).deleted_count
    if not deleted:
        raise SectionListError("There is no section list for this cohort.", 404)
    await record_audit_event(
        actor_user_id=actor["user_id"],
        actor_role=actor.get("role", "ADMIN"),
        action="SECTION_LIST_DELETED",
        resource_type="ACADEMIC",
        resource_id=cohort_id,
        metadata={},
    )
    return {"deleted": True}


def _differences(expected: dict, section: str, choices: dict) -> list[str]:
    out = []
    if expected["section"] != section:
        out.append(f"Section: list {expected['section']}, student {section}")
    for set_code, want in expected["choices"].items():
        got = choices.get(set_code)
        if got != want:
            have = f"{got['option']} {got['group']}" if got else "none"
            out.append(f"{set_code}: list {want['option']} {want['group']}, student {have}")
    return out


async def report(db: AsyncIOMotorDatabase, cohort_id: str, section: Optional[str] = None) -> dict:
    stored = await db[LISTS].find_one({"cohort_id": cohort_id})
    if stored is None:
        raise SectionListError("Upload the section list first.", 404)
    cohort = await db[org.COHORTS].find_one({"cohort_id": cohort_id}) or {}
    term_id = cohort.get("term_id")

    pending = {
        r["user_id"]: r
        async for r in db[enrolment.REQUESTS].find(
            {"cohort_id": cohort_id, "status": enrolment.PENDING}, {"template": 0}
        )
    }
    enrolled = {e["user_id"]: e async for e in db[enrolment.ENROLMENTS].find({"term_id": term_id})}
    profiles_by_roll: dict[str, dict] = {}
    async for p in db["student_profiles"].find(
        {}, {"user_id": 1, "roll_number": 1, "name": 1, "email": 1}
    ):
        if p.get("roll_number"):
            profiles_by_roll[str(p["roll_number"]).strip()] = p

    rows: list[dict] = []
    listed_users: set[str] = set()
    for expected in stored["rows"]:
        profile = profiles_by_roll.get(expected["roll_no"])
        entry: dict[str, Any] = {
            "roll_no": expected["roll_no"],
            "list": {k: expected[k] for k in ("name", "email", "section", "choices")},
            "student": None,
            "request": None,
            "differences": [],
            "warnings": [],
        }
        if profile is None:
            rows.append({**entry, "category": NOT_REGISTERED})
            continue
        user_id = profile["user_id"]
        listed_users.add(user_id)
        entry["student"] = {
            "user_id": user_id,
            "name": profile.get("name"),
            "email": profile.get("email"),
        }
        if _norm_name(profile.get("name")) != _norm_name(expected["name"]):
            entry["warnings"].append(
                f"Name: list {expected['name']!r}, student {profile.get('name')!r}"
            )
        request = pending.get(user_id)
        if request is not None:
            entry["request"] = {
                "request_id": request["request_id"],
                "kind": request["kind"],
                "section": request["section"],
                "choices": request["choices"],
            }
        if (profile.get("email") or "").lower() != expected["email"]:
            rows.append(
                {
                    **entry,
                    "category": EMAIL_DIFFERS,
                    "differences": [
                        f"Email: list {expected['email']}, student {profile.get('email')}"
                    ],
                }
            )
            continue
        if request is not None:
            diffs = _differences(expected, request["section"], request["choices"])
            rows.append({**entry, "category": DIFFERENT if diffs else MATCH, "differences": diffs})
            continue
        current = enrolled.get(user_id)
        if current is not None:
            diffs = _differences(expected, current["section"], current["choices"])
            rows.append(
                {
                    **entry,
                    "category": APPROVED_DIFFERS if diffs else APPROVED_AGREES,
                    "differences": diffs,
                }
            )
            continue
        rows.append({**entry, "category": NO_REQUEST})

    for user_id, request in pending.items():
        if user_id in listed_users:
            continue
        profile = await db["student_profiles"].find_one({"user_id": user_id}) or {}
        rows.append(
            {
                "roll_no": profile.get("roll_number"),
                "list": None,
                "student": {
                    "user_id": user_id,
                    "name": profile.get("name"),
                    "email": profile.get("email"),
                },
                "request": {
                    "request_id": request["request_id"],
                    "kind": request["kind"],
                    "section": request["section"],
                    "choices": request["choices"],
                },
                "category": NOT_ON_LIST,
                "differences": [],
                "warnings": [],
            }
        )

    if section:
        wanted = section.upper()
        rows = [
            r
            for r in rows
            if (r["list"] and r["list"]["section"] == wanted)
            or (r["request"] and r["request"]["section"] == wanted)
        ]
    order = {c: i for i, c in enumerate(CATEGORIES)}
    rows.sort(key=lambda r: (order[r["category"]], str(r["roll_no"] or "")))
    counts = {c: 0 for c in CATEGORIES}
    for row in rows:
        counts[row["category"]] += 1
    return {
        "cohort_id": cohort_id,
        "source_name": stored.get("source_name"),
        "uploaded_at": stored.get("uploaded_at"),
        "counts": counts,
        "rows": rows,
    }


async def approve_matching(
    db: AsyncIOMotorDatabase, cohort_id: str, request_ids: list[str], *, actor: dict
) -> dict:
    """Approve the given requests, but only if every one of them still matches the list."""
    if not request_ids:
        raise SectionListError("Select at least one request.")
    current = await report(db, cohort_id)
    matching = {r["request"]["request_id"] for r in current["rows"] if r["category"] == MATCH}
    stale = [rid for rid in dict.fromkeys(request_ids) if rid not in matching]
    if stale:
        raise SectionListError(
            "Some requests no longer match the section list; nothing was approved. Reload the report.",
            409,
            details={"not_matching": stale},
        )
    return await enrolment.decide(
        db, request_ids, action="approve", actor=actor, via="section_list"
    )
