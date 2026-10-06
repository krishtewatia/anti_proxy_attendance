"""HMAC-signed recognition results.

The vision service signs every confirmed recognition so the backend can
verify that a mark is backed by a real recognition for a specific session.
The backend holds the same key and re-computes the signature; the browser
never sees or supplies these results.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any, Optional

RECOGNITION_TTL_SECONDS = 30
SIGNING_KEY_MIN_LENGTH = 32
PLACEHOLDER_KEY_PREFIX = "replace_with"


def validate_signing_key(key: Optional[str], *, allow_insecure: bool = False) -> None:
    """Refuse to run without a real signing key.

    A missing, placeholder or short key must never reach a running service.
    ``allow_insecure`` is the explicit development/test override
    (ALLOW_INSECURE_RECOGNITION_KEY=true).
    """
    if allow_insecure:
        return
    if not key or not key.strip():
        raise RuntimeError(
            "RECOGNITION_SIGNING_KEY is not set. Generate one with "
            '`python -c "import secrets; print(secrets.token_hex(32))"` and set it for both '
            "the backend and the vision service."
        )
    cleaned = key.strip()
    if cleaned.lower().startswith(PLACEHOLDER_KEY_PREFIX):
        raise RuntimeError(
            "RECOGNITION_SIGNING_KEY is still the placeholder from .env.example. "
            "Replace it with a generated secret."
        )
    if len(cleaned) < SIGNING_KEY_MIN_LENGTH:
        raise RuntimeError(
            f"RECOGNITION_SIGNING_KEY must be at least {SIGNING_KEY_MIN_LENGTH} characters long "
            f"(found {len(cleaned)})."
        )


def canonical_message(
    session_id: str,
    identity: str,
    confidence: float,
    issued_at: int,
    expires_at: int,
    nonce: str,
) -> bytes:
    """Byte string covered by the signature. Must match the backend verifier exactly."""
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


def sign_recognition(
    *,
    session_id: str,
    identity: str,
    confidence: float,
    key: str,
    ttl_seconds: int = RECOGNITION_TTL_SECONDS,
    now: Optional[float] = None,
) -> dict[str, Any]:
    """Return a signed recognition result bound to one session and one identity."""
    if not key:
        raise ValueError("A signing key is required to sign recognition results")
    if not session_id or not identity:
        raise ValueError("session_id and identity are required to sign a recognition result")

    issued_at = int(now if now is not None else time.time())
    expires_at = issued_at + int(ttl_seconds)
    nonce = secrets.token_hex(16)
    confidence = round(float(confidence), 4)

    signature = hmac.new(
        key.encode("utf-8"),
        canonical_message(session_id, identity, confidence, issued_at, expires_at, nonce),
        hashlib.sha256,
    ).hexdigest()

    return {
        "session_id": session_id,
        "identity": identity,
        "confidence": confidence,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "nonce": nonce,
        "signature": signature,
    }
