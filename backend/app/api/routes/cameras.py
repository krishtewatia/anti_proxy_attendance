"""API routes for Camera Registry and Operational Health Telemetry."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.dependencies.auth import (
    require_admin,
    require_teacher_or_admin,
)
from app.api.dependencies.camera_auth import (
    CameraAuthContext,
    require_camera_auth,
    validate_camera_binding,
)
from app.database import get_database
from app.database.cameras import (
    create_camera_in_db,
    delete_camera_from_db,
    get_camera_from_db,
    list_cameras_from_db,
    record_camera_heartbeat_in_db,
    update_camera_in_db,
)
from app.schemas.camera import (
    CameraCreate,
    CameraHeartbeat,
    CameraHeartbeatResponse,
    CameraResponse,
    CameraStatus,
    CameraUpdate,
    mask_rtsp_url,
)
from app.services.audit_service import record_audit_event
from app.services.session_resolution_service import (
    _CAMERA_REGISTRY,
    register_camera_classroom,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"])


@router.post(
    "",
    response_model=CameraResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new camera in the registry (Admin only)",
)
async def create_camera(
    payload: CameraCreate,
    current_user: Annotated[dict, Depends(require_admin)],
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> CameraResponse:
    existing = await get_camera_from_db(payload.camera_id, db=db)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Camera with ID '{payload.camera_id}' is already registered",
        )

    camera_dict = payload.model_dump()
    created = await create_camera_in_db(camera_dict, db=db)

    # Sync runtime resolution registry
    register_camera_classroom(payload.camera_id, payload.classroom_id)

    # Audit logging with strict credential omission
    audit_meta = {
        "classroom_id": payload.classroom_id,
        "role": payload.role.value,
        "source_type": payload.source_type.value,
        "enabled": payload.enabled,
        "rtsp_url_masked": mask_rtsp_url(payload.rtsp_url),
        "has_secret_ref": bool(payload.secret_reference),
    }
    await record_audit_event(
        actor_user_id=current_user["user_id"],
        actor_role=current_user["role"],
        action="CAMERA_CREATED",
        resource_type="CAMERA",
        resource_id=payload.camera_id,
        metadata=audit_meta,
        db=db,
    )

    return CameraResponse(**created)


@router.get(
    "",
    response_model=list[CameraResponse],
    summary="List all cameras in the registry (Teacher/Admin)",
)
async def list_cameras(
    current_user: Annotated[dict, Depends(require_teacher_or_admin)],
    classroom_id: Optional[str] = Query(None, description="Filter by classroom ID"),
    enabled_only: bool = Query(False, description="Filter only enabled cameras"),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> list[CameraResponse]:
    cameras = await list_cameras_from_db(
        classroom_id=classroom_id,
        enabled_only=enabled_only,
        db=db,
    )
    return [CameraResponse(**cam) for cam in cameras]


@router.get(
    "/{camera_id}",
    response_model=CameraResponse,
    summary="Get camera configuration and operational status (Teacher/Admin)",
)
async def get_camera(
    camera_id: str,
    current_user: Annotated[dict, Depends(require_teacher_or_admin)],
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> CameraResponse:
    camera = await get_camera_from_db(camera_id, db=db)
    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Camera '{camera_id}' not found",
        )
    return CameraResponse(**camera)


@router.patch(
    "/{camera_id}",
    response_model=CameraResponse,
    summary="Update camera configuration (Admin only)",
)
async def update_camera(
    camera_id: str,
    payload: CameraUpdate,
    current_user: Annotated[dict, Depends(require_admin)],
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> CameraResponse:
    existing = await get_camera_from_db(camera_id, db=db)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Camera '{camera_id}' not found",
        )

    updates = payload.model_dump(exclude_unset=True)
    updated = await update_camera_in_db(camera_id, updates, db=db)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Camera '{camera_id}' not found",
        )

    if payload.classroom_id:
        register_camera_classroom(camera_id, payload.classroom_id)

    # Audited without credentials
    audit_meta = {
        "updated_fields": list(updates.keys()),
    }
    if "rtsp_url" in updates:
        audit_meta["rtsp_url_masked"] = mask_rtsp_url(updates["rtsp_url"])

    await record_audit_event(
        actor_user_id=current_user["user_id"],
        actor_role=current_user["role"],
        action="CAMERA_UPDATED",
        resource_type="CAMERA",
        resource_id=camera_id,
        metadata=audit_meta,
        db=db,
    )

    return CameraResponse(**updated)


@router.delete(
    "/{camera_id}",
    status_code=status.HTTP_200_OK,
    summary="Deregister a camera from the registry (Admin only)",
)
async def delete_camera(
    camera_id: str,
    current_user: Annotated[dict, Depends(require_admin)],
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> dict[str, str]:
    existing = await get_camera_from_db(camera_id, db=db)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Camera '{camera_id}' not found",
        )

    deleted = await delete_camera_from_db(camera_id, db=db)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Camera '{camera_id}' could not be deleted",
        )

    # Remove from dynamic runtime cache if present
    _CAMERA_REGISTRY.pop(camera_id, None)

    await record_audit_event(
        actor_user_id=current_user["user_id"],
        actor_role=current_user["role"],
        action="CAMERA_DELETED",
        resource_type="CAMERA",
        resource_id=camera_id,
        metadata={"classroom_id": existing.get("classroom_id")},
        db=db,
    )

    return {"status": "deleted", "camera_id": camera_id}


@router.post(
    "/{camera_id}/heartbeat",
    response_model=CameraHeartbeatResponse,
    summary="Record live camera health heartbeat telemetry (Service-authenticated)",
)
async def record_camera_heartbeat(
    camera_id: str,
    payload: CameraHeartbeat,
    request: Request,
    auth_context: CameraAuthContext = Depends(require_camera_auth),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> CameraHeartbeatResponse:
    if payload.camera_id != camera_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Route camera_id '{camera_id}' does not match body camera_id '{payload.camera_id}'",
        )

    client_ip = request.client.host if request.client else "unknown"
    await validate_camera_binding(auth_context, camera_id, client_ip=client_ip, db=db)

    existing = await get_camera_from_db(camera_id, db=db)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Camera '{camera_id}' is not registered in the system",
        )

    state_str = (
        payload.state.value if isinstance(payload.state, CameraStatus) else str(payload.state)
    )
    await record_camera_heartbeat_in_db(
        camera_id=camera_id,
        state=state_str,
        fps=payload.fps,
        dropped_frames=payload.dropped_frames,
        metadata=payload.metadata,
        db=db,
    )

    now = datetime.now(timezone.utc)
    return CameraHeartbeatResponse(
        status="ok",
        camera_id=camera_id,
        state=payload.state,
        received_at=now,
    )


@router.get(
    "/{camera_id}/health",
    summary="Get camera health and telemetry for dashboard (Teacher/Admin)",
)
async def get_camera_health(
    camera_id: str,
    current_user: Annotated[dict, Depends(require_teacher_or_admin)],
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> dict:
    camera = await get_camera_from_db(camera_id, db=db)
    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Camera '{camera_id}' not found",
        )

    return {
        "camera_id": camera["camera_id"],
        "classroom_id": camera["classroom_id"],
        "status": camera.get("status", CameraStatus.UNKNOWN.value),
        "fps": camera.get("fps"),
        "last_seen": camera.get("last_seen"),
        "enabled": camera.get("enabled", True),
        "role": camera.get("role"),
    }
