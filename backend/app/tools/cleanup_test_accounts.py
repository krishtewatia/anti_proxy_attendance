"""Remove accounts that automated tests left in a development database.

Lists first, deletes only when told to. Without ``--apply`` nothing is
changed. Run it in the backend container (from the folder that holds
docker-compose.yml)::

    docker compose exec backend python -m app.tools.cleanup_test_accounts

Two rules decide what is listed:

1. Always: a student or teacher account that has no profile and has created
   no session. Nothing depends on such an account.
2. Only with ``--include-test-pattern``: an account whose email carries a
   test timestamp (``name_1759912345678@...``). These can have a profile or
   sessions; their sessions, rosters and the attendance recorded in those
   sessions are removed with them.

Administrator accounts are never listed. To delete, repeat the command with
``--apply --expect N`` where N is the number of accounts the listing showed;
if the number no longer matches, nothing is deleted.

Each removed account gets one audit entry holding IDs and counts only.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import settings
from app.services.approval_service import SYSTEM_ACTOR, delete_teacher_account
from app.services.audit_service import record_audit_event
from app.services.student_deletion import delete_student_completely

# name_<10 or more digits>@domain: the form every test suite uses for a throwaway address.
TEST_EMAIL_PATTERN = re.compile(r"_\d{10,}@")

RULE_ORPHAN = "no profile and no sessions"
RULE_TEST_PATTERN = "test email pattern"


async def find_candidates(
    db: AsyncIOMotorDatabase, *, include_test_pattern: bool = False
) -> list[dict[str, Any]]:
    """Accounts the rules select, oldest first. Reads only."""
    student_users = set(await db["student_profiles"].distinct("user_id"))
    teacher_users = set(await db["teacher_profiles"].distinct("user_id"))
    candidates: list[dict[str, Any]] = []

    cursor = db["users"].find({"role": {"$in": ["STUDENT", "TEACHER"]}}, {"password_hash": 0})
    async for user in cursor.sort("created_at", 1):
        user_id = user["user_id"]
        role = user["role"]
        has_profile = user_id in (student_users if role == "STUDENT" else teacher_users)
        sessions = await db["sessions"].count_documents({"created_by": user_id})

        if not has_profile and sessions == 0:
            rule = RULE_ORPHAN
        elif include_test_pattern and TEST_EMAIL_PATTERN.search(user.get("email") or ""):
            rule = RULE_TEST_PATTERN
        else:
            continue
        candidates.append(
            {
                "user_id": user_id,
                "role": role,
                "email": user.get("email") or "",
                "has_profile": has_profile,
                "sessions": sessions,
                "created_at": user.get("created_at"),
                "rule": rule,
            }
        )
    return candidates


async def _remove_sessions_of(db: AsyncIOMotorDatabase, user_id: str) -> dict[str, int]:
    session_ids = [
        doc["session_id"]
        async for doc in db["sessions"].find({"created_by": user_id}, {"session_id": 1})
    ]
    if not session_ids:
        return {"sessions": 0, "rosters": 0, "attendance_records": 0, "doorway_events": 0}
    in_sessions = {"session_id": {"$in": session_ids}}
    return {
        "rosters": (await db["session_rosters"].delete_many(in_sessions)).deleted_count,
        "attendance_records": (
            await db["attendance_records"].delete_many(in_sessions)
        ).deleted_count,
        "doorway_events": (
            await db[settings.EVENTS_COLLECTION].delete_many(in_sessions)
        ).deleted_count,
        "sessions": (await db["sessions"].delete_many(in_sessions)).deleted_count,
    }


async def remove_account(
    db: AsyncIOMotorDatabase, candidate: dict[str, Any], *, actor: dict[str, Any]
) -> dict[str, Any]:
    """Delete one listed account and what the rule says goes with it."""
    user_id = candidate["user_id"]
    user = await db["users"].find_one({"user_id": user_id}, {"role": 1})
    if user is None or user.get("role") not in {"STUDENT", "TEACHER"}:
        return {"user_id": user_id, "removed": False}

    removed: dict[str, Any] = {}
    if candidate["rule"] == RULE_TEST_PATTERN:
        removed.update(await _remove_sessions_of(db, user_id))
    if user["role"] == "STUDENT":
        # Writes its own STUDENT_DELETED entry as well.
        removed.update((await delete_student_completely(db, user_id, deleted_by=actor)).counts())
    else:
        removed.update(await delete_teacher_account(db, user_id))

    await record_audit_event(
        actor_user_id=actor["user_id"],
        actor_role=actor.get("role", "SYSTEM"),
        action="TEST_ACCOUNT_REMOVED",
        resource_type="USER",
        resource_id=user_id,
        metadata={"role": user["role"], "rule": candidate["rule"], "removed": removed},
    )
    return {"user_id": user_id, "removed": True, "counts": removed}


def _print_listing(candidates: list[dict[str, Any]]) -> None:
    for item in candidates:
        created = item["created_at"].date().isoformat() if item.get("created_at") else "?"
        print(
            f"{item['role']:<8}{item['email']:<56}"
            f"{'profile' if item['has_profile'] else 'no profile':<12}"
            f"{item['sessions']:>3} sessions  {created}  [{item['rule']}]"
        )
    by_rule: dict[str, int] = {}
    for item in candidates:
        by_rule[item["rule"]] = by_rule.get(item["rule"], 0) + 1
    print(
        f"\n{len(candidates)} account(s) selected: "
        + (", ".join(f"{count} by '{rule}'" for rule, count in sorted(by_rule.items())) or "none")
    )


async def _run(args: argparse.Namespace) -> int:
    from app.database.mongodb import get_database

    db = get_database()
    candidates = await find_candidates(db, include_test_pattern=args.include_test_pattern)
    _print_listing(candidates)

    if not args.apply:
        print("\nDry run: nothing was deleted. To delete exactly this list, add:")
        print(f"  --apply --expect {len(candidates)}")
        return 0
    if args.expect != len(candidates):
        print(
            f"\nNothing was deleted: --expect {args.expect} does not match the "
            f"{len(candidates)} account(s) selected now. Review the list again."
        )
        return 2

    done = 0
    for candidate in candidates:
        if (await remove_account(db, candidate, actor=SYSTEM_ACTOR))["removed"]:
            done += 1
    print(f"\nDeleted {done} account(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--include-test-pattern",
        action="store_true",
        help="also select accounts whose email carries a test timestamp, with their sessions",
    )
    parser.add_argument("--apply", action="store_true", help="delete the listed accounts")
    parser.add_argument(
        "--expect",
        type=int,
        default=-1,
        help="with --apply: the number of accounts the dry run listed",
    )
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
