"""The backend must refuse to start without a real recognition signing key."""

import secrets

import pytest

from app.core.config import settings
from app.main import app
from app.security.config import (
    is_insecure_recognition_key_allowed,
    validate_recognition_signing_key,
)

GOOD_KEY = secrets.token_hex(32)  # generated per run; no key material in the repo


@pytest.mark.parametrize(
    "key",
    [
        None,
        "",
        "   ",
        "replace_with_secure_random_recognition_signing_key_here",
        "replace_with_output_of_the_command_above",
        "REPLACE_WITH_anything_else_that_is_long_enough_to_pass_length",
        "too-short-key",
    ],
)
def test_missing_placeholder_or_short_key_is_refused(key):
    with pytest.raises(RuntimeError) as excinfo:
        validate_recognition_signing_key(key)
    assert "RECOGNITION_SIGNING_KEY" in str(excinfo.value)


def test_error_message_never_contains_the_key_value():
    with pytest.raises(RuntimeError) as excinfo:
        validate_recognition_signing_key("short-but-secret")
    assert "short-but-secret" not in str(excinfo.value)


def test_a_generated_key_is_accepted():
    validate_recognition_signing_key(GOOD_KEY)


def test_explicit_dev_override_skips_the_check():
    validate_recognition_signing_key(None, allow_insecure=True)
    validate_recognition_signing_key("replace_with_placeholder", allow_insecure=True)


@pytest.mark.parametrize(
    "value,expected",
    [("true", True), ("1", True), ("YES", True), ("false", False), ("", False), ("0", False)],
)
def test_dev_override_is_read_from_the_environment(monkeypatch, value, expected):
    monkeypatch.setenv("ALLOW_INSECURE_RECOGNITION_KEY", value)
    assert is_insecure_recognition_key_allowed() is expected


def test_dev_override_is_off_by_default(monkeypatch):
    monkeypatch.delenv("ALLOW_INSECURE_RECOGNITION_KEY", raising=False)
    assert is_insecure_recognition_key_allowed() is False


@pytest.mark.anyio
@pytest.mark.parametrize(
    "key", ["", "replace_with_secure_random_recognition_signing_key_here"]
)
async def test_application_startup_fails_without_a_real_key(monkeypatch, key):
    monkeypatch.delenv("ALLOW_INSECURE_RECOGNITION_KEY", raising=False)
    monkeypatch.setattr(settings, "RECOGNITION_SIGNING_KEY", key)

    with pytest.raises(RuntimeError) as excinfo:
        async with app.router.lifespan_context(app):
            pytest.fail("the application started without a real signing key")

    assert "RECOGNITION_SIGNING_KEY" in str(excinfo.value)


@pytest.mark.anyio
async def test_application_startup_succeeds_with_a_real_key(monkeypatch):
    monkeypatch.delenv("ALLOW_INSECURE_RECOGNITION_KEY", raising=False)
    monkeypatch.setattr(settings, "RECOGNITION_SIGNING_KEY", GOOD_KEY)
    monkeypatch.setattr(settings, "MONGODB_URL", "mock")

    started = False
    async with app.router.lifespan_context(app):
        started = True

    assert started


@pytest.mark.anyio
async def test_application_startup_with_the_explicit_dev_override(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_RECOGNITION_KEY", "true")
    monkeypatch.setattr(settings, "RECOGNITION_SIGNING_KEY", "")
    monkeypatch.setattr(settings, "MONGODB_URL", "mock")

    started = False
    async with app.router.lifespan_context(app):
        started = True

    assert started
