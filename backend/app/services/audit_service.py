from datetime import datetime, timezone
from typing import Any
import uuid

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database.audit import (
    create_audit_event as db_create_audit_event,
    get_audit_event as db_get_audit_event,
    get_audit_events as db_get_audit_events,
)
from app.schemas.audit import (
    AuditAction,
    AuditActorRole,
    AuditEvent,
    AuditResourceType,
)


async def record_audit_event(
    actor_user_id: str,
    actor_role: AuditActorRole | str,
    action: AuditAction | str,
    resource_type: AuditResourceType | str,
    resource_id: str,
    metadata: dict[str, Any] | None = None,
    audit_id: str | None = None,
    timestamp: datetime | None = None,
    db: AsyncIOMotorDatabase | None = None,
) -> AuditEvent:
    """
    Centralized service function to validate and record an immutable audit event.

    Workflow:
    1. Generates a unique audit_id if not provided.
    2. Uses current UTC timestamp if not provided.
    3. Normalizes optional metadata (defaulting to empty dict).
    4. Validates through AuditEvent Pydantic schema (validating actor_role, action, resource_type).
    5. Persists the event via database.audit.create_audit_event().
    6. Returns the validated, persisted AuditEvent.
    """
    generated_audit_id = audit_id or f"audit_{uuid.uuid4().hex[:12]}"
    current_time = timestamp or datetime.now(timezone.utc)
    event_metadata = metadata if metadata is not None else {}

    # Validate schema through AuditEvent
    event = AuditEvent(
        audit_id=generated_audit_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,  # type: ignore[arg-type]
        action=action,  # type: ignore[arg-type]
        resource_type=resource_type,  # type: ignore[arg-type]
        resource_id=resource_id,
        timestamp=current_time,
        metadata=event_metadata,
    )

    # Persist in MongoDB
    await db_create_audit_event(event.model_dump(), db=db)

    return event


async def get_audit_event(audit_id: str) -> AuditEvent | None:
    """Retrieve an audit event by its unique ID."""
    doc = await db_get_audit_event(audit_id)
    if not doc:
        return None
    doc_copy = dict(doc)
    doc_copy.pop("_id", None)
    return AuditEvent.model_validate(doc_copy)


async def get_audit_events(
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> list[AuditEvent]:
    """Retrieve audit events in chronological order, optionally filtered."""
    docs = await db_get_audit_events(resource_type=resource_type, resource_id=resource_id)
    results = []
    for doc in docs:
        doc_copy = dict(doc)
        doc_copy.pop("_id", None)
        results.append(AuditEvent.model_validate(doc_copy))
    return results
