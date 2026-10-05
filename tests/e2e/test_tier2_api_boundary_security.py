"""Tier 2: API Boundary & Security Validation E2E Tests.

Validates defensive security boundaries:
- Rejection of missing/invalid camera API keys on POST /api/v1/events.
- Rejection of invalid direction types, empty identities, out-of-bounds similarity scores.
- Enforcement of payload size limits (413 Request Entity Too Large).
- Rejection of unauthenticated requests on GET /api/v1/sessions/{id}/live-snapshot.
- Role-based access control (403 Forbidden for Student tokens on teacher endpoints).
- Session ownership isolation (403 Forbidden when accessing unowned sessions).
- 404 Not Found handling for non-existent session IDs.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
import sys
from typing import Any
import uuid

# Ensure local test directory is importable
_E2E_DIR = Path(__file__).resolve().parent
if str(_E2E_DIR) not in sys.path:
    sys.path.insert(0, str(_E2E_DIR))

from conftest import (
    CAMERA_ID,
    SESSION_ID,
    VISION_SERVICE_API_KEY,
)
from httpx import AsyncClient
import pytest

pytestmark = [pytest.mark.anyio, pytest.mark.e2e]


def make_valid_event_payload(
    *,
    event_id: str | None = None,
    identity: str = "person_01",
    direction: str = "ENTRY",
) -> dict[str, Any]:
    """Helper to produce a structurally valid event payload."""
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    return {
        "event_id": event_id or f"evt_{uuid.uuid4().hex[:12]}",
        "camera_id": CAMERA_ID,
        "track_id": 101,
        "identity": identity,
        "direction": direction,
        "timestamp": now_iso,
        "evidence": {
            "peak_similarity": 0.88,
            "mean_similarity": 0.85,
            "supporting_frames": 3,
            "total_frames": 4,
            "consistency_pct": 75.0,
            "margin_over_runner_up": 0.35,
            "runner_up_identity": "person_02",
        },
    }


# ==============================================================================
# Event Ingestion Security & Schema Boundaries
# ==============================================================================


async def test_events_missing_api_key_rejected(api_client: AsyncClient, clean_seed: dict[str, Any]) -> None:
    """POST /api/v1/events without X-API-Key must return HTTP 401 Unauthorized."""
    payload = make_valid_event_payload()
    res = await api_client.post("/api/v1/events", json=payload)
    assert res.status_code == 401, f"Expected 401 Unauthorized, got {res.status_code}"
    assert "Missing camera API key" in res.json().get("detail", "")


async def test_events_invalid_api_key_rejected(api_client: AsyncClient, clean_seed: dict[str, Any]) -> None:
    """POST /api/v1/events with wrong X-API-Key must return HTTP 401 Unauthorized."""
    payload = make_valid_event_payload()
    headers = {"X-API-Key": "totally_fraudulent_camera_key_9999"}
    res = await api_client.post("/api/v1/events", json=payload, headers=headers)
    assert res.status_code == 401, f"Expected 401 Unauthorized, got {res.status_code}"


async def test_events_invalid_direction_rejected(
    api_client: AsyncClient,
    vision_headers: dict[str, str],
    clean_seed: dict[str, Any],
) -> None:
    """POST /api/v1/events with illegal direction must return HTTP 422 Unprocessable Entity."""
    payload = make_valid_event_payload(direction="SIDEWAYS")
    res = await api_client.post("/api/v1/events", json=payload, headers=vision_headers)
    assert res.status_code == 422, f"Expected 422 for invalid direction, got {res.status_code}"


async def test_events_empty_identity_rejected(
    api_client: AsyncClient,
    vision_headers: dict[str, str],
    clean_seed: dict[str, Any],
) -> None:
    """POST /api/v1/events with empty identity string must return HTTP 422 Unprocessable Entity."""
    payload = make_valid_event_payload(identity="")
    res = await api_client.post("/api/v1/events", json=payload, headers=vision_headers)
    assert res.status_code == 422, f"Expected 422 for empty identity, got {res.status_code}"


async def test_events_negative_track_id_rejected(
    api_client: AsyncClient,
    vision_headers: dict[str, str],
    clean_seed: dict[str, Any],
) -> None:
    """POST /api/v1/events with negative track_id must return HTTP 422."""
    payload = make_valid_event_payload()
    payload["track_id"] = -5
    res = await api_client.post("/api/v1/events", json=payload, headers=vision_headers)
    assert res.status_code == 422, f"Expected 422 for negative track_id, got {res.status_code}"


async def test_events_out_of_bounds_similarity_rejected(
    api_client: AsyncClient,
    vision_headers: dict[str, str],
    clean_seed: dict[str, Any],
) -> None:
    """POST /api/v1/events with peak_similarity > 1.0 must return HTTP 422."""
    payload = make_valid_event_payload()
    payload["evidence"]["peak_similarity"] = 1.85  # Boundary violation (> 1.0)
    res = await api_client.post("/api/v1/events", json=payload, headers=vision_headers)
    assert res.status_code == 422, f"Expected 422 for peak_similarity > 1.0, got {res.status_code}"

    # Also test consistency_pct > 100.0
    payload2 = make_valid_event_payload()
    payload2["evidence"]["consistency_pct"] = 150.0  # Boundary violation (> 100.0)
    res2 = await api_client.post("/api/v1/events", json=payload2, headers=vision_headers)
    assert res2.status_code == 422, f"Expected 422 for consistency_pct > 100.0, got {res2.status_code}"


async def test_events_excessive_payload_size_rejected(
    api_client: AsyncClient,
    vision_headers: dict[str, str],
    clean_seed: dict[str, Any],
) -> None:
    """POST /api/v1/events exceeding EVENTS_MAX_PAYLOAD_BYTES (64KB) must return HTTP 413."""
    payload = make_valid_event_payload()
    # Bloat runner_up_identity with 70KB of padding
    payload["evidence"]["runner_up_identity"] = "A" * (70 * 1024)
    res = await api_client.post("/api/v1/events", json=payload, headers=vision_headers)
    assert res.status_code == 413, f"Expected 413 Request Entity Too Large, got {res.status_code}"


# ==============================================================================
# Live Snapshot Security & Role Boundaries
# ==============================================================================


async def test_live_snapshot_unauthenticated_rejected(
    api_client: AsyncClient,
    clean_seed: dict[str, Any],
) -> None:
    """GET /api/v1/sessions/{id}/live-snapshot without Bearer token must return HTTP 401."""
    res = await api_client.get(f"/api/v1/sessions/{SESSION_ID}/live-snapshot")
    assert res.status_code == 401, f"Expected 401 Unauthorized without auth, got {res.status_code}"


async def test_live_snapshot_student_role_forbidden(
    api_client: AsyncClient,
    student_token: str,
    clean_seed: dict[str, Any],
) -> None:
    """GET /api/v1/sessions/{id}/live-snapshot with STUDENT token must return HTTP 403 Forbidden."""
    headers = {"Authorization": f"Bearer {student_token}"}
    res = await api_client.get(f"/api/v1/sessions/{SESSION_ID}/live-snapshot", headers=headers)
    assert res.status_code == 403, f"Expected 403 Forbidden for student, got {res.status_code}"


async def test_live_snapshot_nonexistent_session_not_found(
    api_client: AsyncClient,
    teacher_headers: dict[str, str],
    clean_seed: dict[str, Any],
) -> None:
    """GET /api/v1/sessions/sess_nonexistent_999/live-snapshot must return HTTP 404 Not Found."""
    fake_session_id = "sess_nonexistent_99999"
    res = await api_client.get(f"/api/v1/sessions/{fake_session_id}/live-snapshot", headers=teacher_headers)
    assert res.status_code == 404, f"Expected 404 Not Found, got {res.status_code}"


async def test_live_snapshot_unowned_session_forbidden(
    api_client: AsyncClient,
    mongo_db,
    teacher_headers: dict[str, str],
    clean_seed: dict[str, Any],
) -> None:
    """GET /api/v1/sessions/{id}/live-snapshot for session owned by another teacher returns HTTP 403."""
    # Create an unowned session in MongoDB
    other_session_id = f"sess_foreign_{uuid.uuid4().hex[:8]}"
    now = dt.datetime.now(dt.timezone.utc)
    mongo_db.sessions.insert_one({
        "session_id": other_session_id,
        "course_name": "CS-999 Advanced Quantum Computing",
        "classroom_id": "ROOM_999",
        "created_by": "user_another_teacher_different_uuid",
        "start_time": now - dt.timedelta(hours=1),
        "end_time": now + dt.timedelta(hours=1),
        "required_presence_percentage": 75.0,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
    })

    try:
        res = await api_client.get(
            f"/api/v1/sessions/{other_session_id}/live-snapshot",
            headers=teacher_headers,
        )
        assert res.status_code == 403, f"Expected 403 Forbidden for unowned session, got {res.status_code}"
    finally:
        mongo_db.sessions.delete_one({"session_id": other_session_id})
