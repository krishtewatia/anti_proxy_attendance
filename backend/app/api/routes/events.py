import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import (
    ConnectionFailure,
    DuplicateKeyError,
    PyMongoError,
    ServerSelectionTimeoutError,
)

from app.api.dependencies.camera_auth import (
    CameraAuthContext,
    require_camera_auth,
    validate_camera_binding,
)
from app.api.dependencies.rate_limiter import check_events_rate_limit
from app.core.client_ip import client_ip as get_client_ip
from app.core.config import settings
from app.database import get_database
from app.schemas.vision_event import VisionEventCreate, VisionEventResponse
from app.services.session_resolution_service import (
    find_active_session_for_classroom,
    resolve_classroom_for_camera_db,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


@router.post(
    "",
    response_model=VisionEventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest Vision Transit Event",
    description="Ingest perception transit events from Vision Service. Idempotent on event_id.",
    dependencies=[Depends(check_events_rate_limit)],
)
async def ingest_vision_event(
    event: VisionEventCreate,
    response: Response,
    request: Request,
    auth_context: CameraAuthContext = Depends(require_camera_auth),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    # 0. Enforce Payload Size Limit
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.EVENTS_MAX_PAYLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Payload size exceeds maximum allowed limit of {settings.EVENTS_MAX_PAYLOAD_BYTES} bytes",
        )

    # 1. Enforce Camera ID Binding
    client_ip = get_client_ip(request)
    await validate_camera_binding(auth_context, event.camera_id, client_ip, db=db)

    # 1B. Demo Mode camera restriction
    allowed_demo_cameras = {
        settings.DEMO_CAMERA_ID,
        "LOCAL_WEBCAM",
        "WEBCAM_0",
        "WEBCAM_1",
        "WEBCAM_2",
    }
    if settings.DEMO_MODE and event.camera_id not in allowed_demo_cameras:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"In DEMO_MODE, accepted cameras are {allowed_demo_cameras}. Received: {event.camera_id}",
        )

    # 2. Timestamp Validation (Task 3)
    if settings.EVENT_TIMESTAMP_VALIDATION_ENABLED:
        now = datetime.now(timezone.utc)
        event_ts = event.timestamp
        if event_ts.tzinfo is None:
            event_ts = event_ts.replace(tzinfo=timezone.utc)

        future_limit = now + timedelta(seconds=settings.EVENT_MAX_FUTURE_SKEW_SECONDS)
        if event_ts > future_limit:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Event timestamp {event_ts.isoformat()} is too far in the future (skew exceeds {settings.EVENT_MAX_FUTURE_SKEW_SECONDS}s)",
            )

        past_limit = now - timedelta(seconds=settings.EVENT_MAX_PAST_AGE_SECONDS)
        if event_ts < past_limit:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Event timestamp {event_ts.isoformat()} is older than allowable window ({settings.EVENT_MAX_PAST_AGE_SECONDS}s)",
            )

    collection = db[settings.EVENTS_COLLECTION]

    # 3. Idempotency Check: Existing event_id (Task 2 & 6)
    try:
        existing = await collection.find_one({"event_id": event.event_id})
    except (PyMongoError, ServerSelectionTimeoutError, ConnectionFailure) as exc:
        logger.error(
            "Database connection failure on idempotency check for %s: %s", event.event_id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable. Please retry later.",
            headers={"Retry-After": "2"},
        )

    if existing:
        response.status_code = status.HTTP_200_OK
        return VisionEventResponse(
            event_id=event.event_id,
            status="duplicate",
            message="Event already processed",
            processed_at=existing.get("created_at"),
        )

    # 4. Prepare document for persistence & enrich with active session
    event_doc = event.model_dump()
    event_doc["created_at"] = datetime.now(timezone.utc)

    classroom_id = await resolve_classroom_for_camera_db(event.camera_id, db=db)
    try:
        active_session = await find_active_session_for_classroom(
            classroom_id=classroom_id,
            timestamp=event.timestamp,
            db=db,
        )
    except (PyMongoError, ServerSelectionTimeoutError, ConnectionFailure) as exc:
        logger.error(
            "Database connection failure on session resolution for %s: %s", event.event_id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable. Please retry later.",
            headers={"Retry-After": "2"},
        )

    event_doc["classroom_id"] = classroom_id
    event_doc["session_id"] = active_session["session_id"] if active_session else None

    # 5. Store in MongoDB with unique constraint protection (Task 2 & 6)
    try:
        await collection.insert_one(event_doc)
    except DuplicateKeyError:
        response.status_code = status.HTTP_200_OK
        existing = await collection.find_one({"event_id": event.event_id})
        return VisionEventResponse(
            event_id=event.event_id,
            status="duplicate",
            message="Event already processed",
            processed_at=existing.get("created_at") if existing else None,
            session_id=event_doc.get("session_id"),
        )
    except (PyMongoError, ServerSelectionTimeoutError, ConnectionFailure) as exc:
        logger.error("Database connection failure on event insert for %s: %s", event.event_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable. Please retry later.",
            headers={"Retry-After": "2"},
        )

    return VisionEventResponse(
        event_id=event.event_id,
        status="accepted",
        message="Event successfully ingested",
        processed_at=event_doc["created_at"],
        session_id=event_doc.get("session_id"),
    )
