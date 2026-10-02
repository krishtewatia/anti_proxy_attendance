from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database.mongodb import get_database
from app.schemas.session import SessionCreate


SESSIONS_COLLECTION = "sessions"



async def create_session(
    session: SessionCreate,
    created_by: str = "system",
) -> dict:
    """Create and persist a new attendance session."""

    db = get_database()
    collection = db[SESSIONS_COLLECTION]

    session_id = f"session_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"

    session_document = {
        "session_id": session_id,
        "course_name": session.course_name,
        "classroom_id": session.classroom_id,
        "start_time": session.start_time,
        "end_time": session.end_time,
        "required_presence_percentage": session.required_presence_percentage,
        "status": "SCHEDULED",
        "created_by": created_by,
        "created_at": datetime.now(timezone.utc),
    }

    await collection.insert_one(session_document)

    return session_document


async def get_session(session_id: str) -> dict | None:
    db = get_database()
    collection = db[SESSIONS_COLLECTION]

    return await collection.find_one(
        {"session_id": session_id}
    )


async def get_sessions_by_owner(created_by: str) -> list[dict]:
    """Retrieve all attendance sessions created by a specific owner/teacher."""
    db = get_database()
    collection = db[SESSIONS_COLLECTION]

    cursor = collection.find({"created_by": created_by}).sort("created_at", -1)
    return await cursor.to_list(length=None)


async def find_active_session_in_db(
    classroom_id: str,
    timestamp: datetime,
    db: AsyncIOMotorDatabase | None = None,
) -> dict | None:
    """Query MongoDB for an attendance session in classroom active at timestamp."""
    if db is None:
        db = get_database()
    collection = db[SESSIONS_COLLECTION]

    ts_aware = (
        timestamp
        if timestamp.tzinfo is not None
        else timestamp.replace(tzinfo=timezone.utc)
    )
    ts_naive = ts_aware.replace(tzinfo=None)

    # 1. Attempt query using tz-aware timestamp
    try:
        session = await collection.find_one(
            {
                "classroom_id": classroom_id,
                "start_time": {"$lte": ts_aware},
                "end_time": {"$gte": ts_aware},
            },
            sort=[("start_time", 1)],
        )
        if session is not None:
            return session
    except TypeError:
        pass

    # 2. Fallback query using tz-naive timestamp (for mongomock or naive datetime docs)
    try:
        session = await collection.find_one(
            {
                "classroom_id": classroom_id,
                "start_time": {"$lte": ts_naive},
                "end_time": {"$gte": ts_naive},
            },
            sort=[("start_time", 1)],
        )
        if session is not None:
            return session
    except TypeError:
        pass

    return None
