from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies.auth import get_owned_session, require_teacher
from app.database.attendance import get_attendance_by_session
from app.schemas.attendance_response import (
    AttendanceSessionResponse,
    AttendanceSummaryItem,
)


router = APIRouter(
    prefix="/api/v1/attendance",
    tags=["attendance"],
)


@router.get(
    "/{session_id}",
    response_model=AttendanceSessionResponse,
)
async def get_session_attendance(
    session_id: str,
    current_user: Annotated[dict, Depends(require_teacher)],
) -> AttendanceSessionResponse:
    """Return attendance records for a session."""

    await get_owned_session(session_id, current_user)

    records = await get_attendance_by_session(session_id)

    return AttendanceSessionResponse(
        session_id=session_id,
        records=[
            AttendanceSummaryItem(
                attendance_id=record["attendance_id"],
                identity=record["identity"],
                presence_duration_seconds=record[
                    "presence_duration_seconds"
                ],
                presence_percentage=record[
                    "presence_percentage"
                ],
                required_presence_percentage=record[
                    "required_presence_percentage"
                ],
                status=record["status"],
                manually_corrected=record.get("manually_corrected", False),
            )
            for record in records
        ],
    )
