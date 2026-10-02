from datetime import datetime, timezone

import pytest

from app.database import mongodb
from app.database.attendance import (
    ATTENDANCE_COLLECTION,
    create_attendance,
    get_attendance_by_session,
)
from app.schemas.attendance import (
    AttendanceInterval,
    AttendanceRecord,
)


@pytest.mark.anyio
async def test_create_attendance():
    from mongomock_motor import AsyncMongoMockClient

    mongodb._client = AsyncMongoMockClient()

    record = AttendanceRecord(
        attendance_id="att_001",
        session_id="session_001",
        identity="person_01",
        presence_intervals=[
            AttendanceInterval(
                entry_time=datetime(
                    2026, 9, 29, 10, 0, tzinfo=timezone.utc
                ),
                exit_time=datetime(
                    2026, 9, 29, 10, 50, tzinfo=timezone.utc
                ),
            )
        ],
        presence_duration_seconds=3000,
        presence_percentage=83.33,
        required_presence_percentage=75.0,
        status="PRESENT",
    )

    result = await create_attendance(record)

    assert result["attendance_id"] == "att_001"
    assert result["session_id"] == "session_001"
    assert result["identity"] == "person_01"
    assert result["status"] == "PRESENT"

    db = mongodb.get_database()

    stored = await db[ATTENDANCE_COLLECTION].find_one(
        {"attendance_id": "att_001"}
    )

    assert stored is not None
    assert stored["identity"] == "person_01"
    assert stored["presence_duration_seconds"] == 3000
    assert stored["presence_percentage"] == 83.33
    assert stored["required_presence_percentage"] == 75.0
    assert stored["status"] == "PRESENT"
    assert "created_at" in stored


@pytest.mark.anyio
async def test_get_attendance_by_session():
    from mongomock_motor import AsyncMongoMockClient

    mongodb._client = AsyncMongoMockClient()

    record_1 = AttendanceRecord(
        attendance_id="att_001",
        session_id="session_001",
        identity="person_01",
        presence_intervals=[],
        presence_duration_seconds=3000,
        presence_percentage=83.33,
        required_presence_percentage=75.0,
        status="PRESENT",
    )

    record_2 = AttendanceRecord(
        attendance_id="att_002",
        session_id="session_001",
        identity="person_02",
        presence_intervals=[],
        presence_duration_seconds=1800,
        presence_percentage=50.0,
        required_presence_percentage=75.0,
        status="ABSENT",
    )

    record_3 = AttendanceRecord(
        attendance_id="att_003",
        session_id="session_002",
        identity="person_03",
        presence_intervals=[],
        presence_duration_seconds=3600,
        presence_percentage=100.0,
        required_presence_percentage=75.0,
        status="PRESENT",
    )

    await create_attendance(record_1)
    await create_attendance(record_2)
    await create_attendance(record_3)

    results = await get_attendance_by_session("session_001")

    assert len(results) == 2

    identities = {
        record["identity"]
        for record in results
    }

    assert identities == {
        "person_01",
        "person_02",
    }
