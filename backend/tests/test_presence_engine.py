from datetime import datetime, timezone

from app.services.presence_engine import (
    calculate_presence,
    calculate_session_presence,
    calculate_presence_percentage,
    determine_attendance_status,
)


def test_single_entry_exit():
    events = [
        {
            "direction": "ENTRY",
            "timestamp": datetime(
                2026, 9, 29, 10, 0, tzinfo=timezone.utc
            ),
        },
        {
            "direction": "EXIT",
            "timestamp": datetime(
                2026, 9, 29, 10, 30, tzinfo=timezone.utc
            ),
        },
    ]

    result = calculate_presence(events)

    assert len(result.intervals) == 1
    assert result.total_presence_seconds == 30 * 60


def test_multiple_presence_intervals():
    events = [
        {
            "direction": "ENTRY",
            "timestamp": datetime(
                2026, 9, 29, 10, 0, tzinfo=timezone.utc
            ),
        },
        {
            "direction": "EXIT",
            "timestamp": datetime(
                2026, 9, 29, 10, 20, tzinfo=timezone.utc
            ),
        },
        {
            "direction": "ENTRY",
            "timestamp": datetime(
                2026, 9, 29, 10, 30, tzinfo=timezone.utc
            ),
        },
        {
            "direction": "EXIT",
            "timestamp": datetime(
                2026, 9, 29, 11, 0, tzinfo=timezone.utc
            ),
        },
    ]

    result = calculate_presence(events)

    assert len(result.intervals) == 2
    assert result.total_presence_seconds == 20 * 60 + 30 * 60


def test_duplicate_entry_is_ignored():
    events = [
        {
            "direction": "ENTRY",
            "timestamp": datetime(
                2026, 9, 29, 10, 0, tzinfo=timezone.utc
            ),
        },
        {
            "direction": "ENTRY",
            "timestamp": datetime(
                2026, 9, 29, 10, 5, tzinfo=timezone.utc
            ),
        },
        {
            "direction": "EXIT",
            "timestamp": datetime(
                2026, 9, 29, 10, 30, tzinfo=timezone.utc
            ),
        },
    ]

    result = calculate_presence(events)

    assert len(result.intervals) == 1
    assert result.total_presence_seconds == 30 * 60


def test_exit_without_entry_is_ignored():
    events = [
        {
            "direction": "EXIT",
            "timestamp": datetime(
                2026, 9, 29, 10, 30, tzinfo=timezone.utc
            ),
        }
    ]

    result = calculate_presence(events)

    assert len(result.intervals) == 0
    assert result.total_presence_seconds == 0


def test_events_are_sorted_before_processing():
    events = [
        {
            "direction": "EXIT",
            "timestamp": datetime(
                2026, 9, 29, 10, 30, tzinfo=timezone.utc
            ),
        },
        {
            "direction": "ENTRY",
            "timestamp": datetime(
                2026, 9, 29, 10, 0, tzinfo=timezone.utc
            ),
        },
    ]

    result = calculate_presence(events)

    assert len(result.intervals) == 1
    assert result.total_presence_seconds == 30 * 60


def test_session_presence_clamps_entry_before_session():
    session_start = datetime(
        2026, 9, 29, 10, 0, tzinfo=timezone.utc
    )
    session_end = datetime(
        2026, 9, 29, 11, 0, tzinfo=timezone.utc
    )

    events = [
        {
            "direction": "ENTRY",
            "timestamp": datetime(
                2026, 9, 29, 9, 50, tzinfo=timezone.utc
            ),
        },
        {
            "direction": "EXIT",
            "timestamp": datetime(
                2026, 9, 29, 10, 30, tzinfo=timezone.utc
            ),
        },
    ]

    result = calculate_session_presence(
        events,
        session_start,
        session_end,
    )

    assert len(result.intervals) == 1
    assert result.intervals[0].entry_time == session_start
    assert result.total_presence_seconds == 30 * 60


def test_session_presence_clamps_exit_after_session():
    session_start = datetime(
        2026, 9, 29, 10, 0, tzinfo=timezone.utc
    )
    session_end = datetime(
        2026, 9, 29, 11, 0, tzinfo=timezone.utc
    )

    events = [
        {
            "direction": "ENTRY",
            "timestamp": datetime(
                2026, 9, 29, 10, 30, tzinfo=timezone.utc
            ),
        },
        {
            "direction": "EXIT",
            "timestamp": datetime(
                2026, 9, 29, 11, 15, tzinfo=timezone.utc
            ),
        },
    ]

    result = calculate_session_presence(
        events,
        session_start,
        session_end,
    )

    assert len(result.intervals) == 1
    assert result.intervals[0].exit_time == session_end
    assert result.total_presence_seconds == 30 * 60


def test_presence_percentage():
    session_start = datetime(
        2026, 9, 29, 10, 0, tzinfo=timezone.utc
    )
    session_end = datetime(
        2026, 9, 29, 11, 0, tzinfo=timezone.utc
    )

    percentage = calculate_presence_percentage(
        total_presence_seconds=45 * 60,
        session_start=session_start,
        session_end=session_end,
    )

    assert percentage == 75.0


def test_presence_percentage_never_exceeds_100():
    session_start = datetime(
        2026, 9, 29, 10, 0, tzinfo=timezone.utc
    )
    session_end = datetime(
        2026, 9, 29, 11, 0, tzinfo=timezone.utc
    )

    percentage = calculate_presence_percentage(
        total_presence_seconds=90 * 60,
        session_start=session_start,
        session_end=session_end,
    )

    assert percentage == 100.0


def test_invalid_session_boundaries():
    session_start = datetime(
        2026, 9, 29, 11, 0, tzinfo=timezone.utc
    )
    session_end = datetime(
        2026, 9, 29, 10, 0, tzinfo=timezone.utc
    )

    events = []

    try:
        calculate_session_presence(
            events,
            session_start,
            session_end,
        )
        assert False
    except ValueError:
        pass


def test_attendance_status_present():
    status = determine_attendance_status(
        presence_percentage=80.0,
        required_presence_percentage=75.0,
    )

    assert status == "PRESENT"


def test_attendance_status_absent():
    status = determine_attendance_status(
        presence_percentage=60.0,
        required_presence_percentage=75.0,
    )

    assert status == "ABSENT"


def test_attendance_status_exact_threshold():
    status = determine_attendance_status(
        presence_percentage=75.0,
        required_presence_percentage=75.0,
    )

    assert status == "PRESENT"


def test_attendance_status_invalid_presence_percentage():
    try:
        determine_attendance_status(
            presence_percentage=101.0,
            required_presence_percentage=75.0,
        )
        assert False
    except ValueError:
        pass


def test_attendance_status_invalid_required_percentage():
    try:
        determine_attendance_status(
            presence_percentage=80.0,
            required_presence_percentage=101.0,
        )
        assert False
    except ValueError:
        pass
