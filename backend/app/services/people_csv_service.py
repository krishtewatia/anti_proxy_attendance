"""Students and teachers to and from CSV, for keeping them on file.

An administrator downloads the students (or teachers) as a CSV and can load
the file back if accounts are ever lost. A file is checked first (a dry run
that changes nothing) and only then applied. Applying only adds accounts that
are missing: an existing account is never overwritten.

The files carry each account's password hash (bcrypt, never the password), so
a restored account signs in as before, and the ids (``user_id``, ``identity``)
that the photo backups and the face data in the database are keyed by. They
carry no face data. Treat them as confidential.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import re
import secrets
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.account_status import ACCOUNT_APPROVED, ACCOUNT_PENDING
from app.security.passwords import hash_password
from app.services import enrolment_service as enrolment
from app.services import organisation_service as org
from app.services import registry_service as registry
from app.services.audit_service import record_audit_event

STUDENT_COLUMNS = [
    "user_id",
    "identity",
    "roll_number",
    "name",
    "email",
    "status",
    "cohort_id",
    "section",
    "DE-II",
    "DE-III",
    "DLDA",
    "password_hash",
]
TEACHER_COLUMNS = ["user_id", "name", "email", "department", "status", "class_ids", "password_hash"]
GROUP_SETS = ("DE-II", "DE-III", "DLDA")
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
_BCRYPT = re.compile(r"^\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}$")
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_ROLL = re.compile(r"^\d{8,20}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_STATUSES = {ACCOUNT_APPROVED, ACCOUNT_PENDING}


class CsvError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _csv(header: list[str], rows: list[list[Any]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def _cell(value: Any) -> str:
    """A value as written to the file; a leading =, +, - or @ is quoted so a
    spreadsheet never runs it as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") and not text.startswith("$2") else text


def _choice_text(choice: Optional[dict], code: str) -> str:
    if not choice:
        return ""
    return f"{choice['option']}/{choice['group']}"


# ------------------------------------------------------------------ export


async def export_students(db: AsyncIOMotorDatabase, filters: dict, actor: dict) -> str:
    rows = (await registry.students(db, filters))["students"]
    ids = [r["user_id"] for r in rows]
    users = {u["user_id"]: u async for u in db["users"].find({"user_id": {"$in": ids}}, {"_id": 0})}
    profiles = {
        p["user_id"]: p
        async for p in db["student_profiles"].find({"user_id": {"$in": ids}}, {"_id": 0})
    }
    out = []
    for r in rows:
        user, profile = users.get(r["user_id"], {}), profiles.get(r["user_id"], {})
        choices = r.get("choices") or {}
        out.append(
            [
                _cell(v)
                for v in (
                    r["user_id"],
                    profile.get("identity") or profile.get("student_id"),
                    r.get("roll_number"),
                    r.get("name"),
                    r.get("email"),
                    user.get("status", ACCOUNT_APPROVED),
                    r.get("cohort_id"),
                    r.get("section"),
                    *(_choice_text(choices.get(code), code) for code in GROUP_SETS),
                    user.get("password_hash"),
                )
            ]
        )
    await _audit(actor, "export", "students", {"rows": len(out)})
    return _csv(STUDENT_COLUMNS, out)


async def export_teachers(db: AsyncIOMotorDatabase, actor: dict) -> str:
    rows = (await registry.teachers(db))["teachers"]
    users = {
        u["user_id"]: u
        async for u in db["users"].find(
            {"user_id": {"$in": [r["user_id"] for r in rows]}}, {"_id": 0}
        )
    }
    out = [
        [
            _cell(v)
            for v in (
                r["user_id"],
                r.get("name"),
                r.get("email"),
                r.get("department"),
                users.get(r["user_id"], {}).get("status", ACCOUNT_APPROVED),
                ";".join(c["class_id"] for c in r.get("classes") or []),
                users.get(r["user_id"], {}).get("password_hash"),
            )
        ]
        for r in rows
    ]
    await _audit(actor, "export", "teachers", {"rows": len(out)})
    return _csv(TEACHER_COLUMNS, out)


# ------------------------------------------------------------------ import


def _read(data: bytes, columns: list[str]) -> list[dict[str, str]]:
    if len(data) > MAX_BYTES:
        raise CsvError("The file is larger than 2 MB.", 413)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvError("The file is not UTF-8 text (save it as CSV UTF-8).") from exc
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in columns if c not in (reader.fieldnames or [])]
    if missing:
        raise CsvError(
            f"Missing columns: {', '.join(missing)}. Use a file downloaded from this page."
        )
    rows = []
    for row in reader:
        if len(rows) >= MAX_ROWS:
            raise CsvError(f"More than {MAX_ROWS} rows; split the file.")
        clean = {k: (v or "").strip() for k, v in row.items() if k in columns}
        for key, value in clean.items():
            if value.startswith("'") and value[1:2] in ("=", "+", "-", "@"):
                clean[key] = value[1:]
        if any(clean.values()):
            rows.append(clean)
    return rows


