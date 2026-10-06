from typing import Optional
from pydantic import BaseModel, ConfigDict


class AttendanceSummaryItem(BaseModel):
    """Attendance information for one student in a session."""

    model_config = ConfigDict(extra="forbid")

    attendance_id: str
    identity: str
    student_id: Optional[str] = None
    student_name: Optional[str] = None
    status: str = "ABSENT"  # "PRESENT" | "ABSENT"

    # Optional legacy fields for backward compatibility
    presence_duration_seconds: float = 0.0
    presence_percentage: float = 0.0
    required_presence_percentage: float = 0.0
    manually_corrected: bool = False
    requires_review: bool = False
    anomalies: list[str] = []


class AttendanceSessionResponse(BaseModel):
    """Attendance summary for one session."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    course_name: Optional[str] = None
    total_students: int = 0
    present_count: int = 0
    records: list[AttendanceSummaryItem]
