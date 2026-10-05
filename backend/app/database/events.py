from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import settings
from app.database.mongodb import get_database


async def get_events_for_session(
    session_id: str | datetime | None = None,
    session_start: datetime | None = None,
    session_end: datetime | None = None,
    *,
    db: AsyncIOMotorDatabase | None = None,
) -> list[dict]:
    """
    Retrieve vision events associated with a session.

    If session_id is provided:
        - Retrieves events with matching session_id.
        - Falls back to session_start/session_end window if no enriched events exist
          in the collection (maintaining backwards compatibility with legacy tests).
    If session_start and session_end are provided (or passed positionally):
        - Retrieves events strictly within the session timestamp window.
    """
    if db is None:
        db = get_database()
    collection = db[settings.EVENTS_COLLECTION]

    # Handle backwards-compatible positional call: get_events_for_session(session_start, session_end)
    if isinstance(session_id, datetime):
        session_end = session_start
        session_start = session_id
        session_id = None

    if session_id:
        cursor = collection.find({"session_id": session_id}).sort("timestamp", 1)
        session_events = await cursor.to_list(length=None)
        if session_events:
            return session_events

        # If any events in the collection have a non-null session_id,
        # it means session enrichment is active in the environment,
        # so returning [] for this session_id is the accurate result.
        any_enriched = await collection.find_one({"session_id": {"$ne": None}})
        if any_enriched is not None:
            return []

    # Fallback to session_start and session_end timestamp window
    if session_start is not None and session_end is not None:
        cursor = collection.find(
            {
                "timestamp": {
                    "$gte": session_start,
                    "$lte": session_end,
                }
            }
        ).sort("timestamp", 1)
        return await cursor.to_list(length=None)

    return []
