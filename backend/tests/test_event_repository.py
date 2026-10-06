from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.core.config import settings
from app.database import mongodb
from app.database.events import get_events_for_session


@pytest.mark.anyio
async def test_get_events_for_session():
    mongodb._client = AsyncMongoMockClient()

    db = mongodb.get_database()
    collection = db[settings.EVENTS_COLLECTION]

    session_start = datetime(
        2026, 9, 29, 10, 0, tzinfo=timezone.utc
    )

    events = [
        {
            "event_id": "evt_inside_02",
            "session_id": "session_repo_001",
            "identity": "person_01",
            "direction": "EXIT",
            "timestamp": session_start + timedelta(minutes=30),
        },
        {
            "event_id": "evt_inside_01",
            "session_id": "session_repo_001",
            "identity": "person_01",
            "direction": "ENTRY",
            "timestamp": session_start + timedelta(minutes=5),
        },
        # Same time window, different session
        {
            "event_id": "evt_other_session",
            "session_id": "session_repo_002",
            "identity": "person_02",
            "direction": "ENTRY",
            "timestamp": session_start + timedelta(minutes=10),
        },
        # Same time window, no session: must never be attributed by timestamp
        {
            "event_id": "evt_unscoped",
            "session_id": None,
            "identity": "person_02",
            "direction": "EXIT",
            "timestamp": session_start + timedelta(minutes=20),
        },
    ]

    await collection.insert_many(events)

    results = await get_events_for_session("session_repo_001")

    event_ids = [event["event_id"] for event in results]

    # Only this session's events, oldest first
    assert event_ids == [
        "evt_inside_01",
        "evt_inside_02",
    ]

    assert await get_events_for_session("session_without_events") == []