def _common_errors(row: dict[str, str], seen: dict[str, set]) -> list[str]:
    errors = []
    if not _ID.match(row["user_id"]):
        errors.append("user_id is missing or has characters that are not allowed")
    if not _EMAIL.match(row["email"]):
        errors.append("email is not an email address")
    if (row["status"] or ACCOUNT_APPROVED).upper() not in _STATUSES:
        errors.append("status must be APPROVED or PENDING")
    if row["password_hash"] and not _BCRYPT.match(row["password_hash"]):
        errors.append("password_hash is not a bcrypt hash (leave it empty to set a password later)")
    for field in ("user_id", "email"):
        value = row[field].lower()
        if value and value in seen[field]:
            errors.append(f"{field} appears twice in the file")
        seen[field].add(value)
    return errors


async def _existing(db: AsyncIOMotorDatabase, rows: list[dict[str, str]]) -> tuple[set, set]:
    ids = [r["user_id"] for r in rows]
    emails = [r["email"].lower() for r in rows]
    by_id, by_email = set(), set()
    async for u in db["users"].find(
        {"$or": [{"user_id": {"$in": ids}}, {"email": {"$in": emails}}]}, {"user_id": 1, "email": 1}
    ):
        by_id.add(u["user_id"])
        by_email.add((u.get("email") or "").lower())
    return by_id, by_email


async def check_students(db: AsyncIOMotorDatabase, data: bytes) -> dict[str, Any]:
    rows = _read(data, STUDENT_COLUMNS)
    by_id, by_email = await _existing(db, rows)
    taken_identity = {
        p.get("identity")
        async for p in db["student_profiles"].find(
            {"identity": {"$in": [r["identity"] for r in rows]}}, {"identity": 1}
        )
    }
    taken_roll = {
        p.get("roll_number")
        async for p in db["student_profiles"].find(
            {"roll_number": {"$in": [r["roll_number"] for r in rows]}}, {"roll_number": 1}
        )
    }
    seen: dict[str, set] = {
        "user_id": set(),
        "email": set(),
        "identity": set(),
        "roll_number": set(),
    }
    plan: dict[str, Any] = {"create": [], "existing": 0, "errors": []}
    for line, row in enumerate(rows, start=2):
        errors = _common_errors(row, seen)
        if not _ID.match(row["identity"]):
            errors.append("identity is missing or has characters that are not allowed")
        if not _ROLL.match(row["roll_number"]):
            errors.append("roll_number must be 8 to 20 digits")
        if len(row["name"]) < 2:
            errors.append("name is missing")
        for field in ("identity", "roll_number"):
            if row[field] and row[field] in seen[field]:
                errors.append(f"{field} appears twice in the file")
            seen[field].add(row[field])
        if row["user_id"] in by_id or row["email"].lower() in by_email:
            if not errors:
                plan["existing"] += 1
            else:
                plan["errors"].append({"line": line, "errors": errors})
            continue
        if row["identity"] in taken_identity:
            errors.append("identity belongs to another account already")
        if row["roll_number"] in taken_roll:
            errors.append("roll_number belongs to another student already")
        setup = None
        if row["cohort_id"] or row["section"]:
            choices = {}
            for code in GROUP_SETS:
                if row[code]:
                    option, _, group = row[code].partition("/")
                    choices[code] = {"option": option, "group": group or option}
            try:
                clean, class_ids, cohort = await enrolment.resolve_choices(
                    db, row["cohort_id"], row["section"], choices
                )
                setup = {
                    "cohort_id": row["cohort_id"],
                    "term_id": cohort.get("term_id"),
                    "section": clean["section"],
                    "choices": clean["groups"],
                    "class_ids": class_ids,
                }
            except enrolment.EnrolmentError as exc:
                errors.append(f"setup: {exc}")
        if errors:
            plan["errors"].append({"line": line, "errors": errors})
        else:
            plan["create"].append({**row, "setup": setup})
    return plan


