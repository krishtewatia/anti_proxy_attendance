"""MongoDB database access layer for cameras collection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_database
from app.schemas.camera import CameraStatus, mask_rtsp_url


COLLECTION_NAME = "cameras"


def _format_camera_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """Convert raw Mongo document to public-facing camera representation with masked credentials."""
    raw_rtsp = doc.get("rtsp_url")
    formatted = dict(doc)
    formatted["rtsp_url_masked"] = mask_rtsp_url(raw_rtsp) if raw_rtsp else None
    # Exclude raw rtsp_url from the public dictionary
    formatted.pop("rtsp_url", None)
    return formatted


async def create_camera_in_db(
    camera_data: dict[str, Any],
    db: Optional[AsyncIOMotorDatabase] = None,
) -> dict[str, Any]:
    """Insert a new camera document into the cameras collection."""
    if db is None:
        db = get_database()

    now = datetime.now(timezone.utc)
    doc = {
        **camera_data,
        "status": camera_data.get("status", CameraStatus.UNKNOWN.value),
        "last_seen": None,
        "fps": None,
        "created_at": now,
        "updated_at": now,
    }

    await db[COLLECTION_NAME].insert_one(doc)
    created = await db[COLLECTION_NAME].find_one({"camera_id": camera_data["camera_id"]})
    return _format_camera_doc(created)


async def get_camera_from_db(
    camera_id: str,
    raw: bool = False,
    db: Optional[AsyncIOMotorDatabase] = None,
) -> Optional[dict[str, Any]]:
    """Retrieve camera by logical camera_id.

    If raw=True, returns the document with the raw rtsp_url for internal ingestion workers.
    Otherwise returns sanitized document with masked rtsp_url.
    """
    if db is None:
        db = get_database()

    doc = await db[COLLECTION_NAME].find_one({"camera_id": camera_id})
    if not doc:
        return None
    return doc if raw else _format_camera_doc(doc)


async def list_cameras_from_db(
    classroom_id: Optional[str] = None,
    enabled_only: bool = False,
    db: Optional[AsyncIOMotorDatabase] = None,
) -> list[dict[str, Any]]:
    """List cameras with optional filtering by classroom and enabled status."""
    if db is None:
        db = get_database()

    query: dict[str, Any] = {}
    if classroom_id:
        query["classroom_id"] = classroom_id
    if enabled_only:
        query["enabled"] = True

    cursor = db[COLLECTION_NAME].find(query).sort("camera_id", 1)
    docs = await cursor.to_list(length=1000)
    return [_format_camera_doc(d) for d in docs]


async def update_camera_in_db(
    camera_id: str,
    updates: dict[str, Any],
    db: Optional[AsyncIOMotorDatabase] = None,
) -> Optional[dict[str, Any]]:
    """Update fields of an existing camera record."""
    if db is None:
        db = get_database()

    cleaned = {k: v for k, v in updates.items() if v is not None}
    if not cleaned:
        doc = await get_camera_from_db(camera_id, raw=False, db=db)
        return doc

    cleaned["updated_at"] = datetime.now(timezone.utc)
    res = await db[COLLECTION_NAME].find_one_and_update(
        {"camera_id": camera_id},
        {"$set": cleaned},
        return_document=True,
    )
    if not res:
        return None
    return _format_camera_doc(res)


async def delete_camera_from_db(
    camera_id: str,
    db: Optional[AsyncIOMotorDatabase] = None,
) -> bool:
    """Delete a camera from the registry."""
    if db is None:
        db = get_database()

    result = await db[COLLECTION_NAME].delete_one({"camera_id": camera_id})
    return result.deleted_count > 0


async def record_camera_heartbeat_in_db(
    camera_id: str,
    state: str,
    fps: float,
    dropped_frames: int = 0,
    metadata: Optional[dict[str, Any]] = None,
    db: Optional[AsyncIOMotorDatabase] = None,
) -> Optional[dict[str, Any]]:
    """Update camera operational status and last_seen timestamp."""
    if db is None:
        db = get_database()

    now = datetime.now(timezone.utc)
    update_data: dict[str, Any] = {
        "status": state,
        "fps": fps,
        "last_seen": now,
        "updated_at": now,
    }
    if dropped_frames > 0:
        update_data["dropped_frames"] = dropped_frames
    if metadata:
        update_data["telemetry"] = metadata

    res = await db[COLLECTION_NAME].find_one_and_update(
        {"camera_id": camera_id},
        {"$set": update_data},
        return_document=True,
    )
    if not res:
        return None
    return _format_camera_doc(res)
