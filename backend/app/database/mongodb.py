"""MongoDB connection and database dependency management."""

from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings

_client: Optional[AsyncIOMotorClient] = None


def get_client() -> AsyncIOMotorClient:
    """Get or create singleton MongoDB client."""
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.MONGODB_URL)
    return _client


def close_client():
    """Close MongoDB client connection."""
    global _client
    if _client is not None:
        _client.close()
        _client = None


def get_database() -> AsyncIOMotorDatabase:
    """FastAPI dependency to retrieve the application database."""
    client = get_client()
    return client[settings.DATABASE_NAME]


async def init_indexes(db: AsyncIOMotorDatabase):
    """Ensure required database indexes are created."""
    # Enforce unique event_id for strict database-level idempotency
    await db[settings.EVENTS_COLLECTION].create_index(
        "event_id",
        unique=True,
        name="unique_event_id_idx",
    )
