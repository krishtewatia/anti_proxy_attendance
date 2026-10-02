import pytest

from app.security.passwords import hash_password, verify_password


def test_hash_password_generates_valid_bcrypt_hash():
    password = "supersecretpassword123"
    hashed = hash_password(password)

    assert isinstance(hashed, str)
    assert hashed.startswith("$2b$")
    assert hashed != password


def test_hash_password_uses_unique_salts():
    password = "supersecretpassword123"
    hash_1 = hash_password(password)
    hash_2 = hash_password(password)

    assert hash_1 != hash_2
    assert verify_password(password, hash_1) is True
    assert verify_password(password, hash_2) is True


def test_verify_password_success():
    password = "ValidPassword456!"
    hashed = hash_password(password)

    assert verify_password(password, hashed) is True


def test_verify_password_failure():
    password = "ValidPassword456!"
    hashed = hash_password(password)

    assert verify_password("WrongPassword123!", hashed) is False
    assert verify_password("", hashed) is False


def test_verify_password_handles_malformed_hash_gracefully():
    assert verify_password("any_password", "invalid_hash_string") is False
    assert verify_password("any_password", "") is False


def test_password_hashing_with_unicode():
    password = "pässwörd_🔑_123"
    hashed = hash_password(password)

    assert verify_password(password, hashed) is True
    assert verify_password("pässwörd_🔒_123", hashed) is False
