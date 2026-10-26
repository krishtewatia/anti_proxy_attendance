"""ENTRY and EXIT rounds of a timetable session, and the lectures they give.

Rule (the college's): a single period counts present only if the student was
present in both rounds; a double period gives one lecture per round. If the
teacher never held one of the rounds, the round that was held counts for both,
so a forgotten EXIT round does not mark the whole class absent.

Only sessions started from the timetable (they carry ``slot_id``) have rounds;
older ad-hoc sessions keep their single PRESENT/ABSENT mark. Recognition marks
only the round that is open; a manual mark locks that round against later
recognition. Teachers may mark or correct until they finalize or the edit
window ends; after that only an administrator, or the teacher once an
administrator unlocks the session.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.services import organisation_service as org
from app.services.audit_service import record_audit_event

ROUNDS = ("ENTRY", "EXIT")
UNLOCK_HOURS = 48


class RoundError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Any) -> Optional[datetime]:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if isinstance(value, datetime) and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def has_rounds(session: dict) -> bool:
    return bool(session.get("slot_id"))


def held_rounds(session: dict) -> list[str]:
    return [r for r in ROUNDS if (session.get("rounds") or {}).get(r, {}).get("opened_at")]


def lectures(periods: int, entry: bool, exit_: bool, held: list[str]) -> list[str]:
    """The lectures a student gets: "P" or "A" per period."""
    if "ENTRY" not in held and "EXIT" in held:
        entry = exit_
    if "EXIT" not in held and "ENTRY" in held:
        exit_ = entry
    if periods <= 1:
        return ["P" if entry and exit_ else "A"]
    first = (periods + 1) // 2
    return ["P" if entry else "A"] * first + ["P" if exit_ else "A"] * (periods - first)


def derived(record: dict, session: dict) -> dict:
    """The fields that follow from a record's round marks."""
    marks = record.get("rounds") or {}
    present = {r: (marks.get(r) or {}).get("status") == "PRESENT" for r in ROUNDS}
    result = lectures(
        int(session.get("periods") or 1), present["ENTRY"], present["EXIT"], held_rounds(session)
    )
    count = result.count("P")
    return {
        "lectures": result,
        "lectures_present": count,
        "lectures_total": len(result),
        "status": "PRESENT" if count else "ABSENT",
    }


async def _recompute_session(db: AsyncIOMotorDatabase, session: dict) -> None:
    """After the set of held rounds changes, every record's lectures follow."""
    async for record in db["attendance_records"].find({"session_id": session["session_id"]}):
        await db["attendance_records"].update_one(
            {"_id": record["_id"]}, {"$set": derived(record, session)}
        )


async def editable_until(db: AsyncIOMotorDatabase, session: dict) -> Optional[datetime]:
    end = _aware(session.get("end_time"))
    hours = (await org.get_settings(db))["edit_window_hours"]
    return end + timedelta(hours=hours) if end else None


async def teacher_may_edit(db: AsyncIOMotorDatabase, session: dict) -> bool:
    now = _now()
    unlocked = _aware(session.get("unlocked_until"))
    if unlocked and unlocked > now:
        return True
    # Ended or not, a teacher may correct until the window closes.
    until = await editable_until(db, session)
    return until is None or now <= until


# ------------------------------------------------------------------ rounds


