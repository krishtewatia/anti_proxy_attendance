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

    session_end = datetime(
        2026, 9, 29, 11, 0, tzinfo=timezone.utc
    )

    events = [
        {
            "event_id": "evt_inside_01",
            "identity": "person_01",
            "direction": "ENTRY",
            "timestamp": session_start + timedelta(minutes=5),
        },
        {
            "event_id": "evt_inside_02",
            "identity": "person_01",
            "direction": "EXIT",
            "timestamp": session_start + timedelta(minutes=30),
        },
        {
            "event_id": "evt_before",
            "identity": "person_02",
            "direction": "ENTRY",
            "timestamp": session_start - timedelta(minutes=5),
        },
        {
            "event_id": "evt_after",
            "identity": "person_02",
            "direction": "EXIT",
            "timestamp": session_end + timedelta(minutes=5),
        },
    ]

    await collection.insert_many(events)

    results = await get_events_for_session(
        session_start,
        session_end,
    )

    event_ids = [event["event_id"] for event in results]

    assert event_ids == [
        "evt_inside_01",
        "evt_inside_02",
    ]
