"""Comprehensive tests for service-to-service authentication and security baseline (Step 2E.3)."""

from datetime import datetime, timezone
import json
import logging
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.api.dependencies.camera_auth import (
    CameraAuthContext,
    _hash_key,
    require_camera_auth,
    validate_camera_binding,
)
from app.api.dependencies.rate_limiter import SlidingWindowRateLimiter, events_rate_limiter
from app.core.config import settings
from app.core.logging_security import SensitiveDataFilter
from app.database import get_database, init_indexes
from app.main import app
from app.security.config import validate_jwt_secret_strength


@pytest.fixture
async def mock_db():
    client = AsyncMongoMockClient()
    db = client["test_service_auth_db"]
    await init_indexes(db)
    return db


@pytest.fixture
async def sec_client(mock_db, monkeypatch):
    """Test client with isolated mock database and controlled environment settings."""
    app.dependency_overrides[get_database] = lambda: mock_db
    events_rate_limiter.reset()

    # Configure test master key and per-camera bound keys
    monkeypatch.setattr(settings, "REQUIRE_CAMERA_AUTH", True)
    monkeypatch.setattr(settings, "VISION_SERVICE_API_KEY", "master-secret-key-123")
    monkeypatch.setattr(settings, "VISION_SERVICE_API_KEY_HASH", "")
    monkeypatch.setattr(
        settings,
        "VISION_CAMERA_KEYS",
        json.dumps({
            "CAM_ROOM_101_DOOR": "room101-specific-key-456",
            "CAM_LAB_3": "lab3-specific-key-789",
        }),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()
    events_rate_limiter.reset()


def make_event(event_id="evt_sec_001", camera_id="CAM_ROOM_101_DOOR"):
    return {
        "event_id": event_id,
        "camera_id": camera_id,
        "track_id": 1,
        "identity": "person_01",
        "direction": "ENTRY",
        "timestamp": "2026-10-20T10:05:00Z",
        "evidence": {
            "peak_similarity": 0.85,
            "mean_similarity": 0.80,
            "supporting_frames": 5,
            "total_frames": 5,
            "consistency_pct": 100.0,
        },
    }


# ==============================================================================
# 1. API Key Authentication Tests
# ==============================================================================

@pytest.mark.anyio
async def test_missing_api_key_returns_401(sec_client, mock_db):
    """Missing API key header returns HTTP 401 and logs a security audit entry."""
    resp = await sec_client.post("/api/v1/events", json=make_event("evt_missing_key"))
    assert resp.status_code == 401
    assert "Missing camera API key" in resp.json()["detail"]

    # Verify security audit event recorded in audit_events collection
    audit = await mock_db["audit_events"].find_one({"action": "SERVICE_AUTH_FAILED"})
    assert audit is not None
    assert audit["resource_type"] == "SECURITY"
    assert audit["metadata"]["reason"] == "missing_api_key"
    assert "master-secret-key-123" not in str(audit)


@pytest.mark.anyio
async def test_invalid_api_key_returns_401(sec_client, mock_db):
    """Invalid API key returns HTTP 401 and records audit failure without leaking secrets."""
    resp = await sec_client.post(
        "/api/v1/events",
        json=make_event("evt_invalid_key"),
        headers={"X-API-Key": "wrong-secret-key-xyz"},
    )
    assert resp.status_code == 401
    assert "Invalid camera API key" in resp.json()["detail"]

    audit = await mock_db["audit_events"].find_one({
        "action": "SERVICE_AUTH_FAILED",
        "metadata.reason": "invalid_api_key",
    })
    assert audit is not None
    # Crucial security guarantee: raw submitted secret must NOT appear in audit
    assert "wrong-secret-key-xyz" not in json.dumps(audit, default=str)


@pytest.mark.anyio
async def test_valid_master_key_accepted(sec_client, mock_db):
    """Valid master API key in X-API-Key header is accepted."""
    resp = await sec_client.post(
        "/api/v1/events",
        json=make_event("evt_valid_master"),
        headers={"X-API-Key": "master-secret-key-123"},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "accepted"


@pytest.mark.anyio
async def test_x_vision_api_key_header_accepted(sec_client, mock_db):
    """Alternative X-Vision-API-Key header is accepted."""
    resp = await sec_client.post(
        "/api/v1/events",
        json=make_event("evt_alt_header"),
        headers={"X-Vision-API-Key": "master-secret-key-123"},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "accepted"


# ==============================================================================
# 2. Camera-Bound Key Tests
# ==============================================================================

@pytest.mark.anyio
async def test_camera_bound_key_accepted_on_allowed_camera(sec_client, mock_db):
    """Camera-bound key is accepted when camera_id matches."""
    resp = await sec_client.post(
        "/api/v1/events",
        json=make_event("evt_bound_ok", camera_id="CAM_ROOM_101_DOOR"),
        headers={"X-API-Key": "room101-specific-key-456"},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "accepted"


@pytest.mark.anyio
async def test_camera_bound_key_rejected_on_wrong_camera(sec_client, mock_db):
    """Camera-bound key is rejected with HTTP 403 when camera_id does not match binding."""
    resp = await sec_client.post(
        "/api/v1/events",
        json=make_event("evt_bound_forbidden", camera_id="CAM_ROOM_102_DOOR"),
        headers={"X-API-Key": "room101-specific-key-456"},
    )
    assert resp.status_code == 403
    assert "not authorized for camera" in resp.json()["detail"]

    # Security audit event verified
    audit = await mock_db["audit_events"].find_one({
        "action": "SERVICE_AUTH_FAILED",
        "metadata.reason": "camera_binding_mismatch",
    })
    assert audit is not None
    assert audit["resource_id"] == "CAM_ROOM_102_DOOR"


# ==============================================================================
# 3. Ingestion Hardening: Payload Size Limit & Rate Limiting
# ==============================================================================

@pytest.mark.anyio
async def test_payload_size_limit_exceeded_returns_413(sec_client, monkeypatch):
    """Payloads exceeding maximum size are rejected with HTTP 413 Payload Too Large."""
    monkeypatch.setattr(settings, "EVENTS_MAX_PAYLOAD_BYTES", 500)

    oversized_event = make_event("evt_oversized")
    # Add dummy long padding to exceed 500 bytes
    oversized_event["evidence"]["extra_padding"] = "X" * 1000

    resp = await sec_client.post(
        "/api/v1/events",
        json=oversized_event,
        headers={"X-API-Key": "master-secret-key-123"},
    )
    assert resp.status_code == 413
    assert "exceeds maximum allowed limit" in resp.json()["detail"]


@pytest.mark.anyio
async def test_rate_limiter_exceeded_returns_429(sec_client, monkeypatch):
    """Rate limit per minute triggers HTTP 429 when threshold exceeded."""
    # Set limit to 3 requests per minute for testing
    monkeypatch.setattr(settings, "EVENTS_RATE_LIMIT_PER_MINUTE", 3)
    events_rate_limiter.reset()

    headers = {"X-API-Key": "master-secret-key-123"}

    # Requests 1, 2, 3 should succeed
    for i in range(3):
        r = await sec_client.post(
            "/api/v1/events",
            json=make_event(f"evt_rate_{i}"),
            headers=headers,
        )
        assert r.status_code in (200, 201)

    # 4th request must be rate-limited
    r4 = await sec_client.post(
        "/api/v1/events",
        json=make_event("evt_rate_overflow"),
        headers=headers,
    )
    assert r4.status_code == 429
    assert "Rate limit exceeded" in r4.json()["detail"]


# ==============================================================================
# 4. CORS Baseline Tests
# ==============================================================================

@pytest.mark.anyio
async def test_cors_explicit_origins_allowed_with_credentials(sec_client):
    """CORS allows configured explicit origins."""
    headers = {
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET",
    }
    resp = await sec_client.options("/health", headers=headers)
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert resp.headers.get("access-control-allow-credentials") == "true"


@pytest.mark.anyio
async def test_cors_arbitrary_unwhitelisted_origin_denied(sec_client):
    """CORS denies arbitrary, un-whitelisted origins."""
    headers = {
        "Origin": "http://malicious-site.com",
        "Access-Control-Request-Method": "GET",
    }
    resp = await sec_client.options("/health", headers=headers)
    assert resp.headers.get("access-control-allow-origin") is None


# ==============================================================================
# 5. ADMIN Registration Prohibited
# ==============================================================================

@pytest.mark.anyio
async def test_admin_role_cannot_be_publicly_registered(sec_client):
    """Public registration with role ADMIN must return HTTP 422 Unprocessable Entity."""
    payload = {
        "email": "hacker.admin@domain.com",
        "password": "Password123456!",
        "role": "ADMIN",
    }
    resp = await sec_client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 422


# ==============================================================================
# 6. JWT Secret Strength Validation
# ==============================================================================

def test_jwt_secret_strength_validation():
    """Verify validate_jwt_secret_strength rejects short or default secrets."""
    # 1. Missing or None
    with pytest.raises(RuntimeError, match="not set"):
        validate_jwt_secret_strength(None)

    with pytest.raises(RuntimeError, match="not set"):
        validate_jwt_secret_strength("   ")

    # 2. Short secret (< 32 chars)
    with pytest.raises(RuntimeError, match="at least 32 characters"):
        validate_jwt_secret_strength("short_secret_key_12345")

    # 3. Known weak defaults
    with pytest.raises(RuntimeError, match="insecure, commonly guessed"):
        validate_jwt_secret_strength("password")

    with pytest.raises(RuntimeError, match="insecure, commonly guessed"):
        validate_jwt_secret_strength("12345678901234567890123456789012")

    # 4. Valid strong secret passes
    validate_jwt_secret_strength("cTQHLa5mmvBKkjI0yYIBvS0BOrBf_ZVjO6Uq5Us_IUWQASgxY4Hsw8mBmiHSjvo5")


# ==============================================================================
# 7. Log Scrubbing Filter Tests
# ==============================================================================

def test_sensitive_data_filter_scrubs_secrets_and_biometrics():
    """Verify SensitiveDataFilter redacts tokens, API keys, passwords, embeddings, and images."""
    f = SensitiveDataFilter()

    # 1. Bearer Token scrubbing
    text1 = "User authenticated with Bearer eyJhbGciOiJIUzI1NiJ9.test.sig successfully"
    scrubbed1 = f.scrub_sensitive_text(text1)
    assert "Bearer [REDACTED]" in scrubbed1
    assert "eyJhbGciOiJIUzI1NiJ9" not in scrubbed1

    # 2. API Key scrubbing
    text2 = "Request sent with x-api-key: my_super_secret_api_key_456"
    scrubbed2 = f.scrub_sensitive_text(text2)
    assert "[REDACTED]" in scrubbed2
    assert "my_super_secret_api_key_456" not in scrubbed2

    # 3. Password scrubbing
    text3 = 'User created with "password": "SecretPassword123!"'
    scrubbed3 = f.scrub_sensitive_text(text3)
    assert "[REDACTED]" in scrubbed3
    assert "SecretPassword123!" not in scrubbed3

    # 4. Long ArcFace Embedding vector scrubbing
    embedding_str = str([0.123456 + i * 0.01 for i in range(128)])
    text4 = f"Extracted facial features: {embedding_str}"
    scrubbed4 = f.scrub_sensitive_text(text4)
    assert "[EMBEDDING_VECTOR_REDACTED]" in scrubbed4

    # 5. Base64 image data scrubbing
    text5 = "Image buffer: data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD...=="
    scrubbed5 = f.scrub_sensitive_text(text5)
    assert "[BASE64_IMAGE_REDACTED]" in scrubbed5
