from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


AttendanceStatus = Literal["PRESENT", "ABSENT"]


class AttendanceCorrectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_status: AttendanceStatus
    new_presence_seconds: float = Field(ge=0)
    reason: str = Field(min_length=1, max_length=1000)


class AttendanceCorrectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correction_id: str
    attendance_id: str
    session_id: str
    identity: str

    corrected_by: str

    previous_status: AttendanceStatus
    new_status: AttendanceStatus

    previous_presence_seconds: float
    new_presence_seconds: float

    reason: str
    corrected_at: datetime
