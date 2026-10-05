import logging
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database.sessions import find_active_session_in_db

logger = logging.getLogger(__name__)

# Pre-configured camera mappings for known doorways and cameras
DEFAULT_CAMERA_CLASSROOM_MAP: dict[str, str] = {
    "CAM_ROOM_101_DOOR": "ROOM_101",
    "CAM_ROOM_101": "ROOM_101",
    "cam_01": "ROOM_101",
    "cam_entrance": "ROOM_101",
    "PHONE_CAM_01": "ROOM_101",
    "phone_cam_01": "ROOM_101",
    "webcam_01": "ROOM_101",
    "cam_door_in": "ROOM_101",
    "cam_door_out": "ROOM_101",
}

# In-memory mutable registry
_CAMERA_REGISTRY: dict[str, str] = dict(DEFAULT_CAMERA_CLASSROOM_MAP)


def register_camera_classroom(camera_id: str, classroom_id: str) -> None:
    """Register or override a camera_id to classroom_id mapping."""
    _CAMERA_REGISTRY[camera_id] = classroom_id


def clear_camera_registry() -> None:
    """Reset the camera registry back to default mappings."""
    _CAMERA_REGISTRY.clear()
    _CAMERA_REGISTRY.update(DEFAULT_CAMERA_CLASSROOM_MAP)


def resolve_classroom_for_camera(camera_id: str) -> str:
    """
    Resolve a camera identifier to its physical classroom_id.

    1. Checks the camera registry for an explicit mapping.
    2. Falls back to convention:
       - Extracts classroom from CAM_<ROOM> or CAM_<ROOM>_<LOCATION>
       - If no prefix, returns camera_id as-is.
    """
    if not camera_id:
        return ""

    # 1. Exact match in registry
    if camera_id in _CAMERA_REGISTRY:
        return _CAMERA_REGISTRY[camera_id]

    # 2. Convention parsing for prefixes: CAM_ or CAM-
    upper = camera_id.upper()
    if upper.startswith("CAM_") or upper.startswith("CAM-"):
        candidate = camera_id[4:]
        # Strip common trailing location/doorway suffixes
        for suffix in (
            "_DOOR",
            "_ENTRANCE",
            "_EXIT",
            "_FRONT",
            "_BACK",
            "-DOOR",
            "-ENTRANCE",
            "-EXIT",
        ):
            if candidate.upper().endswith(suffix):
                candidate = candidate[: -len(suffix)]
                break

        if candidate:
            return candidate

    return camera_id


async def resolve_classroom_for_camera_db(
    camera_id: str,
    db: AsyncIOMotorDatabase | None = None,
) -> str:
    """
    Resolve camera to classroom, checking dynamic database first, then registry/convention.
    Caches dynamic results in _CAMERA_REGISTRY for fast subsequent lookups.
    """
    if not camera_id:
        return ""

    if db is not None:
        try:
            cam = await db["cameras"].find_one({"camera_id": camera_id}, {"classroom_id": 1})
            if cam and cam.get("classroom_id"):
                _CAMERA_REGISTRY[camera_id] = cam["classroom_id"]
                return cam["classroom_id"]
        except Exception as exc:
            logger.debug(
                "Database lookup for camera '%s' failed (%s), using registry/convention fallback",
                camera_id,
                exc,
            )

    return resolve_classroom_for_camera(camera_id)


async def find_active_session_for_classroom(
    classroom_id: str,
    timestamp: datetime,
    db: AsyncIOMotorDatabase | None = None,
) -> dict | None:
    """
    Find an active or scheduled attendance session for a classroom at the given timestamp.

    Returns the session document if start_time <= timestamp <= end_time, else None.
    """
    if not classroom_id:
        return None

    return await find_active_session_in_db(
        classroom_id=classroom_id,
        timestamp=timestamp,
        db=db,
    )
