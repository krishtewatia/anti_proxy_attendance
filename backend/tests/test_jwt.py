from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.security.config import JWT_ALGORITHM, JWT_SECRET_KEY
from app.security.jwt import create_access_token, decode_access_token


def test_create_access_token():
    token = create_access_token(user_id="user_123", role="TEACHER")

    assert isinstance(token, str)
    assert len(token) > 0


def test_decode_access_token_claims():
    token = create_access_token(user_id="user_123", role="TEACHER")
    claims = decode_access_token(token)

    assert claims["sub"] == "user_123"
    assert claims["role"] == "TEACHER"
    assert "iat" in claims
    assert "exp" in claims
    assert claims["exp"] > claims["iat"]


def test_tampered_token_fails_decoding():
    token = create_access_token(user_id="user_123", role="TEACHER")

    # Modify the signature part of the JWT
    parts = token.split(".")
    tampered_signature = parts[2][:-4] + "abcd" if len(parts[2]) > 4 else "abcd"
    tampered_token = f"{parts[0]}.{parts[1]}.{tampered_signature}"

    with pytest.raises(jwt.PyJWTError):
        decode_access_token(tampered_token)


def test_expired_token_is_rejected():
    # Construct an expired token directly using an expiration in the past
    past_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    expired_payload = {
        "sub": "user_expired",
        "role": "STUDENT",
        "iat": past_time - timedelta(minutes=60),
        "exp": past_time,
    }
    expired_token = jwt.encode(
        expired_payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired_token)
