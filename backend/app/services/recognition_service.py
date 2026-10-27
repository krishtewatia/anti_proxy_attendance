"""Verification of signed recognition results and the single mark-present path.

The vision service signs every confirmed recognition. The backend marks a
student PRESENT only through ``verify_and_mark``, which accepts a result only
if it is authentic, fresh, bound to this session, unused, for a rostered
student, and does not override a manual correction.

Frame contents and embeddings are never handled or logged here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import logging
import time
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import settings
from app.database.attendance import upsert_attendance
from app.database.session_roster import get_session_roster
from app.schemas.attendance import AttendanceRecord

logger = logging.getLogger(__name__)

NONCE_COLLECTION = "recognition_nonces"
REQUIRED_FIELDS = (
    "session_id",
    "identity",
    "confidence",
    "issued_at",
    "expires_at",
    "nonce",
    "liveness",
    "signature",
)
# What the vision service attests about liveness: "passed" (checked and judged
# live) or "unchecked" (it is running in observe mode).
LIVENESS_PASSED = "passed"
LIVENESS_UNCHECKED = "unchecked"
LIVENESS_ATTESTATIONS = (LIVENESS_PASSED, LIVENESS_UNCHECKED)


class RecognitionRejected(Exception):
    """A recognition result failed verification. ``reason`` is a short machine-readable code."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class VerifiedRecognition:
    session_id: str
    identity: str
    confidence: float
    nonce: str
    expires_at: int
    liveness: str


@dataclass(frozen=True)
class MarkResult:
    """Outcome of one verify-and-mark attempt.

    status: marked | already_present | locked | rejected
    """

    status: str
    identity: Optional[str] = None
    reason: Optional[str] = None
    # For not_on_roster in a timetable class: why the student is not in it.
    detail: Optional[str] = None


def canonical_message(
    session_id: str,
    identity: str,
    confidence: float,
    issued_at: int,
    expires_at: int,
    nonce: str,
    liveness: str,
) -> bytes:
    """Byte string covered by the signature. Must match the vision service signer exactly."""
    return "|".join(
        [
            "v2",
            session_id,
            identity,
            f"{confidence:.4f}",
            str(issued_at),
            str(expires_at),
            nonce,
            liveness,
        ]
    ).encode("utf-8")


def compute_signature(
    key: str,
    session_id: str,
    identity: str,
    confidence: float,
    issued_at: int,
    expires_at: int,
    nonce: str,
    liveness: str,
) -> str:
    return hmac.new(
        key.encode("utf-8"),
        canonical_message(session_id, identity, confidence, issued_at, expires_at, nonce, liveness),
        hashlib.sha256,
    ).hexdigest()


def verify_recognition(
    token: Any,
    *,
    session_id: str,
    now: Optional[float] = None,
) -> VerifiedRecognition:
    """Check authenticity, freshness and session binding of a recognition result."""
    key = settings.RECOGNITION_SIGNING_KEY.strip()
    if not key:
        # Fail closed: without a key nothing can be verified, so nothing is accepted.
        raise RecognitionRejected("signing_key_not_configured")

    if not isinstance(token, dict) or any(token.get(f) in (None, "") for f in REQUIRED_FIELDS):
        raise RecognitionRejected("unsigned")

    try:
        token_session = str(token["session_id"])
        identity = str(token["identity"])
        confidence = float(token["confidence"])
        issued_at = int(token["issued_at"])
        expires_at = int(token["expires_at"])
        nonce = str(token["nonce"])
        liveness = str(token["liveness"])
        signature = str(token["signature"])
    except (TypeError, ValueError):
        raise RecognitionRejected("malformed")

    expected = compute_signature(
        key, token_session, identity, confidence, issued_at, expires_at, nonce, liveness
    )
    if not hmac.compare_digest(expected, signature):
        raise RecognitionRejected("bad_signature")

    # The attestation is covered by the signature, so it cannot be upgraded in
    # transit. In enforce mode only a face that passed liveness may be marked.
    if liveness not in LIVENESS_ATTESTATIONS:
        raise RecognitionRejected("malformed")
    if settings.LIVENESS_MODE == "enforce" and liveness != LIVENESS_PASSED:
        raise RecognitionRejected("liveness_not_passed")

    current = time.time() if now is None else now
    skew = settings.RECOGNITION_MAX_CLOCK_SKEW_SECONDS
    if current > expires_at:
        raise RecognitionRejected("expired")
    if issued_at > current + skew:
        raise RecognitionRejected("issued_in_future")
    if expires_at - issued_at > settings.RECOGNITION_MAX_TTL_SECONDS:
        raise RecognitionRejected("ttl_too_long")

    if token_session != session_id:
        raise RecognitionRejected("session_mismatch")

    return VerifiedRecognition(
        session_id=token_session,
        identity=identity,
        confidence=confidence,
        nonce=nonce,
        expires_at=expires_at,
        liveness=liveness,
    )


