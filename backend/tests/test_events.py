from datetime import datetime, timezone

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
async def client(mock_db, register_test_camera):
    """Async test client with database dependency override and registered cameras."""
    app.dependency_overrides[get_database] = lambda: mock_db
    camera_headers = await register_test_camera("CAM_ROOM_101_DOOR", "ROOM_101", db=mock_db)
    await register_test_camera("CAM_LAB-3_DOOR", "LAB-3", db=mock_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers=camera_headers,
    ) as ac:
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


@pytest.mark.anyio
async def test_event_ingestion_matching_room_active_session_assigns_session_id(
    client, mock_db
):
    """Matching room and active session assigns session_id and classroom_id."""
    # 1. Insert an active session in ROOM_101
    start_time = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2026, 10, 20, 11, 30, 0, tzinfo=timezone.utc)

    await mock_db["sessions"].insert_one({
        "session_id": "session_operating_systems_101",
        "course_name": "Operating Systems",
        "classroom_id": "ROOM_101",
        "start_time": start_time,
        "end_time": end_time,
        "required_presence_percentage": 75.0,
        "status": "SCHEDULED",
        "created_by": "teacher_01",
    })

    # 2. Ingest event at 10:15 UTC (within session window) from camera at ROOM_101 door
    payload = {
        "event_id": "evt_match_active_01",
        "camera_id": "CAM_ROOM_101_DOOR",
        "track_id": 10,
        "identity": "person_01",
        "direction": "ENTRY",
        "timestamp": "2026-10-20T10:15:00Z",
        "evidence": {
            "peak_similarity": 0.85,
            "mean_similarity": 0.80,
            "supporting_frames": 10,
            "total_frames": 10,
            "consistency_pct": 100.0,
        },
    }

    response = await client.post("/api/v1/events", json=payload)
    assert response.status_code == 201

    # 3. Verify event document in DB has enriched fields
    doc = await mock_db[settings.EVENTS_COLLECTION].find_one(
        {"event_id": "evt_match_active_01"}
    )
    assert doc is not None
    assert doc["classroom_id"] == "ROOM_101"
    assert doc["session_id"] == "session_operating_systems_101"


@pytest.mark.anyio
async def test_event_ingestion_different_room_session_id_is_null(client, mock_db):
    """Event in a different room than active session gets session_id null."""
    # Session is in ROOM_101
    start_time = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2026, 10, 20, 11, 30, 0, tzinfo=timezone.utc)

    await mock_db["sessions"].insert_one({
        "session_id": "session_operating_systems_101",
        "course_name": "Operating Systems",
        "classroom_id": "ROOM_101",
        "start_time": start_time,
        "end_time": end_time,
        "required_presence_percentage": 75.0,
        "status": "SCHEDULED",
        "created_by": "teacher_01",
    })

    # Event is from LAB-3 camera at 10:15 UTC (no session in LAB-3)
    payload = {
        "event_id": "evt_diff_room_01",
        "camera_id": "CAM_LAB-3_DOOR",
        "track_id": 11,
        "identity": "person_01",
        "direction": "ENTRY",
        "timestamp": "2026-10-20T10:15:00Z",
        "evidence": {
            "peak_similarity": 0.82,
            "mean_similarity": 0.78,
            "supporting_frames": 8,
            "total_frames": 8,
            "consistency_pct": 100.0,
        },
    }

    response = await client.post("/api/v1/events", json=payload)
    assert response.status_code == 201

    doc = await mock_db[settings.EVENTS_COLLECTION].find_one(
        {"event_id": "evt_diff_room_01"}
    )
    assert doc is not None
    assert doc["classroom_id"] == "LAB-3"
    assert doc["session_id"] is None


@pytest.mark.anyio
async def test_event_ingestion_outside_session_window_session_id_is_null(
    client, mock_db
):
    """Event outside the session window in same classroom gets session_id null."""
    start_time = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2026, 10, 20, 11, 30, 0, tzinfo=timezone.utc)

    await mock_db["sessions"].insert_one({
        "session_id": "session_operating_systems_101",
        "course_name": "Operating Systems",
        "classroom_id": "ROOM_101",
        "start_time": start_time,
        "end_time": end_time,
        "required_presence_percentage": 75.0,
        "status": "SCHEDULED",
        "created_by": "teacher_01",
    })

    # Event is in ROOM_101, but at 09:30 UTC (30 minutes before class starts)
    payload = {
        "event_id": "evt_outside_window_01",
        "camera_id": "CAM_ROOM_101_DOOR",
        "track_id": 12,
        "identity": "person_01",
        "direction": "ENTRY",
        "timestamp": "2026-10-20T09:30:00Z",
        "evidence": {
            "peak_similarity": 0.88,
            "mean_similarity": 0.85,
            "supporting_frames": 9,
            "total_frames": 9,
            "consistency_pct": 100.0,
        },
    }

    response = await client.post("/api/v1/events", json=payload)
    assert response.status_code == 201

    doc = await mock_db[settings.EVENTS_COLLECTION].find_one(
        {"event_id": "evt_outside_window_01"}
    )
    assert doc is not None
    assert doc["classroom_id"] == "ROOM_101"
    assert doc["session_id"] is None


@pytest.mark.anyio
async def test_missing_or_wrong_camera_key_returns_401(client, mock_db):
    """With camera auth required, a missing or wrong X-API-Key is rejected and nothing is stored."""
    payload = {
        "event_id": "evt_unauthenticated_001",
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
    assert settings.REQUIRE_CAMERA_AUTH is True

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as anonymous:
        missing = await anonymous.post("/api/v1/events", json=payload)
        wrong = await anonymous.post(
            "/api/v1/events",
            json=payload,
            headers={"X-API-Key": "not-a-registered-camera-key"},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401

    count = await mock_db[settings.EVENTS_COLLECTION].count_documents({})
    assert count == 0

    # The same request with the registered camera key is accepted
    accepted = await client.post("/api/v1/events", json=payload)
    assert accepted.status_code == 201
