from pydantic import BaseModel, ConfigDict, Field


class StudentProfile(BaseModel):
    """Schema representing an authenticated student's identity mapping."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    identity: str = Field(min_length=1, max_length=128)


class StudentProfileBind(BaseModel):
    """Schema for binding an authenticated student to a CV identity."""

    model_config = ConfigDict(extra="forbid")

    identity: str = Field(min_length=1, max_length=128)
