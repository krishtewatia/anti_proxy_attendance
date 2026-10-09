from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies.auth import (
    get_owned_session,
    require_teacher,
    require_teacher_or_admin,
)
from app.database.attendance import get_attendance_record
from app.schemas.attendance_correction import (
    AttendanceCorrectionCreate,
    AttendanceCorrectionResponse,
    AttendanceStatusToggle,
    AttendanceStatusToggleResponse,
)
from app.services.attendance_correction import (
    AttendanceNotFoundError,
    correct_attendance,
    get_correction_history,
)

TOGGLE_CORRECTION_REASON = "Manual status toggle by teacher"

router = APIRouter(
    prefix="/api/v1/attendance",
    tags=["attendance"],
)


@router.patch(
    "/{session_id}/records/{attendance_id}",
    response_model=AttendanceCorrectionResponse | AttendanceStatusToggleResponse,
    status_code=status.HTTP_200_OK,
)
async def correct_session_attendance(
    session_id: str,
    attendance_id: str,
    payload: AttendanceCorrectionCreate | AttendanceStatusToggle,
    current_user: Annotated[dict, Depends(require_teacher)],
) -> AttendanceCorrectionResponse | AttendanceStatusToggleResponse:
    """
    Manually correct an attendance record for a session.

    Enforces:
    1. Authentication & Role: User must be an authenticated TEACHER.
    2. Session Ownership: Session must exist and be owned by the calling teacher.
    3. Attendance Isolation: Attendance record must exist and belong to the specified session.
    4. Service Execution: Executes audit logging and atomic record update.
    """
    # 1. Enforce session existence and ownership
    await get_owned_session(session_id, current_user)

    # 2. Enforce attendance record existence and session boundary
    record = await get_attendance_record(attendance_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attendance record not found",
        )

    if record.get("session_id") != session_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attendance record does not belong to this session",
        )

    # 3. Call service layer (a status toggle is audited exactly like a full correction)
    is_toggle = isinstance(payload, AttendanceStatusToggle)
    if is_toggle:
        new_status = payload.status
        new_presence_seconds = float(record.get("presence_duration_seconds", 0.0))
        reason = TOGGLE_CORRECTION_REASON
    else:
        new_status = payload.new_status
        new_presence_seconds = payload.new_presence_seconds
        reason = payload.reason

    try:
        correction_result = await correct_attendance(
            attendance_id=attendance_id,
            new_status=new_status,
            new_presence_seconds=new_presence_seconds,
            reason=reason,
            corrected_by=current_user["user_id"],
        )
    except AttendanceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    if is_toggle:
        return AttendanceStatusToggleResponse(
            attendance_id=attendance_id,
            session_id=session_id,
            status=correction_result.new_status,
            correction_id=correction_result.correction_id,
            message=f"Attendance updated to {correction_result.new_status}",
        )

    return correction_result


@router.get(
    "/{session_id}/records/{attendance_id}/corrections",
    response_model=list[AttendanceCorrectionResponse],
    status_code=status.HTTP_200_OK,
)
async def get_session_attendance_corrections(
    session_id: str,
    attendance_id: str,
    current_user: Annotated[dict, Depends(require_teacher_or_admin)],
) -> list[AttendanceCorrectionResponse]:
    """
    Retrieve read-only correction history for an attendance record.

    Enforces:
    1. Authentication & Role: User must be an authenticated TEACHER.
    2. Session Ownership: Session must exist and be owned by the calling teacher.
    3. Attendance Isolation: Attendance record must exist and belong to the specified session.
    4. Service Execution: Returns chronological correction history.
    """
    # 1. Enforce session existence and ownership
    await get_owned_session(session_id, current_user)

    # 2. Enforce attendance record existence and session boundary
    record = await get_attendance_record(attendance_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attendance record not found",
        )

    if record.get("session_id") != session_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attendance record does not belong to this session",
        )

    # 3. Retrieve historical audit records from service
    return await get_correction_history(attendance_id)
