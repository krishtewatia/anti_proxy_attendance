"""Event ingestion API route."""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Response, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.database import get_database
from app.schemas.vision_event import VisionEventCreate, VisionEventResponse

router = APIRouter(prefix="/events", tags=["events"])


@router.post(
    "",
    response_model=VisionEventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest Vision Transit Event",
    description="Ingest perception transit events from Vision Service. Idempotent on event_id.",
)
async def ingest_vision_event(
    event: VisionEventCreate,
    response: Response,
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    collection = db[settings.EVENTS_COLLECTION]

    # 1. Idempotency Check: Existing event_id
    existing = await collection.find_one({"event_id": event.event_id})
    if existing:
        response.status_code = status.HTTP_200_OK
        return VisionEventResponse(
            event_id=event.event_id,
            status="duplicate",
            message="Event already processed",
            processed_at=existing.get("created_at"),
        )

    # 2. Prepare document for persistence
    event_doc = event.model_dump()
    event_doc["created_at"] = datetime.now(timezone.utc)

    # 3. Store in MongoDB with unique constraint protection
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
        )

    return VisionEventResponse(
        event_id=event.event_id,
        status="accepted",
        message="Event successfully ingested",
        processed_at=event_doc["created_at"],
    )