async def consume_nonce(db: AsyncIOMotorDatabase, verified: VerifiedRecognition) -> None:
    """Record the nonce as used; a second use of the same nonce is a replay."""
    result = await db[NONCE_COLLECTION].update_one(
        {"nonce": verified.nonce},
        {
            "$setOnInsert": {
                "nonce": verified.nonce,
                "session_id": verified.session_id,
                "expires_at": datetime.fromtimestamp(verified.expires_at, tz=timezone.utc),
            }
        },
        upsert=True,
    )
    if result.upserted_id is None:
        raise RecognitionRejected("replayed")


# (session, identity) -> when a "does not belong to this class" answer expires.
# A face that is not in the class is seen many times a minute; the database is
# asked again at most once a minute per face.
_NOT_IN_CLASS: dict[tuple[str, str], tuple[float, str]] = {}
_NOT_IN_CLASS_SECONDS = 60.0


async def _joined_late(db: AsyncIOMotorDatabase, session: dict, identity: str) -> Optional[str]:
    """None when a timetable class's student was approved after it started (now
    added); otherwise why they are not in the class (see teaching_service)."""
    if not session.get("slot_id"):
        return "not_on_list"
    key = (session["session_id"], identity)
    now = time.monotonic()
    cached = _NOT_IN_CLASS.get(key)
    if cached and cached[0] > now:
        return cached[1]
    from app.services import teaching_service

    if await teaching_service.add_late_student(db, session, identity):
        _NOT_IN_CLASS.pop(key, None)
        return None
    why = await teaching_service.why_not_in_class(db, session, identity)
    if len(_NOT_IN_CLASS) > 10_000:
        _NOT_IN_CLASS.clear()
    _NOT_IN_CLASS[key] = (now + _NOT_IN_CLASS_SECONDS, why)
    return why


async def verify_and_mark(
    db: AsyncIOMotorDatabase,
    session: dict,
    token: Any,
    *,
    now: Optional[float] = None,
) -> MarkResult:
    """The only code path that marks a student PRESENT from a recognition.

    Callers must already have established that ``session`` is ACTIVE and owned
    by the requesting teacher.
    """
    session_id = session["session_id"]

    try:
        verified = verify_recognition(token, session_id=session_id, now=now)
        await consume_nonce(db, verified)
    except RecognitionRejected as exc:
        logger.warning("Recognition result rejected for session %s: %s", session_id, exc.reason)
        return MarkResult(status="rejected", reason=exc.reason)

    identity = verified.identity

    roster = await get_session_roster(session_id)
    if roster is None or identity not in roster.identities:
        why = await _joined_late(db, session, identity)
        if why is not None:
            logger.warning(
                "Recognition for %s rejected in session %s: not on the roster (%s)",
                identity,
                session_id,
                why,
            )
            return MarkResult(
                status="rejected", identity=identity, reason="not_on_roster", detail=why
            )

    # A timetable session marks the round that is open (ENTRY or EXIT).
    if session.get("slot_id"):
        from app.services.rounds_service import mark_from_recognition

        profile = await db["student_profiles"].find_one({"identity": identity}) or {}
        outcome = await mark_from_recognition(db, session, identity, profile)
        if outcome == "no_round_open":
            return MarkResult(status="rejected", identity=identity, reason="no_round_open")
        if outcome == "locked":
            return MarkResult(status="locked", identity=identity, reason="manually_corrected")
        return MarkResult(status=outcome, identity=identity)

    existing = await db["attendance_records"].find_one(
        {"session_id": session_id, "identity": identity}
    )

    # Manual corrections win: recognition never overwrites a corrected record.
    if existing and existing.get("manually_corrected"):
        logger.warning(
            "Recognition for %s in session %s blocked: record is locked by a manual correction "
            "(current status %s)",
            identity,
            session_id,
            existing.get("status"),
        )
        return MarkResult(status="locked", identity=identity, reason="manually_corrected")

    if existing and existing.get("status") == "PRESENT":
        return MarkResult(status="already_present", identity=identity)

    profile = await db["student_profiles"].find_one({"identity": identity}) or {}
    await upsert_attendance(
        AttendanceRecord(
            attendance_id=f"att_{session_id}_{identity}",
            session_id=session_id,
            identity=identity,
            student_id=profile.get("student_id", identity),
            student_name=profile.get("name", identity),
            status="PRESENT",
            marked_at=datetime.now(timezone.utc),
        )
    )
    logger.info("Marked %s PRESENT in session %s from a verified recognition", identity, session_id)
    return MarkResult(status="marked", identity=identity)
