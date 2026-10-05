from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


EventDirection = Literal["ENTRY", "EXIT"]


@dataclass
class PresenceInterval:
    entry_time: datetime
    exit_time: datetime

    @property
    def duration_seconds(self) -> float:
        return (self.exit_time - self.entry_time).total_seconds()


@dataclass
class PresenceResult:
    intervals: list[PresenceInterval]
    total_presence_seconds: float
    requires_review: bool = False
    anomalies: list[str] = field(default_factory=list)


def calculate_presence(
    events: list[dict],
    session_start: Optional[datetime] = None,
    session_end: Optional[datetime] = None,
    cap_missing_exit: bool = False,
) -> PresenceResult:
    """
    Convert chronological ENTRY/EXIT events into presence intervals.

    Events must contain:
        - direction
        - timestamp

    Events are sorted chronologically before processing.
    Detects anomalies (EXIT without ENTRY, MISSING_EXIT) and flags for review.
    """

    sorted_events = sorted(
        events,
        key=lambda event: event["timestamp"],
    )

    intervals: list[PresenceInterval] = []
    open_entry: datetime | None = None
    anomalies: list[str] = []
    requires_review: bool = False

    for event in sorted_events:
        direction: EventDirection = event["direction"]
        timestamp: datetime = event["timestamp"]

        if direction == "ENTRY":
            if open_entry is None:
                open_entry = timestamp

        elif direction == "EXIT":
            if open_entry is not None:
                if timestamp > open_entry:
                    intervals.append(
                        PresenceInterval(
                            entry_time=open_entry,
                            exit_time=timestamp,
                        )
                    )

                open_entry = None
            else:
                if "EXIT_WITHOUT_ENTRY" not in anomalies:
                    anomalies.append("EXIT_WITHOUT_ENTRY")
                requires_review = True

    # Check for unclosed ENTRY at end of events
    if open_entry is not None:
        if "MISSING_EXIT" not in anomalies:
            anomalies.append("MISSING_EXIT")
        requires_review = True

        if cap_missing_exit and session_end is not None and session_end > open_entry:
            intervals.append(
                PresenceInterval(
                    entry_time=open_entry,
                    exit_time=session_end,
                )
            )

    total_presence_seconds = sum(interval.duration_seconds for interval in intervals)

    return PresenceResult(
        intervals=intervals,
        total_presence_seconds=total_presence_seconds,
        requires_review=requires_review,
        anomalies=anomalies,
    )


def calculate_session_presence(
    events: list[dict],
    session_start: datetime,
    session_end: datetime,
    cap_missing_exit: bool = False,
) -> PresenceResult:
    """
    Calculate presence while clamping all intervals
    to the boundaries of the attendance session.
    """

    if session_end <= session_start:
        raise ValueError("session_end must be after session_start")

    result = calculate_presence(
        events,
        session_start=session_start,
        session_end=session_end,
        cap_missing_exit=cap_missing_exit,
    )

    clamped_intervals: list[PresenceInterval] = []

    for interval in result.intervals:
        clamped_entry = max(interval.entry_time, session_start)
        clamped_exit = min(interval.exit_time, session_end)

        if clamped_exit > clamped_entry:
            clamped_intervals.append(
                PresenceInterval(
                    entry_time=clamped_entry,
                    exit_time=clamped_exit,
                )
            )

    total_presence_seconds = sum(interval.duration_seconds for interval in clamped_intervals)

    return PresenceResult(
        intervals=clamped_intervals,
        total_presence_seconds=total_presence_seconds,
        requires_review=result.requires_review,
        anomalies=result.anomalies,
    )


def calculate_presence_percentage(
    total_presence_seconds: float,
    session_start: datetime,
    session_end: datetime,
) -> float:
    """Calculate percentage of the session attended."""

    session_duration_seconds = (session_end - session_start).total_seconds()

    if session_duration_seconds <= 0:
        raise ValueError("session_end must be after session_start")

    percentage = (total_presence_seconds / session_duration_seconds) * 100

    return min(max(percentage, 0.0), 100.0)


AttendanceStatus = Literal["PRESENT", "ABSENT"]


def determine_attendance_status(
    presence_percentage: float,
    required_presence_percentage: float,
) -> AttendanceStatus:
    """Determine attendance status using the session requirement."""

    if not 0.0 <= presence_percentage <= 100.0:
        raise ValueError("presence_percentage must be between 0 and 100")

    if not 0.0 <= required_presence_percentage <= 100.0:
        raise ValueError("required_presence_percentage must be between 0 and 100")

    if presence_percentage >= required_presence_percentage:
        return "PRESENT"

    return "ABSENT"
