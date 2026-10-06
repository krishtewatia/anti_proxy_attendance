import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies.auth import get_owned_session, require_teacher
from app.schemas.session_finalization import SessionFinalizationResponse
from app.services.audit_service import record_audit_event
from app.services.session_enrollment import get_enrolled_roster
from app.services.session_finalization import finalize_session_attendance

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/sessions",
    tags=["session-finalization"],
)


@router.post(
    "/{session_id}/finalize",
    response_model=SessionFinalizationResponse,
)
async def finalize_session(
    session_id: str,
    current_user: Annotated[dict, Depends(require_teacher)],
) -> SessionFinalizationResponse:
    session = await get_owned_session(session_id, current_user)

    roster = await get_enrolled_roster(session_id)

    if roster is None:
        raise HTTPException(
            status_code=404,
            detail="Session roster not found",
        )

    records = await finalize_session_attendance(
        session_id=session_id,
        session_start=session["start_time"],
        session_end=session["end_time"],
        required_presence_percentage=session["required_presence_percentage"],
        roster=roster,
    )

    # Record audit event (resilient to audit logging failure)
    try:
        await record_audit_event(
            actor_user_id=current_user["user_id"],
            actor_role=current_user.get("role", "TEACHER"),
            action="ATTENDANCE_FINALIZED",
            resource_type="SESSION",
            resource_id=session_id,
            metadata={
                "attendance_record_count": len(records),
                "required_presence_percentage": session["required_presence_percentage"],
            },
        )
    except Exception:
        logger.exception("Failed to record attendance finalization audit event")

    serialized_records = []
    for record in records:
        rec = dict(record)
        if "_id" in rec:
            rec["_id"] = str(rec["_id"])
        serialized_records.append(rec)

    return SessionFinalizationResponse(
        session_id=session_id,
        records=serialized_records,
    )
