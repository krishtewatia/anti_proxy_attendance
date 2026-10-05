"""MongoDB connection and database dependency management."""

from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings

import asyncio

_client: Optional[AsyncIOMotorClient] = None


def get_client() -> AsyncIOMotorClient:
    """Get or create singleton MongoDB client with event-loop awareness."""
    global _client
    if _client is not None:
        try:
            current_loop = asyncio.get_running_loop()
            client_loop = getattr(_client, "io_loop", None)
            if client_loop is not None and (client_loop.is_closed() or client_loop != current_loop):
                _client.close()
                _client = None
        except RuntimeError:
            pass

    if _client is None:
        if (
            settings.MONGODB_URL.startswith("mongomock://")
            or settings.MONGODB_URL == "mock"
            or settings.MONGODB_URL == ""
        ):
            from mongomock_motor import AsyncMongoMockClient

            _client = AsyncMongoMockClient()
        else:
            _client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=1000)
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
    # Enforce unique email on users collection
    await db["users"].create_index(
        [("email", 1)],
        unique=True,
        name="uq_users_email",
    )
    # Enforce unique user_id and identity on student_profiles collection
    await db["student_profiles"].create_index(
        [("user_id", 1)],
        unique=True,
        name="uq_student_profiles_user_id",
    )
    await db["student_profiles"].create_index(
        [("identity", 1)],
        unique=True,
        name="uq_student_profiles_identity",
    )
    # Enforce unique audit_id and compound chronological history on audit_events
    await db["audit_events"].create_index(
        "audit_id",
        unique=True,
        name="uq_audit_id",
    )
    await db["audit_events"].create_index(
        [("resource_type", 1), ("resource_id", 1), ("timestamp", 1)],
        name="idx_audit_resource_history",
    )
    # Enforce unique camera_id on cameras collection
    await db["cameras"].create_index(
        [("camera_id", 1)],
        unique=True,
        name="uq_cameras_camera_id",
    )
