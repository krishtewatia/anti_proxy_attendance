"""Student Schemas for Multi-Role Attendance Management."""

from datetime import datetime
from typing import Annotated, Optional
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.services.registration_rules import ROLL_NUMBER_PATTERN


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
    # An internal key: made up by the system when not given. Students are
    # known by their roll number; nobody needs to type a student ID.
    student_id: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$",
        description="Internal key; leave out to have one made up",
    )
    roll_number: Annotated[str, StringConstraints(strip_whitespace=True)] = Field(
        min_length=2,
        max_length=32,
        pattern=ROLL_NUMBER_PATTERN,
        description="College roll number, digits only e.g. 2401331540142 (unique)",
    )
    # The class is given by its code (the registration form's list of active
    # classes), or the older way by branch and section.
    class_code: Optional[str] = Field(
        default=None, min_length=2, max_length=20, description="Class code e.g. DS-B"
    )
    branch: str = Field(default="", max_length=64, description="Academic branch e.g. Data Science")
    section: str = Field(default="", max_length=16, description="Section e.g. B")
    photo_base64: Optional[str] = Field(
        default=None, description="Optional Base64 encoded photograph"
    )
    # The version of the photo notice the student accepted. Required when a
    # student registering themselves includes a photo.
    consent_version: Optional[str] = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def class_or_branch_and_section(self) -> "StudentRegisterRequest":
        if not (self.class_code and self.class_code.strip()) and not (
            self.branch.strip() and self.section.strip()
        ):
            raise ValueError("Choose a class, or give both a branch and a section")
        return self


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
    status: str  # "PRESENT", "ABSENT" or "NOT_TAKEN"


class StudentAttendanceDashboardResponse(BaseModel):
    """Full student dashboard telemetry."""

    model_config = ConfigDict(extra="ignore")

    profile: StudentProfileResponse
    overall_present: int
    overall_total: int
    # Sessions that were never taken are in neither total; the percentage is
    # null when no session has been taken.
    overall_percentage: Optional[float] = None
    sessions_not_taken: int = 0
    subjects: list[SubjectAttendanceItem]
    history: list[StudentAttendanceHistoryItem]
