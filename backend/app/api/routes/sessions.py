"""Sessions API routes for attendance sessions, auto-roster, and active session rule."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.dependencies.auth import get_owned_session, require_teacher
from app.database import get_database
from app.database.attendance import upsert_attendance
from app.database.session_roster import create_session_roster
from app.database.sessions import (
    create_session,
    delete_session_in_db,
    get_active_session_by_teacher,
    get_sessions_by_owner,
    update_session_status,
)
from app.database.student_profiles import get_students_by_class
from app.database.teacher_profiles import get_teacher_profile_by_user_id
from app.schemas.attendance import AttendanceRecord
from app.schemas.live_session import SessionLiveSnapshotResponse
from app.schemas.session import SessionCreate, SessionResponse
from app.schemas.session_roster import SessionRoster
from app.services.audit_service import record_audit_event
from app.services.live_session_service import compute_session_live_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/sessions",
    tags=["sessions"],
)


async def _audit_status_change(current_user: dict, session_id: str, new_status: str) -> None:
    """Record a SESSION_UPDATED audit event without failing the request."""
    try:
        await record_audit_event(
            actor_user_id=current_user["user_id"],
            actor_role=current_user.get("role", "TEACHER"),
            action="SESSION_UPDATED",
            resource_type="SESSION",
            resource_id=session_id,
            metadata={"status": new_status},
        )
    except Exception:
        logger.exception("Failed to record audit event for SESSION_UPDATED")


@router.post(
    "",
    response_model=SessionResponse,
    status_code=201,
    summary="Create a new attendance session with assigned class and automatic roster",
)
async def create_session_endpoint(
    session: SessionCreate,
    current_user: Annotated[dict, Depends(require_teacher)],
) -> SessionResponse:
    # 1. Enforce: Only ONE active session per teacher (Requirement 8)
    active_sess = await get_active_session_by_teacher(current_user["user_id"])
    if active_sess:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You already have an active attendance session. Please finish the current session before starting another.",
        )

    # 2. Enforce: Teacher assigned classes check (Requirement 6 & 13)
    #    A teacher may create a session only for a class an administrator has
    #    assigned to them. No assigned classes, no class given, or another
    #    class: refused. (This is what closes security gap 6.1.)
    if current_user.get("role") != "ADMIN":
        teacher_prof = await get_teacher_profile_by_user_id(current_user["user_id"])
        allowed_classes = {
            str(c).strip().upper() for c in (teacher_prof or {}).get("assigned_classes") or []
        }
        requested_class = (session.class_code or "").strip().upper()
        if not allowed_classes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No classes are assigned to you yet. Ask an administrator to assign your classes.",
            )
        if not requested_class:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Choose one of your assigned classes for the session.",
            )
        if requested_class not in allowed_classes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Class '{session.class_code}' is not assigned to you.",
            )

    # 3. Create session document
    created_session = await create_session(
        session,
        created_by=current_user["user_id"],
    )

    # 4. Automatically generate roster from students belonging to this class (Requirement 6, 22)
    target_class = session.class_code
    if target_class:
        students = await get_students_by_class(class_code=target_class)
        roster_idents = [
            s.get("identity") or s.get("student_id")
            for s in students
            if s.get("identity") or s.get("student_id")
        ]
        if roster_idents:
            await create_session_roster(
                SessionRoster(
                    session_id=created_session["session_id"],
                    identities=roster_idents,
                )
            )
            # Initialize each rostered student as ABSENT
            for s in students:
                ident = s.get("identity") or s.get("student_id")
                if ident:
                    await upsert_attendance(
                        AttendanceRecord(
                            attendance_id=f"att_{created_session['session_id']}_{ident}",
                            session_id=created_session["session_id"],
                            identity=ident,
                            student_id=s.get("student_id", ident),
                            student_name=s.get("name", ident),
                            status="ABSENT",
                        )
                    )
            logger.info(
                "Auto-generated roster for session %s with %d students in class %s",
                created_session["session_id"],
                len(roster_idents),
                target_class,
            )

    # 5. Record audit event (resilient to audit logging failure)
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
                "class_code": created_session.get("class_code"),
                "start_time": start_time_iso,
                "end_time": end_time_iso,
                "required_presence_percentage": created_session["required_presence_percentage"],
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
        class_code=created_session.get("class_code"),
        subject=created_session.get("subject"),
        branch=created_session.get("branch"),
        section=created_session.get("section"),
        required_presence_percentage=created_session["required_presence_percentage"],
        status=created_session["status"],
        created_by=created_session["created_by"],
    )


@router.post(
    "/{session_id}/start",
    response_model=SessionResponse,
    summary="Start attendance session (transitions status to ACTIVE)",
)
async def start_session_endpoint(
    session_id: str,
    current_user: Annotated[dict, Depends(require_teacher)],
) -> SessionResponse:
    session = await get_owned_session(session_id, current_user)

    # Check if another session is already active
    active_sess = await get_active_session_by_teacher(current_user["user_id"])
    if active_sess and active_sess["session_id"] != session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You already have an active attendance session. Please finish the current session before starting another.",
        )

    await update_session_status(session_id, "ACTIVE")
    session["status"] = "ACTIVE"
    await _audit_status_change(current_user, session_id, "ACTIVE")

    return SessionResponse(
        session_id=session["session_id"],
        course_name=session["course_name"],
        classroom_id=session["classroom_id"],
        start_time=session["start_time"],
        end_time=session["end_time"],
        class_code=session.get("class_code"),
        subject=session.get("subject"),
        branch=session.get("branch"),
        section=session.get("section"),
        required_presence_percentage=session["required_presence_percentage"],
        status="ACTIVE",
        created_by=session["created_by"],
    )


@router.post(
    "/{session_id}/end",
    response_model=SessionResponse,
    summary="End attendance session (transitions status to FINALIZED)",
)
@router.post(
    "/{session_id}/finalize",
    response_model=SessionResponse,
    include_in_schema=False,
)
async def end_session_endpoint(
    session_id: str,
    current_user: Annotated[dict, Depends(require_teacher)],
) -> SessionResponse:
    session = await get_owned_session(session_id, current_user)
    await update_session_status(session_id, "FINALIZED")
    session["status"] = "FINALIZED"
    await _audit_status_change(current_user, session_id, "FINALIZED")

    return SessionResponse(
        session_id=session["session_id"],
        course_name=session["course_name"],
        classroom_id=session["classroom_id"],
        start_time=session["start_time"],
        end_time=session["end_time"],
        class_code=session.get("class_code"),
        subject=session.get("subject"),
        branch=session.get("branch"),
        section=session.get("section"),
        required_presence_percentage=session["required_presence_percentage"],
        status="FINALIZED",
        created_by=session["created_by"],
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
            class_code=s.get("class_code"),
            subject=s.get("subject"),
            branch=s.get("branch"),
            section=s.get("section"),
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
        class_code=session.get("class_code"),
        subject=session.get("subject"),
        branch=session.get("branch"),
        section=session.get("section"),
        required_presence_percentage=session["required_presence_percentage"],
        status=session["status"],
        created_by=session["created_by"],
    )


@router.get(
    "/{session_id}/live-snapshot",
    response_model=SessionLiveSnapshotResponse,
    summary="Get real-time live presence snapshot, camera health, and events feed (Teacher owned)",
)
async def get_session_live_snapshot_endpoint(
    session_id: str,
    current_user: Annotated[dict, Depends(require_teacher)],
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> SessionLiveSnapshotResponse:
    session = await get_owned_session(session_id, current_user)
    return await compute_session_live_snapshot(session, db=db)


@router.delete(
    "/{session_id}",
    summary="Delete an attendance session (Teacher owned)",
)
async def delete_session_endpoint(
    session_id: str,
    current_user: Annotated[dict, Depends(require_teacher)],
) -> dict:
    _ = await get_owned_session(session_id, current_user)
    deleted = await delete_session_in_db(session_id)
    return {"deleted": deleted, "session_id": session_id}
