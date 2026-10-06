from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    """Schema used when creating an attendance session."""

    model_config = ConfigDict(extra="forbid")

    course_name: str = Field(min_length=1, max_length=200)
    classroom_id: str = Field(min_length=1, max_length=100, default="ROOM_101")

    start_time: datetime
    end_time: datetime

    class_code: Optional[str] = None
    subject: Optional[str] = None
    branch: Optional[str] = None
    section: Optional[str] = None

    required_presence_percentage: float = Field(
        default=100.0,
        ge=0.0,
        le=100.0,
    )


class SessionResponse(BaseModel):
    """Schema returned by the API for an attendance session."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    course_name: str
    classroom_id: str

    start_time: datetime
    end_time: datetime

    class_code: Optional[str] = None
    subject: Optional[str] = None
    branch: Optional[str] = None
    section: Optional[str] = None

    required_presence_percentage: float = 100.0

    status: str  # "SCHEDULED", "ACTIVE", "FINALIZED", "COMPLETED"
    created_by: str
