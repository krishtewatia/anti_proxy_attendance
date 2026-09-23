"""Unit tests for Vision Service -> FastAPI event contract schema."""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from app.schemas.vision_event import (
    DirectionType,
    VisionEvidence,
    VisionEventCreate,
)


def test_valid_entry_event():
    payload = {
        "event_id": "evt_12345",
        "camera_id": "CAM_ROOM_101",
        "track_id": 22,
        "identity": "person_02",
        "direction": "ENTRY",
        "timestamp": "2026-09-23T14:30:15.820Z",
        "evidence": {
            "peak_similarity": 0.613,
            "mean_similarity": 0.585,
            "supporting_frames": 5,
            "total_frames": 5,
            "consistency_pct": 100.0,
            "margin_over_runner_up": 0.461,
            "runner_up_identity": "person_03",
        },
    }

    event = VisionEventCreate(**payload)
    assert event.event_id == "evt_12345"
    assert event.direction == DirectionType.ENTRY
    assert event.evidence.peak_similarity == 0.613
    assert event.evidence.consistency_pct == 100.0


def test_valid_unresolved_event():
    payload = {
        "event_id": "evt_99999",
        "camera_id": "CAM_ROOM_101",
        "track_id": 3,
        "identity": "UNKNOWN",
        "direction": "UNRESOLVED",
        "timestamp": "2026-09-23T14:32:00.000Z",
        "evidence": {
            "peak_similarity": 0.250,
            "mean_similarity": 0.250,
            "supporting_frames": 1,
            "total_frames": 1,
            "consistency_pct": 100.0,
        },
    }

    event = VisionEventCreate(**payload)
    assert event.direction == DirectionType.UNRESOLVED
    assert event.identity == "UNKNOWN"
    assert event.evidence.margin_over_runner_up is None


def test_invalid_direction():
    payload = {
        "event_id": "evt_12345",
        "camera_id": "CAM_ROOM_101",
        "track_id": 22,
        "identity": "person_02",
        "direction": "INSIDE",  # Invalid enum value
        "timestamp": "2026-09-23T14:30:15.820Z",
        "evidence": {
            "peak_similarity": 0.613,
            "mean_similarity": 0.585,
            "supporting_frames": 5,
            "total_frames": 5,
            "consistency_pct": 100.0,
        },
    }

    with pytest.raises(ValidationError):
        VisionEventCreate(**payload)


def test_forbidden_extra_fields():
    # Vision service must not send backend-specific fields like attendance_status or session_id
    payload = {
        "event_id": "evt_12345",
        "camera_id": "CAM_ROOM_101",
        "track_id": 22,
        "identity": "person_02",
        "direction": "ENTRY",
        "timestamp": "2026-09-23T14:30:15.820Z",
        "attendance_status": "PRESENT",  # FORBIDDEN
        "evidence": {
            "peak_similarity": 0.613,
            "mean_similarity": 0.585,
            "supporting_frames": 5,
            "total_frames": 5,
            "consistency_pct": 100.0,
        },
    }

    with pytest.raises(ValidationError):
        VisionEventCreate(**payload)
