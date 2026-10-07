"""Student Schemas for Multi-Role Attendance Management."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class StudentProfile(BaseModel):
    """Legacy schema representing student identity mapping."""

    model_config = ConfigDict(extra="ignore")

    user_id: str
    identity: str = Field(min_length=1, max_length=128)


class StudentProfileBind(BaseModel):
    """Schema for binding an authenticated student to a CV identity."""

    model_config = ConfigDict(extra="ignore")

    identity: str = Field(min_length=1, max_length=128)


class StudentRegisterRequest(BaseModel):
    """Payload for self-service or admin student registration."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=2, max_length=128)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=6, max_length=128)
    student_id: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$",
        description="College ID e.g. DS20260125 (letters, digits, '.', '_' and '-')",
    )
    roll_number: str = Field(
        min_length=2, max_length=64, description="ERP / Roll number e.g. 20261234"
    )
    branch: str = Field(
        min_length=1, max_length=64, description="Academic branch e.g. Data Science"
    )
    section: str = Field(min_length=1, max_length=16, description="Section e.g. B")
    photo_base64: Optional[str] = Field(
        default=None, description="Optional Base64 encoded photograph"
    )


class StudentProfileResponse(BaseModel):
    """Complete student profile presented on dashboard or admin management."""

    model_config = ConfigDict(extra="ignore")

    user_id: str
    identity: str
    name: str
    email: str
    student_id: str
    roll_number: str
    branch: str
    section: str
    class_code: str
    photo_url: Optional[str] = None
    has_biometric: bool = False
    created_at: Optional[datetime] = None


class SubjectAttendanceItem(BaseModel):
    """Student attendance summary for a single course/subject."""

    model_config = ConfigDict(extra="ignore")

    subject: str
    present: int
    total: int
    percentage: float


class StudentAttendanceHistoryItem(BaseModel):
    """Single past attendance session record for a student."""

    model_config = ConfigDict(extra="ignore")

    session_id: str
    course_name: str
    subject: str
    class_code: str
    date_str: str
    status: str  # "PRESENT" or "ABSENT"


class StudentAttendanceDashboardResponse(BaseModel):
    """Full student dashboard telemetry."""

    model_config = ConfigDict(extra="ignore")

    profile: StudentProfileResponse
    overall_present: int
    overall_total: int
    overall_percentage: float
    subjects: list[SubjectAttendanceItem]
    history: list[StudentAttendanceHistoryItem]
