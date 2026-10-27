"""ENTRY and EXIT rounds of a timetable session, and the lectures they give.

Rule (the college's): a single period counts present only if the student was
present in both rounds; a double period gives one lecture per round.

A class is taken in two steps: ENTRY (opened, the camera marks, then
finalized), then EXIT the same way. A finalized round never takes the camera
again; its marks can be changed by hand for ``edit_window_hours`` (24 h) after
it was finalized, then it locks (an administrator can unlock it). The class is
*complete* once both rounds are finalized, and only complete classes count in
any figure. A class left incomplete can still be finished by hand until its end
time plus the same window; after that it counts as not taken.

Only sessions started from the timetable (they carry ``slot_id``) have rounds;
older ad-hoc sessions keep their single PRESENT/ABSENT mark. Recognition marks
only the round that is open. A teacher changes marks by hand only once both
rounds are finalized (an administrator at any time, with a reason); a hand
mark locks that student's round against later recognition.
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


def finalized_at(session: dict, round_name: str) -> Optional[datetime]:
    return _aware(((session.get("rounds") or {}).get(round_name) or {}).get("finalized_at"))


def is_complete(session: dict) -> bool:
    """Both rounds finalized: the class's attendance is final."""
    return has_rounds(session) and all(finalized_at(session, r) for r in ROUNDS)


def is_pending(session: dict, hours: int, now: Optional[datetime] = None) -> bool:
    """Not complete yet, but still within the time to finish it."""
    if not has_rounds(session) or is_complete(session):
        return False
    end = _aware(session.get("end_time"))
    return end is None or (now or _now()) <= end + timedelta(hours=hours)


async def _window_hours(db: AsyncIOMotorDatabase) -> int:
    return int((await org.get_settings(db))["edit_window_hours"])


def _round_until(session: dict, round_name: str, hours: int) -> Optional[datetime]:
    """Until when a teacher may change this round by hand (None: no limit yet)."""
    done = finalized_at(session, round_name)
    if done:
        return done + timedelta(hours=hours)
    if session.get("status") == "ACTIVE":
        return None
    end = _aware(session.get("end_time"))
    return end + timedelta(hours=hours) if end else None


async def round_may_edit(db: AsyncIOMotorDatabase, session: dict, round_name: str) -> bool:
    now = _now()
    unlocked = _aware(session.get("unlocked_until"))
    if unlocked and unlocked > now:
        return True
    until = _round_until(session, round_name, await _window_hours(db))
    return until is None or now <= until


async def editable_until(db: AsyncIOMotorDatabase, session: dict) -> Optional[datetime]:
    """The later of the two rounds' limits (None while one has no limit yet)."""
    hours = await _window_hours(db)
    limits = [_round_until(session, r, hours) for r in ROUNDS]
    if any(limit is None for limit in limits):
        return None
    return max(limits)


async def teacher_may_edit(db: AsyncIOMotorDatabase, session: dict) -> bool:
    """True while a teacher may still change at least one of the rounds by hand."""
    for round_name in ROUNDS:
        if await round_may_edit(db, session, round_name):
            return True
    return False


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
        if finalized_at(session, round_name):
            raise RoundError(
                f"{round_name} is finalized: the camera is off for it. Change its marks by hand.",
                409,
            )
        if round_name == "EXIT" and not finalized_at(session, "ENTRY"):
            raise RoundError("Finalize ENTRY first, then start EXIT.", 409)
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


def next_step(session: dict) -> str:
    """ENTRY, EXIT or FINALIZE: what the teacher does next."""
    if not finalized_at(session, "ENTRY"):
        return "ENTRY"
    if not finalized_at(session, "EXIT"):
        return "EXIT"
    return "FINALIZE"


def round_info(session: dict) -> dict:
    rounds = session.get("rounds") or {}
    return {
        "periods": int(session.get("periods") or 1),
        "open_round": session.get("open_round"),
        "held": held_rounds(session),
        # Times carry their zone: the database returns them without one.
        "rounds": {
            r: {
                "opened_at": _aware(rounds.get(r, {}).get("opened_at")),
                "closed_at": _aware(rounds.get(r, {}).get("closed_at")),
                "times_opened": rounds.get(r, {}).get("times_opened"),
                "finalized_at": _aware(rounds.get(r, {}).get("finalized_at")),
            }
            for r in ROUNDS
        },
        "complete": is_complete(session),
        "next_step": next_step(session),
        "unlocked_until": _aware(session.get("unlocked_until")),
    }


async def round_state(db: AsyncIOMotorDatabase, session: dict) -> dict:
    """round_info plus, per round, until when and whether the teacher may edit it."""
    info = round_info(session)
    hours = await _window_hours(db)
    for round_name in ROUNDS:
        until = _round_until(session, round_name, hours)
        info["rounds"][round_name]["editable_until"] = until
        info["rounds"][round_name]["may_edit"] = await round_may_edit(db, session, round_name)
    info["editable_until"] = await editable_until(db, session)
    info["teacher_may_edit"] = await teacher_may_edit(db, session)
    return info


async def finalize_round(
    db: AsyncIOMotorDatabase, session: dict, round_name: str, *, actor: dict
) -> dict:
    """End a round for good: the camera stops for it; hand changes for the window."""
    if not has_rounds(session):
        raise RoundError(
            "Only sessions started from the timetable have ENTRY and EXIT rounds.", 409
        )
    if round_name not in ROUNDS:
        raise RoundError("The round is ENTRY or EXIT.", 404)
    if finalized_at(session, round_name):
        return await round_state(db, session)
    if round_name == "EXIT" and not finalized_at(session, "ENTRY"):
        raise RoundError("Finalize ENTRY first, then EXIT.", 409)
    if session.get("status") != "ACTIVE" and actor.get("role") != "ADMIN":
        if not await round_may_edit(db, session, round_name):
            raise RoundError(
                "This class can no longer be finished by a teacher. Ask an administrator.", 403
            )
    now = _now()
    rounds = dict(session.get("rounds") or {})
    entry = dict(rounds.get(round_name) or {})
    # A round that was never opened is still taken: nobody was marked in it.
    entry.setdefault("times_opened", 0)
    entry["opened_at"] = entry.get("opened_at") or now
    entry["closed_at"] = entry.get("closed_at") or now
    entry.update({"finalized_at": now, "finalized_by": actor["user_id"]})
    rounds[round_name] = entry
    update: dict[str, Any] = {"rounds": rounds}
    if session.get("open_round") == round_name:
        entry["closed_at"] = now
        update["open_round"] = None
    await db["sessions"].update_one({"session_id": session["session_id"]}, {"$set": update})
    session = {**session, **update}
    await _recompute_session(db, session)
    await record_audit_event(
        actor_user_id=actor["user_id"],
        actor_role=actor.get("role", "TEACHER"),
        action="SESSION_ROUND_CHANGED",
        resource_type="SESSION",
        resource_id=session["session_id"],
        metadata={"round": round_name, "finalized": True},
    )
    return await round_state(db, session)


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
    # While a round runs only the camera marks; a teacher corrects the final
    # attendance by hand once ENTRY and EXIT are both finalized.
    if actor.get("role") != "ADMIN" and not is_complete(session):
        raise RoundError("Hand changes are possible once ENTRY and EXIT are both finalized.", 409)
    if actor.get("role") != "ADMIN" and not await round_may_edit(db, session, round_name):
        raise RoundError(
            f"{round_name} can no longer be changed by a teacher (more than "
            f"{await _window_hours(db)} h since it was finalized). Ask an administrator.",
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
