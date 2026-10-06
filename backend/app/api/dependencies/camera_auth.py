"""Service-to-service and camera authentication dependency."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from typing import Optional, Set

from fastapi import Depends, Header, HTTPException, Request, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import settings
from app.database import get_database
from app.services.audit_service import record_audit_event

logger = logging.getLogger(__name__)


class CameraAuthContext:
    """Authentication context representing an authenticated camera or vision service."""

    def __init__(
        self,
        service_id: str,
        allowed_cameras: Optional[Set[str]] = None,
    ):
        self.service_id = service_id
        self.allowed_cameras = allowed_cameras  # None indicates master access (all cameras)

    def is_camera_allowed(self, camera_id: str) -> bool:
        if self.allowed_cameras is None:
            return True
        return camera_id in self.allowed_cameras


def _hash_key(key: str) -> str:
    """Compute SHA-256 hex digest of a raw API key."""
    return hashlib.sha256(key.strip().encode("utf-8")).hexdigest()


def _key_fingerprint(key: str) -> str:
    """Short, non-reversible identifier for a presented key. Raw keys are never logged."""
    return _hash_key(key)[:8]


def _get_configured_camera_keys() -> dict[str, str]:
    """Parse configured per-camera keys into camera_id -> sha256_hash mapping."""
    raw = settings.VISION_CAMERA_KEYS.strip()
    if not raw:
        return {}

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            mapping = {}
            for cam_id, key_val in data.items():
                # If key looks like a 64-char sha256 hex, store as is, otherwise hash it
                if len(key_val) == 64 and all(c in "0123456789abcdefABCDEF" for c in key_val):
                    mapping[str(cam_id)] = key_val.lower()
                else:
                    mapping[str(cam_id)] = _hash_key(str(key_val))
            return mapping
    except json.JSONDecodeError:
        pass

    # Fallback to comma-separated format: "CAM_101:key1,CAM_102:key2"
    mapping = {}
    for pair in raw.split(","):
        if ":" in pair:
            cam_id, key_val = pair.split(":", 1)
            cam_id = cam_id.strip()
            key_val = key_val.strip()
            if cam_id and key_val:
                mapping[cam_id] = _hash_key(key_val)
    return mapping


async def require_camera_auth(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    x_vision_api_key: Optional[str] = Header(None, alias="X-Vision-API-Key"),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> CameraAuthContext:
    """Authenticate incoming perception requests via API key header.

    Fail-closed policy: If REQUIRE_CAMERA_AUTH is enabled, missing or invalid
    credentials result in HTTP 401 Unauthorized and a security audit entry.
    """
    if not settings.REQUIRE_CAMERA_AUTH:
        # Development override only
        return CameraAuthContext(service_id="dev-bypass", allowed_cameras=None)

    api_key = x_api_key or x_vision_api_key
    client_ip = request.client.host if request.client else "unknown"

    if not api_key:
        logger.warning(
            "Camera authentication failed: no auth header (client_ip=%s, path=%s)",
            client_ip,
            request.url.path,
        )
        try:
            await record_audit_event(
                actor_user_id="anonymous",
                actor_role="SYSTEM",
                action="SERVICE_AUTH_FAILED",
                resource_type="SECURITY",
                resource_id="unknown_camera",
                metadata={"reason": "missing_api_key", "client_ip": client_ip},
                db=db,
            )
        except Exception as exc:
            logger.error("Failed to write security audit event: %s", exc)

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing camera API key in header ('X-API-Key')",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    incoming_hash = _hash_key(api_key)

    # 1. Check master Vision Service key / hash
    master_key = settings.VISION_SERVICE_API_KEY.strip()
    master_hash = settings.VISION_SERVICE_API_KEY_HASH.strip().lower()

    if master_key and secrets.compare_digest(incoming_hash, _hash_key(master_key)):
        return CameraAuthContext(service_id="vision-service", allowed_cameras=None)

    if master_hash and secrets.compare_digest(incoming_hash, master_hash):
        return CameraAuthContext(service_id="vision-service", allowed_cameras=None)

    # 2. Check per-camera bound keys
    camera_key_map = _get_configured_camera_keys()
    matched_cameras: Set[str] = set()

    for cam_id, stored_hash in camera_key_map.items():
        if secrets.compare_digest(incoming_hash, stored_hash):
            matched_cameras.add(cam_id)

    if matched_cameras:
        return CameraAuthContext(
            service_id=f"camera-agent-{','.join(sorted(matched_cameras))}",
            allowed_cameras=matched_cameras,
        )

    # Authentication failed: no matching key or hash
    logger.warning(
        "Camera authentication failed: auth header not recognized "
        "(fingerprint=%s, client_ip=%s, path=%s)",
        _key_fingerprint(api_key),
        client_ip,
        request.url.path,
    )
    try:
        await record_audit_event(
            actor_user_id="anonymous",
            actor_role="SYSTEM",
            action="SERVICE_AUTH_FAILED",
            resource_type="SECURITY",
            resource_id="unknown_camera",
            metadata={"reason": "invalid_api_key", "client_ip": client_ip},
            db=db,
        )
    except Exception as exc:
        logger.error("Failed to write security audit event: %s", exc)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid camera API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )


async def validate_camera_binding(
    auth_context: CameraAuthContext,
    camera_id: str,
    client_ip: str = "unknown",
    db: AsyncIOMotorDatabase | None = None,
) -> None:
    """Verify that an authenticated credential is authorized for the given camera_id."""
    if not auth_context.is_camera_allowed(camera_id):
        logger.warning(
            "Camera authorization rejected: key not allowed for camera_id=%s (service_id=%s, client_ip=%s)",
            camera_id,
            auth_context.service_id,
            client_ip,
        )
        try:
            await record_audit_event(
                actor_user_id="anonymous",
                actor_role="SYSTEM",
                action="SERVICE_AUTH_FAILED",
                resource_type="SECURITY",
                resource_id=camera_id,
                metadata={
                    "reason": "camera_binding_mismatch",
                    "camera_id": camera_id,
                    "service_id": auth_context.service_id,
                    "client_ip": client_ip,
                },
                db=db,
            )
        except Exception as exc:
            logger.error("Failed to write security audit event: %s", exc)

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"API key is not authorized for camera '{camera_id}'",
        )


async def require_service_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> None:
    """Require the vision service master key. Always enforced.

    Used for internal service-to-service routes (such as the biometric
    gallery) that must never be reachable without the shared key, regardless
    of the REQUIRE_CAMERA_AUTH development switch.
    """
    master_key = settings.VISION_SERVICE_API_KEY.strip()
    master_hash = settings.VISION_SERVICE_API_KEY_HASH.strip().lower()

    if x_api_key and (master_key or master_hash):
        incoming_hash = _hash_key(x_api_key)
        if master_key and secrets.compare_digest(incoming_hash, _hash_key(master_key)):
            return None
        if master_hash and secrets.compare_digest(incoming_hash, master_hash):
            return None

    logger.warning("Service route rejected: service credential absent or not recognized")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Service authentication required",
        headers={"WWW-Authenticate": "ApiKey"},
    )
