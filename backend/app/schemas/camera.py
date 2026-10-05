"""Pydantic schemas and utility helpers for Camera Registry and Telemetry."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import re
from typing import Any, Optional
import urllib.parse

from pydantic import BaseModel, ConfigDict, Field


class CameraRole(str, Enum):
    """Functional directional role of a camera relative to a classroom."""

    ENTRY = "ENTRY"
    EXIT = "EXIT"
    BOTH = "BOTH"


class CameraSourceType(str, Enum):
    """Supported ingestion source modalities."""

    RTSP = "RTSP"
    WEBRTC = "WEBRTC"
    PHONE = "PHONE"
    FILE = "FILE"


class CameraStatus(str, Enum):
    """Operational health state of a camera stream."""

    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"
    UNKNOWN = "UNKNOWN"


def mask_rtsp_url(url: str | None) -> str | None:
    """Mask credentials in an RTSP URL so passwords never leak in logs or responses.

    Example:
        rtsp://admin:secret123@192.168.1.100:554/stream -> rtsp://admin:*****@192.168.1.100:554/stream
    """
    if not url:
        return None

    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.password is not None:
            username = parsed.username or ""
            port_part = f":{parsed.port}" if parsed.port is not None else ""
            masked_netloc = f"{username}:*****@{parsed.hostname}{port_part}"
            return urllib.parse.urlunsplit(
                (
                    parsed.scheme,
                    masked_netloc,
                    parsed.path,
                    parsed.query,
                    parsed.fragment,
                )
            )
        return url
    except Exception:
        return re.sub(r":([^/@:]+)@", ":*****@", url)


class CameraBase(BaseModel):
    """Base fields for camera configuration."""

    classroom_id: str = Field(
        ..., min_length=1, description="Classroom identifier this camera monitors"
    )
    role: CameraRole = Field(
        default=CameraRole.BOTH, description="Directional filter: ENTRY, EXIT, or BOTH"
    )
    source_type: CameraSourceType = Field(
        default=CameraSourceType.RTSP, description="Ingestion protocol"
    )
    secret_reference: Optional[str] = Field(
        default=None, description="Optional secret reference/vault key"
    )
    enabled: bool = Field(default=True, description="Whether camera ingestion is actively enabled")
    boundary_config: Optional[dict[str, Any]] = Field(
        default=None, description="Virtual boundary line configuration"
    )
    notes: Optional[str] = Field(
        default=None, description="Administrative notes or installation details"
    )


class CameraCreate(CameraBase):
    """Payload to register a new camera in the registry."""

    model_config = ConfigDict(extra="forbid")

    camera_id: str = Field(..., min_length=1, max_length=64, description="Unique logical camera ID")
    rtsp_url: Optional[str] = Field(
        default=None, description="Raw RTSP ingestion URL (credentials encrypted/masked)"
    )


class CameraUpdate(BaseModel):
    """Payload to update an existing camera configuration."""

    model_config = ConfigDict(extra="forbid")

    classroom_id: Optional[str] = Field(default=None, min_length=1)
    role: Optional[CameraRole] = None
    source_type: Optional[CameraSourceType] = None
    rtsp_url: Optional[str] = None
    secret_reference: Optional[str] = None
    enabled: Optional[bool] = None
    boundary_config: Optional[dict[str, Any]] = None
    notes: Optional[str] = None


class CameraResponse(BaseModel):
    """Sanitized public camera representation returned via API. Never leaks plaintext credentials."""

    model_config = ConfigDict(extra="ignore")

    camera_id: str
    classroom_id: str
    role: CameraRole
    source_type: CameraSourceType
    rtsp_url_masked: Optional[str] = None
    secret_reference: Optional[str] = None
    enabled: bool
    boundary_config: Optional[dict[str, Any]] = None
    notes: Optional[str] = None
    status: CameraStatus = CameraStatus.UNKNOWN
    last_seen: Optional[datetime] = None
    fps: Optional[float] = None
    created_at: datetime
    updated_at: datetime


class CameraHeartbeat(BaseModel):
    """Heartbeat telemetry payload submitted by the Vision Service / camera worker."""

    model_config = ConfigDict(extra="forbid")

    camera_id: str = Field(..., min_length=1, description="Camera logical identifier")
    state: CameraStatus = Field(
        ..., description="Operational state: CONNECTED, DEGRADED, DISCONNECTED"
    )
    fps: float = Field(default=0.0, ge=0.0, description="Measured ingestion framerate")
    dropped_frames: int = Field(default=0, ge=0, description="Total dropped frame count")
    metadata: Optional[dict[str, Any]] = Field(
        default=None, description="Diagnostic telemetry (resolution, drops)"
    )


class CameraHeartbeatResponse(BaseModel):
    """Acknowledgment returned to Vision Service after recording a heartbeat."""

    status: str = "ok"
    camera_id: str
    state: CameraStatus
    received_at: datetime
