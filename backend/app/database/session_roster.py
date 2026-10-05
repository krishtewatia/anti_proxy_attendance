from app.database.mongodb import get_database
from app.schemas.session_roster import SessionRoster

ROSTER_COLLECTION = "session_rosters"


async def create_session_roster(roster: SessionRoster) -> dict:
    db = get_database()
    collection = db[ROSTER_COLLECTION]

    document = roster.model_dump()

    await collection.update_one(
        {"session_id": roster.session_id},
        {"$set": document},
        upsert=True,
    )

    return await collection.find_one({"session_id": roster.session_id})


async def get_session_roster(session_id: str) -> SessionRoster | None:
    db = get_database()
    collection = db[ROSTER_COLLECTION]

    document = await collection.find_one({"session_id": session_id})

    if document is None:
        return None

    return SessionRoster(
        session_id=document["session_id"],
        identities=document["identities"],
    )
