from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class AttendanceInterval(BaseModel):
    """Legacy interval model retained for backwards compatibility."""

    model_config = ConfigDict(extra="ignore")

    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None


class AttendanceRecord(BaseModel):
    """Clean One-Time AI Face Recognition Attendance Record."""

    model_config = ConfigDict(extra="ignore")

    attendance_id: str
    session_id: str
    identity: str
    student_id: Optional[str] = None
    student_name: Optional[str] = None
    status: Literal["PRESENT", "ABSENT"] = "ABSENT"
    marked_at: Optional[datetime] = None

    # Optional legacy fields for backward compatibility
    presence_intervals: list[AttendanceInterval] = []
    presence_duration_seconds: float = 0.0
    presence_percentage: float = 0.0
    required_presence_percentage: float = 0.0
    requires_review: bool = False
    anomalies: list[str] = []


class MarkAttendanceRequest(BaseModel):
    """Payload to mark a student present in a session."""

    model_config = ConfigDict(extra="ignore")

    identity: str
    session_id: Optional[str] = None
    confidence: Optional[float] = None
    timestamp: Optional[datetime] = None


class MarkAttendanceResponse(BaseModel):
    """Response returned when marking a student."""

    model_config = ConfigDict(extra="ignore")

    status: Literal["marked", "already_present", "not_found", "error"]
    identity: str
    student_id: Optional[str] = None
    student_name: Optional[str] = None
    message: str
