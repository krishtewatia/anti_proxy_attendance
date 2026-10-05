from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class BiometricEnrollRequest(BaseModel):
    """Payload for registering or updating a student biometric profile."""

    model_config = ConfigDict(extra="forbid")

    identity: str = Field(min_length=1, max_length=128, description="Canonical student identity")
    mean_embedding: list[float] = Field(
        min_length=512, max_length=512, description="512-d unit ArcFace embedding"
    )
    sample_count: int = Field(
        ge=1, le=20, default=3, description="Number of source images used for enrollment"
    )
    quality_score: float = Field(
        ge=0.0, le=1.0, default=1.0, description="Quality-weighted score across samples"
    )


class BiometricProfileResponse(BaseModel):
    """Public summary of enrolled biometric profile.

    SECURITY: The raw mean_embedding vector is NEVER exposed in this schema.
    """

    model_config = ConfigDict(extra="ignore")

    identity: str
    sample_count: int
    quality_score: float
    enrolled_by: str
    created_at: datetime
    updated_at: datetime


class BiometricGalleryResponse(BaseModel):
    """Restricted gallery schema returned only to authorized vision service or admin."""

    model_config = ConfigDict(extra="ignore")

    count: int
    gallery: dict[str, list[float]]
