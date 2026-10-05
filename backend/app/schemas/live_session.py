"""Pydantic schemas for real-time live attendance session snapshots and telemetry."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


StudentLiveState = Literal["INSIDE", "OUTSIDE", "NOT_SEEN"]
SessionLiveState = Literal["UPCOMING", "LIVE", "ENDED"]


class StudentLiveItem(BaseModel):
    """Real-time presence and verification status for an individual student."""

    model_config = ConfigDict(extra="forbid")

    identity: str
    is_rostered: bool = True
    state: StudentLiveState
    last_event_time: Optional[datetime] = None
    last_event_direction: Optional[Literal["ENTRY", "EXIT"]] = None
    presence_duration_seconds: float = 0.0
    presence_percentage: float = 0.0
    projected_status: Literal["PRESENT", "ABSENT"] = "ABSENT"
    is_on_track: bool = False
    no_exit_observed: bool = False
    anomalies: list[str] = Field(default_factory=list)


class CameraHealthItem(BaseModel):
    """Operational health telemetry for a camera monitoring a session's classroom."""

    model_config = ConfigDict(extra="forbid")

    camera_id: str
    classroom_id: str
    status: str
    role: Optional[str] = None
    fps: Optional[float] = None
    last_seen: Optional[datetime] = None
    heartbeat_age_seconds: Optional[float] = None
    is_stale: bool = False


class RecentLiveEvent(BaseModel):
    """Recent event emitted by a vision worker or phone camera for the session."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    identity: str
    direction: Literal["ENTRY", "EXIT"]
    timestamp: datetime
    camera_id: Optional[str] = None
    confidence: Optional[float] = None


class SessionLiveSnapshotResponse(BaseModel):
    """Complete real-time snapshot of an ongoing, upcoming, or ended session."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    course_name: str
    classroom_id: str
    session_state: SessionLiveState
    status: str
    start_time: datetime
    end_time: datetime
    required_presence_percentage: float
    cameras: list[CameraHealthItem] = Field(default_factory=list)
    students: list[StudentLiveItem] = Field(default_factory=list)
    recent_events: list[RecentLiveEvent] = Field(default_factory=list)
    server_time: datetime
    is_stale: bool = False
