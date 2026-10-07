"""Signed recognition results produced by the vision service."""

import hashlib
import hmac
from pathlib import Path
import sys

import pytest

SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from camera.recognition_signing import (  # noqa: E402
    RECOGNITION_TTL_SECONDS,
    canonical_message,
    sign_recognition,
)

KEY = "vision-signing-test-key"


def _expected_signature(token: dict, key: str = KEY) -> str:
    message = canonical_message(
        token["session_id"],
        token["identity"],
        token["confidence"],
        token["issued_at"],
        token["expires_at"],
        token["nonce"],
    )
    return hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def test_signature_matches_the_shared_test_vector():
    """The same vector is asserted in backend/tests/test_secure_frame_marking.py."""
    message = canonical_message(
        "sess_vector_1",
        "student1",
        0.9123,
        1790000000,
        1790000030,
        "0123456789abcdef0123456789abcdef",
    )
    signature = hmac.new(b"shared-test-vector-key", message, hashlib.sha256).hexdigest()
    assert signature == "f7c62bfa88f268a5dc4513f9c588139877106aa1c35b615a427d37d24796cfbe"


def test_signed_result_contains_session_identity_confidence_and_short_expiry():
    token = sign_recognition(
        session_id="sess_1", identity="student1", confidence=0.87654321, key=KEY, now=1790000000
    )

    assert token["session_id"] == "sess_1"
    assert token["identity"] == "student1"
    assert token["confidence"] == 0.8765
    assert token["issued_at"] == 1790000000
    assert token["expires_at"] == 1790000000 + RECOGNITION_TTL_SECONDS
    assert RECOGNITION_TTL_SECONDS == 30
    assert len(token["nonce"]) == 32
    assert token["signature"] == _expected_signature(token)


def test_every_result_has_a_fresh_nonce_and_signature():
    first = sign_recognition(session_id="sess_1", identity="student1", confidence=0.9, key=KEY)
    second = sign_recognition(session_id="sess_1", identity="student1", confidence=0.9, key=KEY)

    assert first["nonce"] != second["nonce"]
    assert first["signature"] != second["signature"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_id", "sess_other"),
        ("identity", "student2"),
        ("confidence", 0.99),
        ("issued_at", 1790000001),
        ("expires_at", 1790009999),
        ("nonce", "f" * 32),
    ],
)
def test_changing_any_signed_field_invalidates_the_signature(field, value):
    token = sign_recognition(
        session_id="sess_1", identity="student1", confidence=0.9, key=KEY, now=1790000000
    )
    tampered = {**token, field: value}

    assert _expected_signature(tampered) != token["signature"]


def test_signature_depends_on_the_key():
    token = sign_recognition(
        session_id="sess_1", identity="student1", confidence=0.9, key=KEY, now=1790000000
    )
    assert _expected_signature(token, key="a-different-key") != token["signature"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"session_id": "sess_1", "identity": "student1", "confidence": 0.9, "key": ""},
        {"session_id": "", "identity": "student1", "confidence": 0.9, "key": KEY},
        {"session_id": "sess_1", "identity": "", "confidence": 0.9, "key": KEY},
    ],
)
def test_signing_requires_a_key_a_session_and_an_identity(kwargs):
    with pytest.raises(ValueError):
        sign_recognition(**kwargs)


# ------------------------------------------------------------------------------
# The service must refuse to run without a real signing key
# ------------------------------------------------------------------------------

import secrets  # noqa: E402

from camera.recognition_signing import validate_signing_key  # noqa: E402

GOOD_KEY = secrets.token_hex(32)  # generated per run; no key material in the repo


@pytest.mark.parametrize(
    "key",
    [
        None,
        "",
        "   ",
        "replace_with_secure_random_recognition_signing_key_here",
        "replace_with_output_of_the_command_above",
        "too-short-key",
    ],
)
def test_missing_placeholder_or_short_key_is_refused(key):
    with pytest.raises(RuntimeError) as excinfo:
        validate_signing_key(key)
    assert "RECOGNITION_SIGNING_KEY" in str(excinfo.value)


def test_generated_key_is_accepted_and_dev_override_skips_the_check():
    validate_signing_key(GOOD_KEY)
    validate_signing_key(None, allow_insecure=True)


@pytest.mark.parametrize(
    "key", [None, "replace_with_secure_random_recognition_signing_key_here"]
)
def test_runner_exits_before_serving_when_the_key_is_not_real(key):
    """run_vision_service.py must stop at startup, with a clear message and exit code 1."""
    import os
    import subprocess

    env = {k: v for k, v in os.environ.items() if k not in {
        "RECOGNITION_SIGNING_KEY", "ALLOW_INSECURE_RECOGNITION_KEY"
    }}
    if key is not None:
        env["RECOGNITION_SIGNING_KEY"] = key

    proc = subprocess.run(
        [sys.executable, "run_vision_service.py", "--port", "0"],
        cwd=str(SERVICE_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert proc.returncode == 1
    assert "RECOGNITION_SIGNING_KEY" in proc.stderr
    assert "listening" not in (proc.stdout + proc.stderr).lower()
