"""Service for computing live session presence snapshots, camera telemetry, and event feeds."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database.attendance import get_attendance_by_session
from app.database.cameras import list_cameras_from_db
from app.database.events import get_events_for_session
from app.database.session_roster import get_session_roster
from app.schemas.live_session import (
    CameraHealthItem,
    RecentLiveEvent,
    SessionLiveSnapshotResponse,
    SessionLiveState,
    StudentLiveItem,
    StudentLiveState,
)
from app.services.presence_engine import calculate_session_presence

logger = logging.getLogger(__name__)


def _to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def compute_session_live_snapshot(
    session: dict[str, Any],
    db: AsyncIOMotorDatabase,
    *,
    now: datetime | None = None,
) -> SessionLiveSnapshotResponse:
    """
    Compute real-time presence state, camera operational health, and recent events
    for a given attendance session.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    else:
        now = _to_utc(now)

    session_id = session["session_id"]
    course_name = session.get("course_name", "")
    classroom_id = session.get("classroom_id", "")
    status_field = session.get("status", "SCHEDULED")

    start_time = _to_utc(session["start_time"])
    end_time = _to_utc(session["end_time"])
    required_percentage = float(session.get("required_presence_percentage", 75.0))

    # Attendance rows exist from the moment a session starts (ABSENT placeholders,
    # live marks), so only a finalized session status makes them final.
    is_finalized = status_field in {"COMPLETED", "FINALIZED"}
    finalized_records: dict[str, dict] = {}
    if is_finalized:
        recs = await get_attendance_by_session(session_id)
        finalized_records = {r["identity"]: r for r in recs} if recs else {}

    # 1. Determine Session State
    if is_finalized:
        session_state: SessionLiveState = "ENDED"
        status_field = "COMPLETED"
    elif now < start_time:
        session_state = "UPCOMING"
    elif now <= end_time:
        session_state = "LIVE"
    else:
        session_state = "ENDED"

    total_duration_seconds = max((end_time - start_time).total_seconds(), 1.0)
    remaining_seconds = (
        max((end_time - now).total_seconds(), 0.0) if session_state == "LIVE" else 0.0
    )
    required_seconds = (required_percentage / 100.0) * total_duration_seconds

    # 2. Camera Telemetry for Classroom
    cameras_db = await list_cameras_from_db(classroom_id=classroom_id, enabled_only=True, db=db)
    camera_items: list[CameraHealthItem] = []
    any_camera_active = False

    for cam in cameras_db:
        cam_id = cam["camera_id"]
        cam_status = cam.get("status", "UNKNOWN")
        cam_role = cam.get("role")
        cam_fps = cam.get("fps")
        last_seen = _to_utc(cam.get("last_seen"))

        heartbeat_age_seconds: float | None = None
        is_cam_stale = False

        if last_seen is not None:
            heartbeat_age_seconds = max((now - last_seen).total_seconds(), 0.0)
            if heartbeat_age_seconds > 15.0:
                is_cam_stale = True

        if cam_status == "CONNECTED" and not is_cam_stale:
            any_camera_active = True

        camera_items.append(
            CameraHealthItem(
                camera_id=cam_id,
                classroom_id=classroom_id,
                status=cam_status,
                role=cam_role,
                fps=cam_fps,
                last_seen=last_seen,
                heartbeat_age_seconds=heartbeat_age_seconds,
                is_stale=is_cam_stale,
            )
        )

    # If session is live and has cameras, check if cameras are unreachable/stale
    is_session_stale = False
    if session_state == "LIVE" and camera_items:
        is_session_stale = not any_camera_active

    # 3. Retrieve Roster and Events
    roster_doc = await get_session_roster(session_id)
    rostered_set = set(roster_doc.identities) if roster_doc else set()

    raw_events = await get_events_for_session(
        session_id=session_id,
        session_start=start_time,
        session_end=end_time,
        db=db,
    )
    events: list[dict] = []
    for ev in raw_events:
        ev_dict = dict(ev)
        ev_dict["timestamp"] = _to_utc(ev_dict.get("timestamp"))
        events.append(ev_dict)

    # Group events by identity
    events_by_student: dict[str, list[dict]] = {}
    for ev in events:
        ident = ev.get("identity")
        if ident:
            events_by_student.setdefault(ident, []).append(ev)

    all_identities = sorted(
        list(rostered_set | set(events_by_student.keys()) | set(finalized_records.keys()))
    )

    # 5. Compute Student Presence Items
    student_items: list[StudentLiveItem] = []

    for identity in all_identities:
        is_rostered = identity in rostered_set
        student_events = events_by_student.get(identity, [])

        if identity in finalized_records:
            # Session is completed and finalized
            rec = finalized_records[identity]
            dur = float(rec.get("presence_duration_seconds", 0.0))
            pct = float(rec.get("presence_percentage", 0.0))
            stat = rec.get("status", "ABSENT")
            anomalies = list(rec.get("anomalies", []))

            student_items.append(
                StudentLiveItem(
                    identity=identity,
                    is_rostered=is_rostered,
                    state="OUTSIDE" if dur > 0 else "NOT_SEEN",
                    last_event_time=_to_utc(student_events[-1]["timestamp"])
                    if student_events
                    else None,
                    last_event_direction=student_events[-1]["direction"]
                    if student_events
                    else None,
                    presence_duration_seconds=dur,
                    presence_percentage=pct,
                    projected_status=stat,
                    is_on_track=stat == "PRESENT",
                    no_exit_observed="MISSING_EXIT" in anomalies,
                    anomalies=anomalies,
                )
            )
            continue

        if not student_events:
            # Student not seen
            is_on_track = (
                (remaining_seconds >= required_seconds) if session_state == "LIVE" else False
            )
            student_items.append(
                StudentLiveItem(
                    identity=identity,
                    is_rostered=is_rostered,
                    state="NOT_SEEN",
                    last_event_time=None,
                    last_event_direction=None,
                    presence_duration_seconds=0.0,
                    presence_percentage=0.0,
                    projected_status="PRESENT" if required_percentage == 0.0 else "ABSENT",
                    is_on_track=is_on_track,
                    no_exit_observed=False,
                    anomalies=[],
                )
            )
            continue

        # Sort student events chronologically
        sorted_evs = sorted(student_events, key=lambda x: _to_utc(x["timestamp"]))
        last_event = sorted_evs[-1]
        last_time = _to_utc(last_event["timestamp"])
        last_dir = last_event["direction"]

        # Run presence engine over existing events
        pres_res = calculate_session_presence(
            sorted_evs,
            session_start=start_time,
            session_end=end_time,
            cap_missing_exit=False,
        )

        closed_seconds = pres_res.total_presence_seconds
        anomalies = list(pres_res.anomalies)

        # Check if student is currently inside (unclosed ENTRY)
        if last_dir == "ENTRY":
            state: StudentLiveState = "INSIDE"
            no_exit_observed = True
            # Active interval calculation
            entry_effective = max(last_time, start_time)
            end_effective = min(now, end_time)
            active_seconds = max((end_effective - entry_effective).total_seconds(), 0.0)
            total_presence = closed_seconds + active_seconds
        else:
            state = "OUTSIDE"
            no_exit_observed = False
            total_presence = closed_seconds

        presence_percentage = min(
            round((total_presence / total_duration_seconds) * 100.0, 1), 100.0
        )
        projected_status = "PRESENT" if presence_percentage >= required_percentage else "ABSENT"

        max_potential_presence = total_presence + remaining_seconds
        is_on_track = max_potential_presence >= required_seconds

        student_items.append(
            StudentLiveItem(
                identity=identity,
                is_rostered=is_rostered,
                state=state,
                last_event_time=last_time,
                last_event_direction=last_dir,
                presence_duration_seconds=round(total_presence, 1),
                presence_percentage=presence_percentage,
                projected_status=projected_status,
                is_on_track=is_on_track,
                no_exit_observed=no_exit_observed,
                anomalies=anomalies,
            )
        )

    # Sort students: rostered first, then by identity
    student_items.sort(key=lambda s: (not s.is_rostered, s.identity))

    # 6. Bounded Recent Events Feed (Newest First, max 20)
    sorted_all_events = sorted(events, key=lambda x: _to_utc(x["timestamp"]), reverse=True)[:20]
    recent_events: list[RecentLiveEvent] = []

    for ev in sorted_all_events:
        ev_id = str(ev.get("event_id") or ev.get("_id") or "")
        recent_events.append(
            RecentLiveEvent(
                event_id=ev_id,
                identity=ev["identity"],
                direction=ev["direction"],
                timestamp=_to_utc(ev["timestamp"]),
                camera_id=ev.get("camera_id"),
                confidence=ev.get("confidence"),
            )
        )

    return SessionLiveSnapshotResponse(
        session_id=session_id,
        course_name=course_name,
        classroom_id=classroom_id,
        session_state=session_state,
        status=status_field,
        start_time=start_time,
        end_time=end_time,
        required_presence_percentage=required_percentage,
        cameras=camera_items,
        students=student_items,
        recent_events=recent_events,
        server_time=now,
        is_stale=is_session_stale,
    )
