import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies.auth import get_owned_session, require_teacher
from app.schemas.session_roster_response import (
    SessionRosterResponse,
    SessionRosterUpdate,
)
from app.services.audit_service import record_audit_event
from app.services.session_enrollment import (
    enroll_session_roster,
    get_enrolled_roster,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/sessions",
    tags=["session-roster"],
)


@router.post(
    "/{session_id}/roster",
    response_model=SessionRosterResponse,
)
@router.put(
    "/{session_id}/roster",
    response_model=SessionRosterResponse,
)
async def update_session_roster(
    session_id: str,
    payload: SessionRosterUpdate,
    current_user: Annotated[dict, Depends(require_teacher)],
) -> SessionRosterResponse:
    await get_owned_session(session_id, current_user)

    roster = await enroll_session_roster(
        session_id=session_id,
        identities=payload.identities,
    )

    # Record audit event (resilient to audit logging failure)
    try:
        await record_audit_event(
            actor_user_id=current_user["user_id"],
            actor_role=current_user.get("role", "TEACHER"),
            action="ROSTER_UPDATED",
            resource_type="SESSION_ROSTER",
            resource_id=session_id,
            metadata={
                "student_count": len(roster.identities),
            },
        )
    except Exception:
        logger.exception("Failed to record audit event for ROSTER_UPDATED")

    return SessionRosterResponse(
        session_id=roster.session_id,
        identities=roster.identities,
    )


@router.get(
    "/{session_id}/roster",
    response_model=SessionRosterResponse,
)
async def get_session_roster(
    session_id: str,
    current_user: Annotated[dict, Depends(require_teacher)],
) -> SessionRosterResponse:
    await get_owned_session(session_id, current_user)

    roster = await get_enrolled_roster(session_id)

    if roster is None:
        raise HTTPException(
            status_code=404,
            detail="Session roster not found",
        )

    return SessionRosterResponse(
        session_id=roster.session_id,
        identities=roster.identities,
    )
