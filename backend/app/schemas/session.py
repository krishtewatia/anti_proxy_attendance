from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    """Schema used when creating an attendance session."""

    model_config = ConfigDict(extra="forbid")

    course_name: str = Field(min_length=1, max_length=200)
    classroom_id: str = Field(min_length=1, max_length=100)

    start_time: datetime
    end_time: datetime

    required_presence_percentage: float = Field(
        default=75.0,
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

    required_presence_percentage: float

    status: Literal["SCHEDULED", "ACTIVE", "COMPLETED"]
    created_by: str
