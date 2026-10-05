from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies.auth import get_current_user
from app.database.attendance import get_attendance_record
from app.database.sessions import get_session, get_sessions_by_owner
from app.database.users import get_user_by_email, get_user_by_id
from app.schemas.audit import AuditEventResponse
from app.services.audit_service import get_audit_events

router = APIRouter(
    prefix="/api/v1/audit",
    tags=["audit"],
)

VALID_RESOURCE_TYPES = {
    "USER",
    "SESSION",
    "SESSION_ROSTER",
    "ATTENDANCE",
    "STUDENT_PROFILE",
    "SYSTEM",
}


def _to_response(e) -> AuditEventResponse:
    return AuditEventResponse(
        audit_id=e.audit_id,
        actor_user_id=e.actor_user_id,
        actor_role=e.actor_role,
        action=e.action,
        resource_type=e.resource_type,
        resource_id=e.resource_id,
        timestamp=e.timestamp,
        metadata=e.metadata,
    )


@router.get(
    "",
    response_model=list[AuditEventResponse],
    status_code=status.HTTP_200_OK,
)
async def list_audit_events(
    current_user: Annotated[dict, Depends(get_current_user)],
    resource_type: str | None = Query(default=None),
    resource_id: str | None = Query(default=None),
) -> list[AuditEventResponse]:
    """
    Retrieve audit trail records with RBAC and session-ownership enforcement.

    - TEACHER: Can inspect audit events for sessions they own (and associated rosters/attendance).
    - ADMIN: Can inspect broader system audit events.
    - STUDENT: Forbidden (HTTP 403).
    """
    # 1. RBAC check: Only TEACHER or ADMIN can access audit records
    role = current_user.get("role")
    if role not in ("TEACHER", "ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Insufficient permissions to access audit records",
        )

    # 2. Validate resource_type filter value if provided
    if resource_type is not None and resource_type not in VALID_RESOURCE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid resource_type: '{resource_type}'. Valid types are: {', '.join(sorted(VALID_RESOURCE_TYPES))}",
        )

    # 3. Handle TEACHER authorization & scoping
    if role == "TEACHER":
        # Teachers cannot inspect system, user, or student_profile logs
        if resource_type in ("USER", "SYSTEM", "STUDENT_PROFILE"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Teachers cannot access this audit resource type",
            )

        if resource_id is not None:
            # Specific resource requested
            if resource_type in ("SESSION", "SESSION_ROSTER"):
                session = await get_session(resource_id)
                if session is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Session not found",
                    )
                if session.get("created_by") != current_user.get("user_id"):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Forbidden: You do not own this session",
                    )
            elif resource_type == "ATTENDANCE":
                att_record = await get_attendance_record(resource_id)
                if att_record is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Attendance record not found",
                    )
                session = await get_session(att_record.get("session_id"))
                if session is None or session.get("created_by") != current_user.get("user_id"):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Forbidden: You do not own the session for this attendance record",
                    )
            else:
                # No resource_type specified, check whether resource_id is session or attendance
                session = await get_session(resource_id)
                if session:
                    if session.get("created_by") != current_user.get("user_id"):
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Forbidden: You do not own this session",
                        )
                else:
                    att_record = await get_attendance_record(resource_id)
                    if att_record:
                        session = await get_session(att_record.get("session_id"))
                        if session is None or session.get("created_by") != current_user.get(
                            "user_id"
                        ):
                            raise HTTPException(
                                status_code=status.HTTP_403_FORBIDDEN,
                                detail="Forbidden: You do not own the session for this attendance record",
                            )
                    else:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail="Resource not found",
                        )

            events = await get_audit_events(resource_type=resource_type, resource_id=resource_id)
            return [_to_response(e) for e in events]

        else:
            # Teacher queries without specific resource_id
            owned_sessions = await get_sessions_by_owner(current_user["user_id"])
            owned_session_ids = {s["session_id"] for s in owned_sessions}

            all_events = await get_audit_events(resource_type=resource_type)
            allowed_events = []
            for ev in all_events:
                rt = ev.resource_type
                rid = ev.resource_id
                if rt in ("SESSION", "SESSION_ROSTER") and rid in owned_session_ids:
                    allowed_events.append(ev)
                elif rt == "ATTENDANCE" and ev.metadata.get("session_id") in owned_session_ids:
                    allowed_events.append(ev)
                elif ev.actor_user_id == current_user["user_id"]:
                    allowed_events.append(ev)

            return [_to_response(e) for e in allowed_events]

    # 4. Handle ADMIN authorization
    if role == "ADMIN":
        # Validate existence if resource_id is specified
        if resource_id is not None:
            if resource_type in ("SESSION", "SESSION_ROSTER"):
                session = await get_session(resource_id)
                if session is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Session not found",
                    )
            elif resource_type == "ATTENDANCE":
                att_record = await get_attendance_record(resource_id)
                if att_record is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Attendance record not found",
                    )
            elif resource_type == "USER":
                user = await get_user_by_id(resource_id)
                if user is None:
                    user = await get_user_by_email(resource_id)
                if user is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="User not found",
                    )
            elif resource_type is None:
                # Check general existence
                s = await get_session(resource_id)
                a = await get_attendance_record(resource_id) if not s else None
                u = await get_user_by_id(resource_id) if not s and not a else None
                if not s and not a and not u:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Resource not found",
                    )

        events = await get_audit_events(resource_type=resource_type, resource_id=resource_id)
        return [_to_response(e) for e in events]

    return []