async def set_round(
    db: AsyncIOMotorDatabase, session: dict, round_name: str, *, open_: bool, actor: dict
) -> dict:
    if not has_rounds(session):
        raise RoundError(
            "Only sessions started from the timetable have ENTRY and EXIT rounds.", 409
        )
    if round_name not in ROUNDS:
        raise RoundError("The round is ENTRY or EXIT.", 404)
    if session.get("status") != "ACTIVE":
        raise RoundError("Start the session first; a finalized session takes no rounds.", 409)
    now = _now()
    rounds = dict(session.get("rounds") or {})
    if open_:
        current = session.get("open_round")
        if current and current != round_name:
            rounds[current] = {**rounds.get(current, {}), "closed_at": now}
        entry = dict(rounds.get(round_name) or {})
        reopened = bool(entry.get("opened_at"))
        entry.update(
            {
                "opened_at": entry.get("opened_at") or now,
                "last_opened_at": now,
                "opened_by": actor["user_id"],
                "closed_at": None,
            }
        )
        entry["times_opened"] = int(entry.get("times_opened") or 0) + 1
        rounds[round_name] = entry
        update = {"rounds": rounds, "open_round": round_name}
        action_detail = {"round": round_name, "reopened": reopened}
    else:
        if session.get("open_round") != round_name:
            raise RoundError(f"The {round_name} round is not open.", 409)
        rounds[round_name] = {**rounds.get(round_name, {}), "closed_at": now}
        update = {"rounds": rounds, "open_round": None}
        action_detail = {"round": round_name, "closed": True}
    await db["sessions"].update_one({"session_id": session["session_id"]}, {"$set": update})
    session = {**session, **update}
    await _recompute_session(db, session)
    await record_audit_event(
        actor_user_id=actor["user_id"],
        actor_role=actor.get("role", "TEACHER"),
        action="SESSION_ROUND_CHANGED",
        resource_type="SESSION",
        resource_id=session["session_id"],
        metadata=action_detail,
    )
    return round_info(session)


async def close_open_round(db: AsyncIOMotorDatabase, session_id: str) -> None:
    """Called when a session is finalized."""
    session = await db["sessions"].find_one({"session_id": session_id})
    if session and session.get("open_round"):
        rounds = dict(session.get("rounds") or {})
        name = session["open_round"]
        rounds[name] = {**rounds.get(name, {}), "closed_at": _now()}
        await db["sessions"].update_one(
            {"session_id": session_id}, {"$set": {"rounds": rounds, "open_round": None}}
        )


def round_info(session: dict) -> dict:
    rounds = session.get("rounds") or {}
    return {
        "periods": int(session.get("periods") or 1),
        "open_round": session.get("open_round"),
        "held": held_rounds(session),
        "rounds": {
            r: {k: rounds.get(r, {}).get(k) for k in ("opened_at", "closed_at", "times_opened")}
            for r in ROUNDS
        },
        "unlocked_until": session.get("unlocked_until"),
    }


# ------------------------------------------------------------------ marks


async def mark_from_recognition(
    db: AsyncIOMotorDatabase, session: dict, identity: str, profile: dict
) -> str:
    """Mark the open round for a verified recognition; returns the mark status."""
    round_name = session.get("open_round")
    if not round_name:
        return "no_round_open"
    record = (
        await db["attendance_records"].find_one(
            {"session_id": session["session_id"], "identity": identity}
        )
        or {}
    )
    mark = (record.get("rounds") or {}).get(round_name) or {}
    if mark.get("source") == "MANUAL":
        return "locked"
    if mark.get("status") == "PRESENT":
        return "already_present"
    rounds = {
        **(record.get("rounds") or {}),
        round_name: {"status": "PRESENT", "at": _now(), "source": "RECOGNITION"},
    }
    merged = {**record, "rounds": rounds}
    await db["attendance_records"].update_one(
        {"session_id": session["session_id"], "identity": identity},
        {
            "$set": {
                "rounds": rounds,
                **derived(merged, session),
                "marked_at": _now(),
                "attendance_id": record.get("attendance_id")
                or f"att_{session['session_id']}_{identity}",
                "student_id": record.get("student_id") or profile.get("student_id", identity),
                "student_name": record.get("student_name") or profile.get("name", identity),
            }
        },
        upsert=True,
    )
    return "marked"


