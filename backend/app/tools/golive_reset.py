"""Clear the test data from the production database before the pilot starts.

Lists first, deletes only when told to. Without ``--apply`` nothing is
changed. Run on the instance through ``python infra/scripts/tf.py
golive-reset``, which takes a backup first; by hand, in the backend container::

    docker compose exec backend python -m app.tools.golive_reset --database <name>

Kept:
  * administrator accounts;
  * approved teacher accounts, their profiles, their class assignments and
    their approved choices;
  * the organisation: terms, cohorts, sections, groups, subjects, classes,
    timetable versions and slots, calendar, settings, section lists, cameras;
  * the audit log.

Removed:
  * every student, with their photos, face data, consents, setup requests and
    approved setup (the same removal an administrator's "delete student" does);
  * every session, roster, attendance record, correction and recognition nonce;
  * teacher accounts that are not approved, and teacher requests still waiting
    or refused.

To delete, repeat the command with ``--apply --expect N`` where N is the total
the listing showed; if the number no longer matches, nothing is deleted.
``--database`` must name the database the backend is connected to, so the
command cannot be pointed at the wrong one by accident. One audit entry holds
the counts only.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import settings
from app.core.uploads import (
    ENROLMENT_PHOTOS_SUBDIR,
    PENDING_PHOTOS_SUBDIR,
    STUDENT_PHOTOS_SUBDIR,
    resolve_uploads_root,
)
from app.services.approval_service import SYSTEM_ACTOR, delete_teacher_account
from app.services.audit_service import record_audit_event
from app.services.student_deletion import _refresh_vision_gallery, delete_student_completely

# Emptied completely: everything in them was made while testing.
SESSION_COLLECTIONS = (
    "sessions",
    "session_rosters",
    "session_roster",
    "attendance_records",
    "attendance_corrections",
    "attendance",
    "recognition_nonces",
)
# What is left of students once every student account is gone (records
# without an account, e.g. from an interrupted registration).
STUDENT_LEFTOVERS = (
    "student_profiles",
    "biometric_profiles",
    "consents",
    "enrolment_requests",
    "enrolments",
    "photo_change_requests",
)
PHOTO_SUBDIRS = (STUDENT_PHOTOS_SUBDIR, PENDING_PHOTOS_SUBDIR, ENROLMENT_PHOTOS_SUBDIR)


def _photo_files() -> list[Path]:
    root = resolve_uploads_root()
    files: list[Path] = []
    for sub in PHOTO_SUBDIRS:
        folder = root / sub
        if folder.is_dir():
            files += [p for p in folder.rglob("*") if p.is_file()]
    return files


async def plan(db: AsyncIOMotorDatabase) -> dict[str, Any]:
    """What a reset would remove now."""
    students = [u["user_id"] async for u in db["users"].find({"role": "STUDENT"}, {"user_id": 1})]
    teachers = [
        u["user_id"]
        async for u in db["users"].find(
            {"role": "TEACHER", "status": {"$ne": "APPROVED"}}, {"user_id": 1}
        )
    ]
    counts = {
        "student accounts": len(students),
        "teacher accounts not approved": len(teachers),
        "teacher requests waiting or refused": await db["teacher_requests"].count_documents(
            {"status": {"$ne": "APPROVED"}}
        ),
    }
    for name in SESSION_COLLECTIONS + (settings.EVENTS_COLLECTION,):
        counts[name] = await db[name].count_documents({})
    for name in STUDENT_LEFTOVERS:
        counts[name] = await db[name].count_documents({})
    counts["photo files"] = len(_photo_files())
    kept = {
        "administrators": await db["users"].count_documents({"role": "ADMIN"}),
        "approved teachers": await db["users"].count_documents(
            {"role": "TEACHER", "status": "APPROVED"}
        ),
        "classes": await db["org_classes"].count_documents({}),
        "timetable slots": await db["timetable_slots"].count_documents({}),
    }
    return {"students": students, "teachers": teachers, "counts": counts, "kept": kept}


def total(found: dict[str, Any]) -> int:
    return sum(found["counts"].values())


async def apply(db: AsyncIOMotorDatabase, found: dict[str, Any]) -> dict[str, int]:
    removed = dict(found["counts"])
    for user_id in found["students"]:
        await delete_student_completely(db, user_id, deleted_by=SYSTEM_ACTOR)
    for user_id in found["teachers"]:
        await delete_teacher_account(db, user_id)
    await db["teacher_requests"].delete_many({"status": {"$ne": "APPROVED"}})
    for name in SESSION_COLLECTIONS + (settings.EVENTS_COLLECTION,) + STUDENT_LEFTOVERS:
        await db[name].delete_many({})
    for path in _photo_files():
        path.unlink(missing_ok=True)
    await record_audit_event(
        actor_user_id=SYSTEM_ACTOR["user_id"],
        actor_role=SYSTEM_ACTOR["role"],
        action="GOLIVE_RESET",
        resource_type="SYSTEM",
        resource_id="golive_reset",
        metadata={"removed": removed},
    )
    await _refresh_vision_gallery()
    return removed


def _print(found: dict[str, Any]) -> None:
    print("Would remove:")
    for name, count in found["counts"].items():
        print(f"  {count:>7}  {name}")
    print("Keeps:")
    for name, count in found["kept"].items():
        print(f"  {count:>7}  {name}")
    print(f"Total to remove: {total(found)}")


async def _run(args: argparse.Namespace) -> int:
    from app.database.mongodb import get_database

    db = get_database()
    found = await plan(db)
    _print(found)
    if not args.apply:
        print("\nDry run: nothing was deleted. To delete exactly this, add:")
        print(f"  --apply --expect {total(found)}")
        return 0
    if args.expect != total(found):
        print(
            f"\nNothing was deleted: --expect {args.expect} does not match the "
            f"{total(found)} item(s) found now. Review the list again."
        )
        return 2
    await apply(db, found)
    print(
        "\nDone. The test data is gone; administrators, approved teachers and the timetable are kept."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--database", required=True, help="the database name, to confirm the target"
    )
    parser.add_argument("--apply", action="store_true", help="delete what the listing shows")
    parser.add_argument(
        "--expect", type=int, default=-1, help="with --apply: the total the dry run listed"
    )
    args = parser.parse_args(argv)
    if args.database != settings.DATABASE_NAME:
        print(
            f"Nothing was changed: --database '{args.database}' is not the database this "
            "backend uses. Give its name exactly."
        )
        return 2
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
