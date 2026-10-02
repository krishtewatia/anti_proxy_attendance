import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies.auth import get_owned_session, require_teacher
from app.database.sessions import create_session, get_sessions_by_owner
from app.schemas.session import SessionCreate, SessionResponse
from app.services.audit_service import record_audit_event

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/sessions",
    tags=["sessions"],
)


@router.post(
    "",
    response_model=SessionResponse,
    status_code=201,
)
async def create_session_endpoint(
    session: SessionCreate,
    current_user: Annotated[dict, Depends(require_teacher)],
) -> SessionResponse:
    created_session = await create_session(
        session,
        created_by=current_user["user_id"],
    )

    # Record audit event (resilient to audit logging failure)
    try:
        start_time_iso = (
            created_session["start_time"].isoformat()
            if hasattr(created_session["start_time"], "isoformat")
            else str(created_session["start_time"])
        )
        end_time_iso = (
            created_session["end_time"].isoformat()
            if hasattr(created_session["end_time"], "isoformat")
            else str(created_session["end_time"])
        )
        await record_audit_event(
            actor_user_id=current_user["user_id"],
            actor_role=current_user.get("role", "TEACHER"),
            action="SESSION_CREATED",
            resource_type="SESSION",
            resource_id=created_session["session_id"],
            metadata={
                "course_name": created_session["course_name"],
                "classroom_id": created_session["classroom_id"],
                "start_time": start_time_iso,
                "end_time": end_time_iso,
                "required_presence_percentage": created_session[
                    "required_presence_percentage"
                ],
            },
        )
    except Exception:
        logger.exception("Failed to record audit event for SESSION_CREATED")

    return SessionResponse(
        session_id=created_session["session_id"],
        course_name=created_session["course_name"],
        classroom_id=created_session["classroom_id"],
        start_time=created_session["start_time"],
        end_time=created_session["end_time"],
        required_presence_percentage=created_session[
            "required_presence_percentage"
        ],
        status=created_session["status"],
        created_by=created_session["created_by"],
    )


@router.get(
    "",
    response_model=list[SessionResponse],
)
async def list_teacher_sessions_endpoint(
    current_user: Annotated[dict, Depends(require_teacher)],
) -> list[SessionResponse]:
    """Retrieve all attendance sessions owned by the authenticated teacher."""
    sessions = await get_sessions_by_owner(current_user["user_id"])

    return [
        SessionResponse(
            session_id=s["session_id"],
            course_name=s["course_name"],
            classroom_id=s["classroom_id"],
            start_time=s["start_time"],
            end_time=s["end_time"],
            required_presence_percentage=s["required_presence_percentage"],
            status=s["status"],
            created_by=s["created_by"],
        )
        for s in sessions
    ]


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
)
async def get_session_details_endpoint(
    session_id: str,
    current_user: Annotated[dict, Depends(require_teacher)],
) -> SessionResponse:
    """Retrieve details for a specific attendance session owned by the authenticated teacher."""
    session = await get_owned_session(session_id, current_user)

    return SessionResponse(
        session_id=session["session_id"],
        course_name=session["course_name"],
        classroom_id=session["classroom_id"],
        start_time=session["start_time"],
        end_time=session["end_time"],
        required_presence_percentage=session["required_presence_percentage"],
        status=session["status"],
        created_by=session["created_by"],
    )
