from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


AuditActorRole = Literal["TEACHER", "STUDENT", "ADMIN", "SYSTEM"]

AuditAction = Literal[
    "USER_REGISTERED",
    "USER_LOGIN",
    "USER_LOGOUT",
    "SESSION_CREATED",
    "SESSION_UPDATED",
    "ROSTER_UPDATED",
    "ATTENDANCE_FINALIZED",
    "ATTENDANCE_CORRECTED",
    "STUDENT_PROFILE_CREATED",
    "STUDENT_PROFILE_UPDATED",
]

AuditResourceType = Literal[
    "USER",
    "SESSION",
    "SESSION_ROSTER",
    "ATTENDANCE",
    "STUDENT_PROFILE",
    "SYSTEM",
]


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_id: str
    actor_user_id: str
    actor_role: AuditActorRole

    action: AuditAction
    resource_type: AuditResourceType
    resource_id: str

    timestamp: datetime

    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp", mode="after")
    @classmethod
    def ensure_utc_timezone(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    audit_id: str
    actor_user_id: str
    actor_role: AuditActorRole
    action: AuditAction
    resource_type: AuditResourceType
    resource_id: str
    timestamp: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
