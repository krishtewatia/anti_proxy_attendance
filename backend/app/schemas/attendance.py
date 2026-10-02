from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class AttendanceInterval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_time: datetime
    exit_time: datetime


class AttendanceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attendance_id: str
    session_id: str
    identity: str

    presence_intervals: list[AttendanceInterval]

    presence_duration_seconds: float
    presence_percentage: float
    required_presence_percentage: float

    status: Literal["PRESENT", "ABSENT"]
