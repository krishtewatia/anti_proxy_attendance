from datetime import datetime, timezone

import pytest

from app.database import mongodb
from app.database.attendance import ATTENDANCE_COLLECTION
from app.services.attendance_service import generate_attendance_record


@pytest.mark.anyio
async def test_generate_and_persist_attendance_record():
    from mongomock_motor import AsyncMongoMockClient

    mongodb._client = AsyncMongoMockClient()

    session_start = datetime(
        2026, 9, 29, 10, 0, tzinfo=timezone.utc
    )

    session_end = datetime(
        2026, 9, 29, 11, 0, tzinfo=timezone.utc
    )

    events = [
        {
            "event_id": "evt_entry_001",
            "identity": "person_01",
            "direction": "ENTRY",
            "timestamp": datetime(
                2026, 9, 29, 10, 0, tzinfo=timezone.utc
            ),
        },
        {
            "event_id": "evt_exit_001",
            "identity": "person_01",
            "direction": "EXIT",
            "timestamp": datetime(
                2026, 9, 29, 10, 50, tzinfo=timezone.utc
            ),
        },
    ]

    result = await generate_attendance_record(
        session_id="session_001",
        identity="person_01",
        events=events,
        session_start=session_start,
        session_end=session_end,
        required_presence_percentage=75.0,
    )

    assert result["session_id"] == "session_001"
    assert result["identity"] == "person_01"
    assert result["presence_duration_seconds"] == 50 * 60
    assert result["presence_percentage"] == (50 / 60) * 100
    assert result["status"] == "PRESENT"

    db = mongodb.get_database()

    stored = await db[ATTENDANCE_COLLECTION].find_one(
        {"attendance_id": result["attendance_id"]}
    )

    assert stored is not None
    assert stored["identity"] == "person_01"
    assert stored["status"] == "PRESENT"
    assert len(stored["presence_intervals"]) == 1
