from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database.mongodb import get_database

AUDIT_EVENTS_COLLECTION = "audit_events"


async def ensure_audit_indexes(db: AsyncIOMotorDatabase | None = None) -> None:
    """Ensure indexes on the audit_events collection."""
    if db is None:
        db = get_database()
    collection = db[AUDIT_EVENTS_COLLECTION]
    await collection.create_index(
        "audit_id",
        unique=True,
        name="uq_audit_id",
    )
    await collection.create_index(
        [("resource_type", 1), ("resource_id", 1), ("timestamp", 1)],
        name="idx_audit_resource_history",
    )


async def create_audit_event(event: dict, db: AsyncIOMotorDatabase | None = None) -> dict:
    """
    Append an immutable audit event record to MongoDB.

    This collection is strictly append-only for audit integrity.
    """
    if db is None:
        db = get_database()
    collection = db[AUDIT_EVENTS_COLLECTION]

    await ensure_audit_indexes(db)

    document = dict(event)
    await collection.insert_one(document)
    return document


async def get_audit_event(audit_id: str) -> dict | None:
    """
    Retrieve a single audit event by its unique audit_id.
    """
    db = get_database()
    collection = db[AUDIT_EVENTS_COLLECTION]

    return await collection.find_one({"audit_id": audit_id})


async def get_audit_events(
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> list[dict]:
    """
    Retrieve audit events, optionally filtered by resource_type and/or resource_id,
    ordered chronologically (timestamp ASC).
    """
    db = get_database()
    collection = db[AUDIT_EVENTS_COLLECTION]

    query: dict[str, Any] = {}
    if resource_type is not None:
        query["resource_type"] = resource_type
    if resource_id is not None:
        query["resource_id"] = resource_id

    cursor = collection.find(query).sort("timestamp", 1)
    return await cursor.to_list(length=None)
