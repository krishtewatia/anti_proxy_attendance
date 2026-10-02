from datetime import datetime, timezone

import pytest

from app.database import mongodb
from app.database.sessions import create_session


@pytest.mark.anyio
async def test_create_session():
    # Use the existing mock database infrastructure.
    from mongomock_motor import AsyncMongoMockClient

    mongodb._client = AsyncMongoMockClient()

    session_data = {
        "course_name": "Data Structures",
        "classroom_id": "ROOM_101",
        "start_time": datetime(
            2026, 9, 29, 10, 0, tzinfo=timezone.utc
        ),
        "end_time": datetime(
            2026, 9, 29, 11, 0, tzinfo=timezone.utc
        ),
        "required_presence_percentage": 75.0,
    }

    from app.schemas.session import SessionCreate

    session = SessionCreate(**session_data)

    result = await create_session(session)

    assert result["session_id"].startswith("session_")
    assert result["course_name"] == "Data Structures"
    assert result["classroom_id"] == "ROOM_101"
    assert result["required_presence_percentage"] == 75.0
    assert result["status"] == "SCHEDULED"

    db = mongodb.get_database()

    stored = await db["sessions"].find_one(
        {"session_id": result["session_id"]}
    )

    assert stored is not None
    assert stored["course_name"] == "Data Structures"
