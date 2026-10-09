import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.database.mongodb import get_database
from app.api.dependencies.auth import (
    get_owned_session,
    require_teacher,
    require_teacher_or_admin,
)
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


async def _refuse_students_outside_assigned_classes(identities: list[str], teacher: dict) -> None:
    if teacher.get("role") == "ADMIN" or not identities:
        return
    db = get_database()
    teacher_profile = await db["teacher_profiles"].find_one({"user_id": teacher["user_id"]}) or {}
    allowed = {str(c).strip().upper() for c in teacher_profile.get("assigned_classes") or []}
    pending = {
        doc["user_id"] async for doc in db["users"].find({"status": "PENDING"}, {"user_id": 1})
    }
    keys = sorted({str(i) for i in identities})
    cursor = db["student_profiles"].find(
        {"$or": [{"identity": {"$in": keys}}, {"student_id": {"$in": keys}}]},
        {"identity": 1, "student_id": 1, "class_code": 1, "user_id": 1},
    )
    refused = []
    async for student in cursor:
        class_code = str(student.get("class_code") or "").strip().upper()
        if class_code not in allowed or student.get("user_id") in pending:
            refused.append(str(student.get("student_id") or student.get("identity")))
    if refused:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "These students are not in a class assigned to you, or are not approved yet: "
                + ", ".join(sorted(refused)[:10])
            ),
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

    # A roster grants access to its students (their photos, their attendance),
    # so a teacher may add a registered student only from a class assigned to
    # them. Identities with no student record behind them carry no such data.
    await _refuse_students_outside_assigned_classes(payload.identities, current_user)

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
    current_user: Annotated[dict, Depends(require_teacher_or_admin)],
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
