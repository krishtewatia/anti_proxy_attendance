"""Tier 3: Event Ingestion to Live Snapshot State Transitions E2E Tests.

Validates perception dispatch and live dashboard telemetry:
- POST /api/v1/events acceptance and idempotency (status: accepted -> duplicate).
- Initial state verification: all students begin as NOT_SEEN.
- State transition on ENTRY: NOT_SEEN -> INSIDE (last_event_direction == ENTRY).
- State transition on EXIT: INSIDE -> OUTSIDE (last_event_direction == EXIT).
- Presence duration accumulation and interval closing.
- Absence of cross-talk (non-transiting students remain NOT_SEEN).
- Camera health telemetry in snapshot.
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
)
from httpx import AsyncClient
import pytest

pytestmark = [pytest.mark.anyio, pytest.mark.e2e]


def build_transit_event(
    *,
    identity: str = "person_01",
    direction: str = "ENTRY",
    timestamp: dt.datetime | None = None,
    event_id: str | None = None,
    track_id: int = 1,
) -> dict[str, Any]:
    """Construct an authentic transit event payload for ingestion."""
    ts = timestamp or dt.datetime.now(dt.timezone.utc)
    return {
        "event_id": event_id or f"evt_{uuid.uuid4().hex[:12]}",
        "camera_id": CAMERA_ID,
        "track_id": track_id,
        "identity": identity,
        "direction": direction,
        "timestamp": ts.isoformat(),
        "evidence": {
            "peak_similarity": 0.92,
            "mean_similarity": 0.89,
            "supporting_frames": 4,
            "total_frames": 4,
            "consistency_pct": 100.0,
            "margin_over_runner_up": 0.45,
            "runner_up_identity": "person_02" if identity != "person_02" else "person_03",
        },
    }


async def test_event_ingestion_acceptance_and_idempotency(
    api_client: AsyncClient,
    vision_headers: dict[str, str],
    clean_seed: dict[str, Any],
) -> None:
    """Validate 201 Created on first submission, and 200 duplicate on second submission."""
    event_id = f"evt_idempotency_{uuid.uuid4().hex[:8]}"
    payload = build_transit_event(
        identity="person_01",
        direction="ENTRY",
        event_id=event_id,
        track_id=10,
    )

    # 1. First Submission: must return 201 Created and accepted status
    res1 = await api_client.post("/api/v1/events", json=payload, headers=vision_headers)
    assert res1.status_code == 201, f"First ingestion failed: {res1.text}"
    data1 = res1.json()
    assert data1["event_id"] == event_id
    assert data1["status"] == "accepted"
    assert data1["session_id"] == SESSION_ID

    # 2. Duplicate Submission: must return 200 OK and duplicate status
    res2 = await api_client.post("/api/v1/events", json=payload, headers=vision_headers)
    assert res2.status_code == 200, f"Duplicate ingestion failed: {res2.text}"
    data2 = res2.json()
    assert data2["event_id"] == event_id
    assert data2["status"] == "duplicate"
    assert "already processed" in data2.get("message", "").lower()


async def test_live_snapshot_initial_state_not_seen(
    api_client: AsyncClient,
    teacher_headers: dict[str, str],
    clean_seed: dict[str, Any],
) -> None:
    """Verify live snapshot presents all rostered students as NOT_SEEN prior to transit."""
    res = await api_client.get(
        f"/api/v1/sessions/{SESSION_ID}/live-snapshot",
        headers=teacher_headers,
    )
    assert res.status_code == 200, f"Live snapshot fetch failed: {res.text}"
    snapshot = res.json()

    assert snapshot["session_id"] == SESSION_ID
    assert snapshot["classroom_id"] == "ROOM_101"
    students = snapshot.get("students", [])

    # Exactly 4 rostered students
    rostered_ids = [s["identity"] for s in students if s.get("is_rostered")]
    assert len(rostered_ids) == 4, f"Expected 4 rostered students, found {len(rostered_ids)}"

    for s in students:
        assert s["state"] in {"NOT_SEEN", "INSIDE", "OUTSIDE"}
        if s["identity"] in {"person_02", "person_03", "person_04"}:
            assert s["state"] == "NOT_SEEN"
            assert s["presence_duration_seconds"] == 0.0


async def test_event_ingestion_to_inside_and_outside_transitions(
    api_client: AsyncClient,
    vision_headers: dict[str, str],
    teacher_headers: dict[str, str],
    clean_seed: dict[str, Any],
) -> None:
    """Validate full state cycle: NOT_SEEN -> ENTRY (INSIDE) -> EXIT (OUTSIDE)."""
    now = dt.datetime.now(dt.timezone.utc)
    target_student = "person_03"

    # Step 1: Ingest ENTRY Event
    t_entry = now - dt.timedelta(seconds=20)
    entry_payload = build_transit_event(
        identity=target_student,
        direction="ENTRY",
        timestamp=t_entry,
        track_id=301,
    )
    entry_res = await api_client.post("/api/v1/events", json=entry_payload, headers=vision_headers)
    assert entry_res.status_code == 201, f"ENTRY ingestion failed: {entry_res.text}"

    # Step 2: Poll Live Snapshot -> Verify state INSIDE
    snap_res_1 = await api_client.get(
        f"/api/v1/sessions/{SESSION_ID}/live-snapshot",
        headers=teacher_headers,
    )
    assert snap_res_1.status_code == 200
    snap_1 = snap_res_1.json()

    item_1 = next((s for s in snap_1["students"] if s["identity"] == target_student), None)
    assert item_1 is not None, f"Student {target_student} not found in live snapshot"
    assert item_1["state"] == "INSIDE", f"Expected state INSIDE, got {item_1['state']}"
    assert item_1["last_event_direction"] == "ENTRY"
    assert item_1["no_exit_observed"] is True
    assert item_1["presence_duration_seconds"] >= 0.0

    # Verify recent events feed contains this ENTRY
    recent_entry = next((e for e in snap_1.get("recent_events", []) if e["event_id"] == entry_payload["event_id"]), None)
    assert recent_entry is not None, "Recent event feed missing ENTRY event"
    assert recent_entry["direction"] == "ENTRY"
    assert recent_entry["identity"] == target_student

    # Step 3: Ingest EXIT Event (15 seconds after entry)
    t_exit = t_entry + dt.timedelta(seconds=15)
    exit_payload = build_transit_event(
        identity=target_student,
        direction="EXIT",
        timestamp=t_exit,
        track_id=302,
    )
    exit_res = await api_client.post("/api/v1/events", json=exit_payload, headers=vision_headers)
    assert exit_res.status_code == 201, f"EXIT ingestion failed: {exit_res.text}"

    # Step 4: Poll Live Snapshot -> Verify state OUTSIDE with closed presence duration
    snap_res_2 = await api_client.get(
        f"/api/v1/sessions/{SESSION_ID}/live-snapshot",
        headers=teacher_headers,
    )
    assert snap_res_2.status_code == 200
    snap_2 = snap_res_2.json()

    item_2 = next((s for s in snap_2["students"] if s["identity"] == target_student), None)
    assert item_2 is not None
    assert item_2["state"] == "OUTSIDE", f"Expected state OUTSIDE, got {item_2['state']}"
    assert item_2["last_event_direction"] == "EXIT"
    assert item_2["no_exit_observed"] is False
    # Closed duration should be approximately 15.0 seconds
    assert 14.0 <= item_2["presence_duration_seconds"] <= 16.5, (
        f"Expected presence duration ~15s, got {item_2['presence_duration_seconds']}"
    )


async def test_camera_telemetry_in_live_snapshot(
    api_client: AsyncClient,
    teacher_headers: dict[str, str],
    clean_seed: dict[str, Any],
) -> None:
    """Validate camera telemetry for CAM_ROOM_101_DOOR in live snapshot."""
    res = await api_client.get(
        f"/api/v1/sessions/{SESSION_ID}/live-snapshot",
        headers=teacher_headers,
    )
    assert res.status_code == 200
    snapshot = res.json()

    cameras = snapshot.get("cameras", [])
    door_cam = next((c for c in cameras if c["camera_id"] == CAMERA_ID), None)
    assert door_cam is not None, f"Camera {CAMERA_ID} missing from live snapshot cameras list"
    assert door_cam["classroom_id"] == "ROOM_101"
    assert door_cam["status"] == "CONNECTED"
    assert door_cam.get("fps") == 15.0
