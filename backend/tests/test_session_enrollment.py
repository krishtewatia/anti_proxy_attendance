import pytest
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.services.session_enrollment import (
    enroll_session_roster,
    get_enrolled_roster,
)


@pytest.mark.anyio
async def test_session_enrollment_service():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()

    await db["session_rosters"].delete_many({})

    roster = await enroll_session_roster(
        session_id="session_enrollment_001",
        identities=[
            "person_01",
            "person_02",
            "person_03",
        ],
    )

    assert roster.session_id == "session_enrollment_001"
    assert roster.identities == [
        "person_01",
        "person_02",
        "person_03",
    ]

    retrieved = await get_enrolled_roster(
        "session_enrollment_001"
    )

    assert retrieved is not None
    assert retrieved.session_id == "session_enrollment_001"
    assert retrieved.identities == [
        "person_01",
        "person_02",
        "person_03",
    ]
