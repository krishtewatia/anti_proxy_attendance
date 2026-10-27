"""Teacher Schemas for Multi-Role Attendance Management."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class TeacherRegisterRequest(BaseModel):
    """Payload to register a new teacher account."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=2, max_length=128)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=6, max_length=128)
    # An internal key: made up by the system when not given.
    teacher_id: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=64,
        description="Internal key; leave out to have one made up",
    )
    department: str = Field(
        default="CSE-DS",
        min_length=2,
        max_length=128,
        description="Academic department e.g. CSE-DS",
    )
    assigned_classes: list[str] = Field(
        default_factory=list, description="Class codes e.g. ['DS-B', 'DS-C']"
    )
    assigned_subjects: list[str] = Field(
        default_factory=list, description="Course subjects e.g. ['Machine Learning']"
    )


class TeacherProfileResponse(BaseModel):
    """Public teacher profile schema."""

    model_config = ConfigDict(extra="ignore")

    user_id: str
    teacher_id: str
    name: str
    email: str
    department: str
    assigned_classes: list[str]
    assigned_subjects: list[str]


class TeacherAssignClassesRequest(BaseModel):
    """Admin payload to assign classes and subjects to a teacher."""

    model_config = ConfigDict(extra="ignore")

    assigned_classes: list[str]
    assigned_subjects: list[str]


class TeacherSessionSummaryItem(BaseModel):
    """Summary of one attendance session for teacher/admin dashboard."""

    model_config = ConfigDict(extra="ignore")

    session_id: str
    course_name: str
    class_code: Optional[str] = None
    subject: Optional[str] = None
    total_students: int
    present_count: int
    attendance_percentage: float
    status: str  # "SCHEDULED", "ACTIVE" or "FINALIZED"
    # False when the session was created but attendance was never taken.
    was_taken: bool = True
    # Timetable classes only: False until ENTRY and EXIT are both finalized.
    rounds_complete: Optional[bool] = None
    start_time: Optional[datetime] = None
    created_at: Optional[datetime] = None


class TeacherDashboardResponse(BaseModel):
    """Teacher dashboard data payload."""

    model_config = ConfigDict(extra="ignore")

    teacher: TeacherProfileResponse
    active_session: Optional[TeacherSessionSummaryItem] = None
    previous_sessions: list[TeacherSessionSummaryItem]
