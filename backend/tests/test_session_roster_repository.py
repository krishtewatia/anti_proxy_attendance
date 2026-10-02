import pytest
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.database.session_roster import (
    create_session_roster,
    get_session_roster,
)
from app.schemas.session_roster import SessionRoster


@pytest.mark.anyio
async def test_session_roster_repository():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()

    await db["session_rosters"].delete_many({})

    roster = SessionRoster(
        session_id="session_roster_001",
        identities=[
            "person_01",
            "person_02",
            "person_03",
        ],
    )

    created = await create_session_roster(roster)

    assert created["session_id"] == "session_roster_001"
    assert created["identities"] == [
        "person_01",
        "person_02",
        "person_03",
    ]

    retrieved = await get_session_roster(
        "session_roster_001"
    )

    assert retrieved is not None
    assert retrieved.session_id == "session_roster_001"
    assert retrieved.identities == [
        "person_01",
        "person_02",
        "person_03",
    ]
