from datetime import datetime, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.schemas.session_roster import SessionRoster
from app.services.session_finalization import finalize_session_attendance


@pytest.mark.anyio
async def test_session_finalization_is_idempotent():
    mongodb._client = AsyncMongoMockClient()
    session_start = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
    session_end = datetime(2026, 9, 23, 11, 0, tzinfo=timezone.utc)

    db = mongodb.get_database()

    await db["attendance_events"].delete_many({})
    await db["attendance_records"].delete_many({})

    events = [
        {
            "event_id": "evt_idempotent_entry",
            "camera_id": "CAM_ROOM_101_DOOR",
            "track_id": 1,
            "identity": "person_01",
            "direction": "ENTRY",
            "timestamp": datetime(
                2026, 9, 23, 10, 5, tzinfo=timezone.utc
            ),
            "evidence": {},
        },
        {
            "event_id": "evt_idempotent_exit",
            "camera_id": "CAM_ROOM_101_DOOR",
            "track_id": 2,
            "identity": "person_01",
            "direction": "EXIT",
            "timestamp": datetime(
                2026, 9, 23, 10, 55, tzinfo=timezone.utc
            ),
            "evidence": {},
        },
    ]

    await db["attendance_events"].insert_many(events)

    roster = SessionRoster(
        session_id="session_idempotent",
        identities=["person_01"],
    )

    # First finalization
    first_result = await finalize_session_attendance(
        session_id="session_idempotent",
        session_start=session_start,
        session_end=session_end,
        required_presence_percentage=75.0,
        roster=roster,
    )

    assert len(first_result) == 1

    # Second finalization
    second_result = await finalize_session_attendance(
        session_id="session_idempotent",
        session_start=session_start,
        session_end=session_end,
        required_presence_percentage=75.0,
        roster=roster,
    )

    assert len(second_result) == 1

    # Only one attendance record should exist.
    records = await db["attendance_records"].find(
        {"session_id": "session_idempotent"}
    ).to_list(length=None)

    assert len(records) == 1

    record = records[0]

    assert record["identity"] == "person_01"
    assert record["presence_duration_seconds"] == 3000
    assert record["presence_percentage"] == pytest.approx(
        83.3333,
        rel=1e-3,
    )
    assert record["status"] == "PRESENT"
