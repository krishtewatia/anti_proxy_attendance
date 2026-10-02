from pydantic import BaseModel, ConfigDict


class AttendanceSummaryItem(BaseModel):
    """Attendance information for one identity."""

    model_config = ConfigDict(extra="forbid")

    attendance_id: str
    identity: str

    presence_duration_seconds: float
    presence_percentage: float
    required_presence_percentage: float

    status: str
    manually_corrected: bool = False


class AttendanceSessionResponse(BaseModel):
    """Attendance summary for one session."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    records: list[AttendanceSummaryItem]
