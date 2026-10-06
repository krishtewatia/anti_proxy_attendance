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
    "signature",
)


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


@dataclass(frozen=True)
class MarkResult:
    """Outcome of one verify-and-mark attempt.

    status: marked | already_present | locked | rejected
    """

    status: str
    identity: Optional[str] = None
    reason: Optional[str] = None


def canonical_message(
    session_id: str,
    identity: str,
    confidence: float,
    issued_at: int,
    expires_at: int,
    nonce: str,
) -> bytes:
    """Byte string covered by the signature. Must match the vision service signer exactly."""
    return "|".join(
        [
            "v1",
            session_id,
            identity,
            f"{confidence:.4f}",
            str(issued_at),
            str(expires_at),
            nonce,
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
) -> str:
    return hmac.new(
        key.encode("utf-8"),
        canonical_message(session_id, identity, confidence, issued_at, expires_at, nonce),
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
        signature = str(token["signature"])
    except (TypeError, ValueError):
        raise RecognitionRejected("malformed")

    expected = compute_signature(
        key, token_session, identity, confidence, issued_at, expires_at, nonce
    )
    if not hmac.compare_digest(expected, signature):
        raise RecognitionRejected("bad_signature")

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
        logger.warning(
            "Recognition for %s rejected in session %s: not on the roster", identity, session_id
        )
        return MarkResult(status="rejected", identity=identity, reason="not_on_roster")

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
