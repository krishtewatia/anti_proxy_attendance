from datetime import datetime, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.schemas.session_roster import SessionRoster
from app.services.session_finalization import finalize_session_attendance


@pytest.mark.anyio
async def test_student_with_no_vision_events_is_marked_absent():
    mongodb._client = AsyncMongoMockClient()
    session_start = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
    session_end = datetime(2026, 9, 23, 11, 0, tzinfo=timezone.utc)

    db = mongodb.get_database()

    await db["attendance_events"].delete_many({})
    await db["attendance_records"].delete_many({})

    # Only person_01 appears on camera.
    events = [
        {
            "event_id": "evt_present_entry",
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
            "event_id": "evt_present_exit",
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
        session_id="session_absent_test",
        identities=[
            "person_01",
            "person_02",
        ],
    )

    records = await finalize_session_attendance(
        session_id="session_absent_test",
        session_start=session_start,
        session_end=session_end,
        required_presence_percentage=75.0,
        roster=roster,
    )

    assert len(records) == 2

    records_by_identity = {
        record["identity"]: record
        for record in records
    }

    person_01 = records_by_identity["person_01"]
    person_02 = records_by_identity["person_02"]

    assert person_01["status"] == "PRESENT"
    assert person_01["presence_percentage"] == pytest.approx(
        83.3333,
        rel=1e-3,
    )

    assert person_02["presence_duration_seconds"] == 0
    assert person_02["presence_percentage"] == 0
    assert person_02["status"] == "ABSENT"
