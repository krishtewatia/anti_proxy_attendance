from datetime import datetime, timezone
import logging
import uuid

from app.database.attendance import (
    get_attendance_record,
    update_attendance_record,
)
from app.database.attendance_corrections import (
    create_correction,
    get_corrections_for_attendance,
)
from app.database.sessions import get_session
from app.schemas.attendance_correction import AttendanceCorrectionResponse
from app.services.audit_service import record_audit_event

logger = logging.getLogger(__name__)


class AttendanceNotFoundError(ValueError):
    """Raised when the specified attendance record does not exist."""

    pass


async def correct_attendance(
    attendance_id: str,
    new_status: str,
    new_presence_seconds: float,
    reason: str,
    corrected_by: str,
    corrected_by_role: str = "TEACHER",
) -> AttendanceCorrectionResponse:
    """
    Execute an auditable correction for an existing attendance record.

    Workflow:
    1. Validates input constraints (valid status, non-negative seconds, non-empty reason).
    2. Retrieves the existing attendance record and captures its before-state.
    3. Recomputes presence_percentage based on the session's duration.
    4. Persists an immutable audit log entry in attendance_corrections.
    5. Updates the attendance_records document with the new state.
    6. Returns an AttendanceCorrectionResponse object.
    """
    # 1. Validation
    if new_status not in ("PRESENT", "ABSENT"):
        raise ValueError(
            f"Invalid status: '{new_status}'. Allowed values are 'PRESENT' or 'ABSENT'."
        )

    if new_presence_seconds is None or new_presence_seconds < 0:
        raise ValueError("new_presence_seconds must be a non-negative number.")

    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("A valid non-empty reason must be provided for the correction.")

    if len(reason) > 1000:
        raise ValueError("Reason cannot exceed 1000 characters.")

    if not corrected_by or not corrected_by.strip():
        raise ValueError("corrected_by must be provided from authenticated user context.")

    # 2. Fetch existing attendance record
    attendance = await get_attendance_record(attendance_id)
    if not attendance:
        raise AttendanceNotFoundError(f"Attendance record '{attendance_id}' not found.")

    # 3. Recalculate presence_percentage based on session time window
    session_id = attendance["session_id"]
    session = await get_session(session_id)

    new_presence_percentage = 0.0
    if session:
        start_time = session.get("start_time")
        end_time = session.get("end_time")

        if isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time)
        if isinstance(end_time, str):
            end_time = datetime.fromisoformat(end_time)

        if start_time and end_time:
            session_duration_seconds = (end_time - start_time).total_seconds()
            if session_duration_seconds > 0:
                raw_pct = (new_presence_seconds / session_duration_seconds) * 100.0
                new_presence_percentage = round(min(100.0, max(0.0, raw_pct)), 2)

    # 4. Capture before-state and create immutable audit record
    correction_id = f"corr_{uuid.uuid4().hex[:12]}"
    corrected_at = datetime.now(timezone.utc)

    previous_status = attendance.get("status")
    previous_presence_seconds = float(attendance.get("presence_duration_seconds", 0.0))
    previous_presence_percentage = float(attendance.get("presence_percentage", 0.0))

    audit_entry = {
        "correction_id": correction_id,
        "attendance_id": attendance_id,
        "session_id": session_id,
        "identity": attendance.get("identity"),
        "corrected_by": corrected_by.strip(),
        "previous_status": previous_status,
        "new_status": new_status,
        "previous_presence_seconds": previous_presence_seconds,
        "new_presence_seconds": float(new_presence_seconds),
        "previous_presence_percentage": previous_presence_percentage,
        "new_presence_percentage": float(new_presence_percentage),
        "reason": reason.strip(),
        "corrected_at": corrected_at,
    }
    await create_correction(audit_entry)

    # 5. Atomically update the current attendance record
    attendance_updates = {
        "status": new_status,
        "presence_duration_seconds": float(new_presence_seconds),
        "presence_percentage": float(new_presence_percentage),
        "manually_corrected": True,
        "last_corrected_at": corrected_at,
        "last_corrected_by": corrected_by.strip(),
        "last_correction_id": correction_id,
    }
    await update_attendance_record(attendance_id, attendance_updates)

    # 6. Centralized system audit event (resilient to audit logging failure)
    try:
        await record_audit_event(
            actor_user_id=corrected_by.strip(),
            actor_role=corrected_by_role,
            action="ATTENDANCE_CORRECTED",
            resource_type="ATTENDANCE",
            resource_id=attendance_id,
            metadata={
                "session_id": session_id,
                "identity": attendance.get("identity"),
                "previous_status": previous_status,
                "new_status": new_status,
                "previous_presence_seconds": previous_presence_seconds,
                "new_presence_seconds": float(new_presence_seconds),
                "reason": reason.strip(),
                # Who made it: the session's teacher, or an administrator.
                "corrected_by_role": corrected_by_role,
                "admin_correction": corrected_by_role == "ADMIN",
            },
        )
    except Exception:
        logger.exception("Failed to record attendance correction audit event")

    # 7. Return response
    return AttendanceCorrectionResponse(
        correction_id=correction_id,
        attendance_id=attendance_id,
        session_id=session_id,
        identity=attendance.get("identity"),
        corrected_by=corrected_by.strip(),
        previous_status=previous_status,
        new_status=new_status,
        previous_presence_seconds=previous_presence_seconds,
        new_presence_seconds=float(new_presence_seconds),
        reason=reason.strip(),
        corrected_at=corrected_at,
    )


async def get_correction_history(
    attendance_id: str,
) -> list[AttendanceCorrectionResponse]:
    """Retrieve all historical correction audit records for an attendance record."""
    records = await get_corrections_for_attendance(attendance_id)
    return [
        AttendanceCorrectionResponse(
            correction_id=r["correction_id"],
            attendance_id=r["attendance_id"],
            session_id=r["session_id"],
            identity=r["identity"],
            corrected_by=r["corrected_by"],
            previous_status=r["previous_status"],
            new_status=r["new_status"],
            previous_presence_seconds=r["previous_presence_seconds"],
            new_presence_seconds=r["new_presence_seconds"],
            reason=r["reason"],
            corrected_at=r["corrected_at"],
        )
        for r in records
    ]