async def check_teachers(db: AsyncIOMotorDatabase, data: bytes) -> dict[str, Any]:
    rows = _read(data, TEACHER_COLUMNS)
    by_id, by_email = await _existing(db, rows)
    known = {c["class_id"] async for c in db[org.CLASSES].find({}, {"class_id": 1})}
    seen: dict[str, set] = {"user_id": set(), "email": set()}
    plan: dict[str, Any] = {"create": [], "existing": 0, "errors": []}
    for line, row in enumerate(rows, start=2):
        errors = _common_errors(row, seen)
        if len(row["name"]) < 2:
            errors.append("name is missing")
        class_ids = [c.strip() for c in row["class_ids"].split(";") if c.strip()]
        unknown = [c for c in class_ids if c not in known]
        if unknown:
            errors.append(f"unknown class: {', '.join(unknown)}")
        if row["user_id"] in by_id or row["email"].lower() in by_email:
            if errors:
                plan["errors"].append({"line": line, "errors": errors})
            else:
                plan["existing"] += 1
            continue
        if errors:
            plan["errors"].append({"line": line, "errors": errors})
        else:
            plan["create"].append({**row, "class_list": class_ids})
    return plan


def summary(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "to_create": len(plan["create"]),
        "existing": plan["existing"],
        "errors": plan["errors"],
        "rows": [
            {k: r.get(k) for k in ("user_id", "roll_number", "name", "email", "section")}
            for r in plan["create"][:50]
        ],
    }


def _password(row: dict[str, str]) -> str:
    # No hash in the file: an unguessable one, so the account cannot sign in
    # until an administrator resets its password.
    return row["password_hash"] or hash_password(secrets.token_urlsafe(32))


async def apply_students(db: AsyncIOMotorDatabase, plan: dict[str, Any], actor: dict) -> int:
    now = datetime.now(timezone.utc)
    for row in plan["create"]:
        await db["users"].insert_one(
            {
                "user_id": row["user_id"],
                "email": row["email"].lower(),
                "password_hash": _password(row),
                "role": "STUDENT",
                "status": (row["status"] or ACCOUNT_APPROVED).upper(),
                "is_active": True,
                "created_at": now,
                "restored_from_csv": True,
            }
        )
        has_face = await db["biometric_profiles"].count_documents({"identity": row["identity"]}) > 0
        await db["student_profiles"].insert_one(
            {
                "user_id": row["user_id"],
                "identity": row["identity"],
                "student_id": row["identity"],
                "name": row["name"],
                "email": row["email"].lower(),
                "roll_number": row["roll_number"],
                "section": (row.get("setup") or {}).get("section"),
                "has_biometric": has_face,
                "created_at": now,
                "updated_at": now,
            }
        )
        if row.get("setup"):
            await db[enrolment.ENROLMENTS].insert_one(
                {
                    "user_id": row["user_id"],
                    "identity": row["identity"],
                    **row["setup"],
                    "approved_request_id": None,
                    "since": now,
                    "restored_from_csv": True,
                }
            )
    await _audit(
        actor, "import", "students", {"created": len(plan["create"]), "existing": plan["existing"]}
    )
    return len(plan["create"])


async def apply_teachers(db: AsyncIOMotorDatabase, plan: dict[str, Any], actor: dict) -> int:
    now = datetime.now(timezone.utc)
    for row in plan["create"]:
        await db["users"].insert_one(
            {
                "user_id": row["user_id"],
                "email": row["email"].lower(),
                "password_hash": _password(row),
                "role": "TEACHER",
                "status": (row["status"] or ACCOUNT_APPROVED).upper(),
                "is_active": True,
                "created_at": now,
                "restored_from_csv": True,
            }
        )
        await db["teacher_profiles"].insert_one(
            {
                "user_id": row["user_id"],
                "teacher_id": f"T-{row['user_id'][-8:]}",
                "name": row["name"],
                "email": row["email"].lower(),
                "department": row["department"],
                "assigned_classes": [],
                "assigned_subjects": [],
                "created_at": now,
                "updated_at": now,
            }
        )
        if row["class_list"]:
            await db[org.CLASSES].update_many(
                {"class_id": {"$in": row["class_list"]}},
                {"$addToSet": {"teacher_ids": row["user_id"]}},
            )
    await _audit(
        actor, "import", "teachers", {"created": len(plan["create"]), "existing": plan["existing"]}
    )
    return len(plan["create"])


async def _audit(actor: dict, what: str, kind: str, counts: dict[str, int]) -> None:
    await record_audit_event(
        actor_user_id=actor["user_id"],
        actor_role=actor.get("role", "ADMIN"),
        action="PEOPLE_CSV_EXPORTED" if what == "export" else "PEOPLE_CSV_IMPORTED",
        resource_type="USER",
        resource_id=f"{kind}_csv",
        metadata={"kind": kind, **counts},
    )
