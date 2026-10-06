from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import settings
from app.database.mongodb import get_database


async def get_events_for_session(
    session_id: str,
    *,
    db: AsyncIOMotorDatabase | None = None,
) -> list[dict]:
    """Return the vision events that belong to one session, oldest first.

    Strictly scoped by ``session_id``. An event without a matching session_id
    is never attributed to a session by its timestamp, so concurrent or
    overlapping sessions cannot share events.
    """
    if not session_id:
        return []

    if db is None:
        db = get_database()

    cursor = db[settings.EVENTS_COLLECTION].find({"session_id": session_id}).sort("timestamp", 1)
    return await cursor.to_list(length=None)