async def mark_by_hand(
    db: AsyncIOMotorDatabase,
    session: dict,
    round_name: str,
    identity: str,
    status: str,
    reason: str,
    actor: dict,
) -> dict:
    if not has_rounds(session):
        raise RoundError(
            "Only sessions started from the timetable have ENTRY and EXIT rounds.", 409
        )
    if round_name not in ROUNDS or status not in ("PRESENT", "ABSENT"):
        raise RoundError("Give a round (ENTRY or EXIT) and a status (PRESENT or ABSENT).")
    if actor.get("role") != "ADMIN" and not await teacher_may_edit(db, session):
        raise RoundError(
            "This session can no longer be changed by a teacher (finalized or past the edit window). Ask an administrator.",
            403,
        )
    if actor.get("role") == "ADMIN" and not reason.strip():
        raise RoundError("An administrator must give a reason.")
    roster = await db["session_rosters"].find_one({"session_id": session["session_id"]}) or {}
    if identity not in (roster.get("identities") or []):
        raise RoundError("This student is not on the session's roster.", 404)
    record = (
        await db["attendance_records"].find_one(
            {"session_id": session["session_id"], "identity": identity}
        )
        or {}
    )
    before = ((record.get("rounds") or {}).get(round_name) or {}).get("status", "ABSENT")
    now = _now()
    rounds = {
        **(record.get("rounds") or {}),
        round_name: {"status": status, "at": now, "source": "MANUAL", "by": actor["user_id"]},
    }
    # A manual mark also counts the round as held, so lectures follow it.
    if not (session.get("rounds") or {}).get(round_name, {}).get("opened_at"):
        session_rounds = {
            **(session.get("rounds") or {}),
            round_name: {
                "opened_at": now,
                "closed_at": now,
                "opened_by": actor["user_id"],
                "times_opened": 0,
            },
        }
        await db["sessions"].update_one(
            {"session_id": session["session_id"]}, {"$set": {"rounds": session_rounds}}
        )
        session = {**session, "rounds": session_rounds}
        await _recompute_session(db, session)
        record = (
            await db["attendance_records"].find_one(
                {"session_id": session["session_id"], "identity": identity}
            )
            or record
        )
    fields = derived({**record, "rounds": rounds}, session)
    await db["attendance_records"].update_one(
        {"session_id": session["session_id"], "identity": identity},
        {
            "$set": {
                "rounds": rounds,
                **fields,
                "manually_corrected": True,
                "last_corrected_at": now,
                "last_corrected_by": actor["user_id"],
            }
        },
    )
    await record_audit_event(
        actor_user_id=actor["user_id"],
        actor_role=actor.get("role", "TEACHER"),
        action="ATTENDANCE_CORRECTED",
        resource_type="ATTENDANCE",
        resource_id=f"att_{session['session_id']}_{identity}",
        metadata={
            "session_id": session["session_id"],
            "identity": identity,
            "round": round_name,
            "previous_status": before,
            "new_status": status,
            "reason": reason.strip(),
            "corrected_by_role": actor.get("role", "TEACHER"),
        },
    )
    return {"identity": identity, "round": round_name, "status": status, **fields}


async def unlock(db: AsyncIOMotorDatabase, session: dict, actor: dict) -> dict:
    until = _now() + timedelta(hours=UNLOCK_HOURS)
    await db["sessions"].update_one(
        {"session_id": session["session_id"]},
        {"$set": {"unlocked_until": until, "unlocked_by": actor["user_id"]}},
    )
    await record_audit_event(
        actor_user_id=actor["user_id"],
        actor_role="ADMIN",
        action="SESSION_UNLOCKED",
        resource_type="SESSION",
        resource_id=session["session_id"],
        metadata={"hours": UNLOCK_HOURS},
    )
    return {"session_id": session["session_id"], "unlocked_until": until}


async def end_if_class_is_over(db: AsyncIOMotorDatabase, session: dict) -> bool:
    """End a running timetable session whose class time is over; True if it was ended.

    Its marks stay as they are and the teacher can still correct them within
    the edit window. Ad-hoc sessions are never ended this way.
    """
    end = _aware(session.get("end_time"))
    if not has_rounds(session) or end is None or end > _now():
        return False
    await close_open_round(db, session["session_id"])
    await db["sessions"].update_one(
        {"session_id": session["session_id"], "status": "ACTIVE"},
        {"$set": {"status": "FINALIZED", "ended_automatically": True}},
    )
    return True
