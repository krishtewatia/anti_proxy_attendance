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
    "FACE_ENROLLED",
    "FACE_REENROLLED",
    "FACE_DELETED",
    "SERVICE_AUTH_FAILED",
    "SERVICE_AUTH_SUCCESS",
    "CAMERA_CREATED",
    "CAMERA_UPDATED",
    "CAMERA_DELETED",
    "SPOOF_ATTEMPT",
    "STUDENT_DELETED",
    "REGISTRATION_APPROVED",
    "REGISTRATION_REJECTED",
    "PHOTO_CHANGE_APPROVED",
    "PHOTO_CHANGE_REJECTED",
    "ADMIN_BOOTSTRAPPED",
    "PASSWORD_CHANGED",
    "PASSWORD_RESET",
    "ACCOUNT_CREATED",
    "ACCOUNT_UPDATED",
    "STUDENT_ID_CHANGED",
    "TEACHER_DELETED",
    "ADMIN_DELETED",
    "TEST_ACCOUNT_REMOVED",
]

AuditResourceType = Literal[
    "USER",
    "SESSION",
    "SESSION_ROSTER",
    "ATTENDANCE",
    "STUDENT_PROFILE",
    "BIOMETRIC_PROFILE",
    "SECURITY",
    "CAMERA",
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
