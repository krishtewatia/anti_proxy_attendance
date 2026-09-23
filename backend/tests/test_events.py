"""Integration and unit tests for Event Ingestion API (Step 3.2)."""

import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.core.config import settings
from app.database import get_database, init_indexes
from app.main import app


@pytest.fixture
async def mock_db():
    """Create isolated in-memory MongoDB instance for testing."""
    client = AsyncMongoMockClient()
    db = client["test_anti_proxy_db"]
    await init_indexes(db)
    return db


@pytest.fixture
async def client(mock_db):
    """Async test client with database dependency override."""
    app.dependency_overrides[get_database] = lambda: mock_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_valid_entry_event_accepted_and_persisted(client, mock_db):
    payload = {
        "event_id": "evt_entry_001",
        "camera_id": "CAM_ROOM_101_DOOR",
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

    response = await client.post("/api/v1/events", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["event_id"] == "evt_entry_001"
    assert data["status"] == "accepted"

    # Verify document in database
    doc = await mock_db[settings.EVENTS_COLLECTION].find_one({"event_id": "evt_entry_001"})
    assert doc is not None
    assert doc["camera_id"] == "CAM_ROOM_101_DOOR"
    assert doc["track_id"] == 22
    assert doc["identity"] == "person_02"
    assert doc["direction"] == "ENTRY"
    assert doc["evidence"]["peak_similarity"] == 0.613
    assert doc["created_at"] is not None


@pytest.mark.anyio
async def test_valid_exit_event_accepted(client, mock_db):
    payload = {
        "event_id": "evt_exit_001",
        "camera_id": "CAM_ROOM_101_DOOR",
        "track_id": 45,
        "identity": "person_02",
        "direction": "EXIT",
        "timestamp": "2026-09-23T15:15:42.110Z",
        "evidence": {
            "peak_similarity": 0.640,
            "mean_similarity": 0.602,
            "supporting_frames": 6,
            "total_frames": 6,
            "consistency_pct": 100.0,
            "margin_over_runner_up": 0.490,
            "runner_up_identity": "person_01",
        },
    }

    response = await client.post("/api/v1/events", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["event_id"] == "evt_exit_001"
    assert data["status"] == "accepted"

    doc = await mock_db[settings.EVENTS_COLLECTION].find_one({"event_id": "evt_exit_001"})
    assert doc is not None
    assert doc["direction"] == "EXIT"


@pytest.mark.anyio
async def test_unresolved_event_accepted(client, mock_db):
    payload = {
        "event_id": "evt_unresolved_001",
        "camera_id": "CAM_ROOM_101_DOOR",
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

    response = await client.post("/api/v1/events", json=payload)
    assert response.status_code == 201
    assert response.json()["status"] == "accepted"


@pytest.mark.anyio
async def test_duplicate_event_id_is_idempotent(client, mock_db):
    payload = {
        "event_id": "evt_duplicate_test_101",
        "camera_id": "CAM_ROOM_101_DOOR",
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
        },
    }

    # First send -> 201 accepted
    res1 = await client.post("/api/v1/events", json=payload)
    assert res1.status_code == 201
    assert res1.json()["status"] == "accepted"

    # Second send -> 200 duplicate (idempotent)
    res2 = await client.post("/api/v1/events", json=payload)
    assert res2.status_code == 200
    assert res2.json()["event_id"] == "evt_duplicate_test_101"
    assert res2.json()["status"] == "duplicate"

    # Third send -> still duplicate
    res3 = await client.post("/api/v1/events", json=payload)
    assert res3.status_code == 200
    assert res3.json()["status"] == "duplicate"

    # Verify exactly ONE document exists in MongoDB
    count = await mock_db[settings.EVENTS_COLLECTION].count_documents(
        {"event_id": "evt_duplicate_test_101"}
    )
    assert count == 1


@pytest.mark.anyio
async def test_invalid_payload_returns_422(client, mock_db):
    # Missing required field 'direction' and 'evidence'
    payload = {
        "event_id": "evt_bad_001",
        "camera_id": "CAM_ROOM_101_DOOR",
        "track_id": 22,
        "identity": "person_02",
        "timestamp": "2026-09-23T14:30:15.820Z",
    }

    response = await client.post("/api/v1/events", json=payload)
    assert response.status_code == 422

    count = await mock_db[settings.EVENTS_COLLECTION].count_documents({})
    assert count == 0


@pytest.mark.anyio
async def test_forbidden_backend_fields_rejected(client, mock_db):
    # Vision service sending forbidden backend business logic field
    payload = {
        "event_id": "evt_forbidden_001",
        "camera_id": "CAM_ROOM_101_DOOR",
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

    response = await client.post("/api/v1/events", json=payload)
    assert response.status_code == 422

    count = await mock_db[settings.EVENTS_COLLECTION].count_documents({})
    assert count == 0
