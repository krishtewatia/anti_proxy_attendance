"""Tests for Step 2E.4: Backend reliability, idempotency, ordering, timestamps, and missing EXIT handling."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

from app.core.config import settings
from app.database import get_database, init_indexes
from app.main import app
from app.schemas.session_roster import SessionRoster
from app.services.presence_engine import (
    calculate_presence,
    calculate_session_presence,
    determine_attendance_status,
)
from app.services.session_finalization import finalize_session_attendance


@pytest.fixture
async def mock_db():
    client = AsyncMongoMockClient()
    db = client["test_reliability_db"]
    await init_indexes(db)
    return db


@pytest.fixture
async def client(mock_db, monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_CAMERA_AUTH", True)
    monkeypatch.setattr(settings, "VISION_SERVICE_API_KEY", "test-reliability-key-2026")
    monkeypatch.setattr(settings, "EVENT_TIMESTAMP_VALIDATION_ENABLED", True)
    monkeypatch.setattr(settings, "EVENT_MAX_FUTURE_SKEW_SECONDS", 300)
    monkeypatch.setattr(settings, "EVENT_MAX_PAST_AGE_SECONDS", 86400 * 30)

    app.dependency_overrides[get_database] = lambda: mock_db
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-API-Key": "test-reliability-key-2026"},
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


def make_test_event(
    event_id: str,
    timestamp: datetime,
    direction: str = "ENTRY",
    identity: str = "person_01",
    camera_id: str = "CAM_ROOM_101_DOOR",
) -> dict:
    return {
        "event_id": event_id,
        "camera_id": camera_id,
        "track_id": 10,
        "identity": identity,
        "direction": direction,
        "timestamp": timestamp.isoformat(),
        "evidence": {
            "peak_similarity": 0.88,
            "mean_similarity": 0.82,
            "supporting_frames": 4,
            "total_frames": 4,
            "consistency_pct": 100.0,
        },
    }


# ==============================================================================
# 1. Idempotency & Duplicate POST Tests (Task 2)
# ==============================================================================

@pytest.mark.anyio
async def test_duplicate_event_post_returns_200_duplicate(client, mock_db):
    """Confirm duplicate POST of the same event_id returns safe 200 duplicate, never 500."""
    now = datetime.now(timezone.utc)
    evt = make_test_event("evt_idem_001", now)

    # First POST -> 201 Created
    res1 = await client.post("/api/v1/events", json=evt)
    assert res1.status_code == 201
    assert res1.json()["status"] == "accepted"

    # Second duplicate POST -> 200 OK with duplicate status
    res2 = await client.post("/api/v1/events", json=evt)
    assert res2.status_code == 200
    assert res2.json()["status"] == "duplicate"
    assert "already processed" in res2.json()["message"]

    # Verify only 1 document exists in DB
    count = await mock_db[settings.EVENTS_COLLECTION].count_documents({"event_id": "evt_idem_001"})
    assert count == 1


# ==============================================================================
# 2. Timestamp Validation: Future Skew & Past Window (Task 3)
# ==============================================================================

@pytest.mark.anyio
async def test_future_timestamp_beyond_tolerance_rejected(client):
    """Timestamps too far in the future must be rejected with HTTP 422."""
    far_future = datetime.now(timezone.utc) + timedelta(minutes=15)
    evt = make_test_event("evt_future_001", far_future)

    res = await client.post("/api/v1/events", json=evt)
    assert res.status_code == 422
    assert "too far in the future" in res.json()["detail"]


@pytest.mark.anyio
async def test_reasonable_future_timestamp_within_tolerance_accepted(client):
    """Timestamps slightly ahead (within 300s clock skew tolerance) must be accepted."""
    slight_future = datetime.now(timezone.utc) + timedelta(seconds=30)
    evt = make_test_event("evt_future_ok_001", slight_future)

    res = await client.post("/api/v1/events", json=evt)
    assert res.status_code == 201
    assert res.json()["status"] == "accepted"


@pytest.mark.anyio
async def test_very_old_timestamp_beyond_window_rejected(client):
    """Timestamps older than max past age window (30 days) must be rejected with HTTP 422."""
    very_old = datetime.now(timezone.utc) - timedelta(days=45)
    evt = make_test_event("evt_old_001", very_old)

    res = await client.post("/api/v1/events", json=evt)
    assert res.status_code == 422
    assert "older than allowable window" in res.json()["detail"]


# ==============================================================================
# 3. Out-of-Order & Duplicate Direction Event Handling (Task 3 & 5)
# ==============================================================================

def test_out_of_order_events_sorted_correctly_in_interval_computation():
    """Events arriving in non-chronological order are sorted by event time."""
    t0 = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 10, 1, 10, 15, tzinfo=timezone.utc)
    t2 = datetime(2026, 10, 1, 10, 30, tzinfo=timezone.utc)
    t3 = datetime(2026, 10, 1, 10, 45, tzinfo=timezone.utc)

    # Shuffled input order: EXIT(t3), ENTRY(t0), EXIT(t1), ENTRY(t2)
    shuffled_events = [
        {"direction": "EXIT", "timestamp": t3},
        {"direction": "ENTRY", "timestamp": t0},
        {"direction": "EXIT", "timestamp": t1},
        {"direction": "ENTRY", "timestamp": t2},
    ]

    result = calculate_presence(shuffled_events)
    assert len(result.intervals) == 2
    assert result.intervals[0].entry_time == t0
    assert result.intervals[0].exit_time == t1
    assert result.intervals[1].entry_time == t2
    assert result.intervals[1].exit_time == t3
    assert result.total_presence_seconds == (15 * 60) + (15 * 60)


def test_duplicate_entry_after_vision_restart_does_not_corrupt_attendance():
    """A second ENTRY without an EXIT (e.g. after camera/vision restart) is ignored."""
    t0 = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 10, 1, 10, 5, tzinfo=timezone.utc)  # Duplicate ENTRY
    t2 = datetime(2026, 10, 1, 10, 30, tzinfo=timezone.utc)

    events = [
        {"direction": "ENTRY", "timestamp": t0},
        {"direction": "ENTRY", "timestamp": t1},
        {"direction": "EXIT", "timestamp": t2},
    ]

    result = calculate_presence(events)
    assert len(result.intervals) == 1
    assert result.intervals[0].entry_time == t0
    assert result.intervals[0].exit_time == t2
    assert result.total_presence_seconds == 30 * 60


def test_exit_without_entry_flagged_for_review():
    """An EXIT event with no prior ENTRY is ignored and flagged for review."""
    t0 = datetime(2026, 10, 1, 10, 20, tzinfo=timezone.utc)
    events = [{"direction": "EXIT", "timestamp": t0}]

    result = calculate_presence(events)
    assert len(result.intervals) == 0
    assert result.requires_review is True
    assert "EXIT_WITHOUT_ENTRY" in result.anomalies


# ==============================================================================
# 4. Missing EXIT Finalization & Review Flags (Task 4)
# ==============================================================================

def test_missing_exit_uncapped_flags_for_review():
    """When capping is disabled, missing exit yields 0 intervals and flags review."""
    t0 = datetime(2026, 10, 1, 10, 5, tzinfo=timezone.utc)
    events = [{"direction": "ENTRY", "timestamp": t0}]

    result = calculate_presence(events, cap_missing_exit=False)
    assert len(result.intervals) == 0
    assert result.total_presence_seconds == 0.0
    assert result.requires_review is True
    assert "MISSING_EXIT" in result.anomalies


def test_missing_exit_capped_at_session_end():
    """When capping is enabled, unclosed entry is capped at session_end and flagged."""
    s_start = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    s_end = datetime(2026, 10, 1, 11, 0, tzinfo=timezone.utc)
    t0 = datetime(2026, 10, 1, 10, 10, tzinfo=timezone.utc)

    events = [{"direction": "ENTRY", "timestamp": t0}]

    result = calculate_session_presence(events, s_start, s_end, cap_missing_exit=True)
    assert len(result.intervals) == 1
    assert result.intervals[0].entry_time == t0
    assert result.intervals[0].exit_time == s_end
    assert result.total_presence_seconds == 50 * 60
    assert result.requires_review is True
    assert "MISSING_EXIT" in result.anomalies


@pytest.mark.anyio
async def test_finalization_includes_review_flags_in_attendance(mock_db, monkeypatch):
    """Finalization stores requires_review and anomalies and makes them visible."""
    from app.database import mongodb
    client_mock = AsyncMongoMockClient()
    mongodb._client = client_mock
    db = mongodb.get_database()

    s_start = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    s_end = datetime(2026, 10, 1, 11, 0, tzinfo=timezone.utc)

    # Insert an event with ENTRY but no EXIT for person_01
    await db["attendance_events"].insert_one({
        "event_id": "evt_missing_exit_test",
        "session_id": "sess_review_test",
        "camera_id": "CAM_ROOM_101_DOOR",
        "track_id": 1,
        "identity": "person_01",
        "direction": "ENTRY",
        "timestamp": datetime(2026, 10, 1, 10, 5, tzinfo=timezone.utc),
        "evidence": {},
    })

    roster = SessionRoster(session_id="sess_review_test", identities=["person_01"])

    records = await finalize_session_attendance(
        session_id="sess_review_test",
        session_start=s_start,
        session_end=s_end,
        required_presence_percentage=50.0,
        roster=roster,
    )

    assert len(records) == 1
    rec = records[0]
    assert rec["identity"] == "person_01"
    assert rec["requires_review"] is True
    assert "MISSING_EXIT" in rec["anomalies"]


# ==============================================================================
# 5. MongoDB Down -> 503 Service Unavailable (Task 6)
# ==============================================================================

@pytest.mark.anyio
async def test_mongodb_down_returns_clear_503(client):
    """When MongoDB connection fails, /events returns clear HTTP 503 with Retry-After."""
    now = datetime.now(timezone.utc)
    evt = make_test_event("evt_mongo_down_001", now)

    # Override get_database dependency with broken database that raises ServerSelectionTimeoutError
    bad_db = AsyncMock()
    bad_coll = AsyncMock()
    bad_coll.find_one.side_effect = ServerSelectionTimeoutError("No replica set members found")
    bad_db.__getitem__.return_value = bad_coll

    app.dependency_overrides[get_database] = lambda: bad_db
    try:
        res = await client.post("/api/v1/events", json=evt)
        assert res.status_code == 503
        assert "Database service unavailable" in res.json()["detail"]
        assert res.headers.get("retry-after") == "2"
    finally:
        app.dependency_overrides.clear()
