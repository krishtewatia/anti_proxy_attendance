from datetime import datetime, timezone

from app.services.presence_engine import (
    calculate_session_presence,
    calculate_presence_percentage,
    determine_attendance_status,
)


def test_real_cv_attendance_flow():
    """
    Integration-style test using the same ENTRY/EXIT event
    structure produced by the live CV pipeline.
    """

    session_start = datetime(
        2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc
    )

    session_end = datetime(
        2026, 9, 29, 11, 0, 0, tzinfo=timezone.utc
    )

    required_presence = 75.0

    # Representative structure of the events emitted by the
    # CV -> dispatcher -> FastAPI pipeline.
    person_01_events = [
        {
            "event_id": "evt_ba8b86418f6845d7",
            "camera_id": "CAM_ROOM_101_DOOR",
            "track_id": 7,
            "identity": "person_01",
            "direction": "ENTRY",
            "timestamp": datetime(
                2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc
            ),
        },
        {
            "event_id": "evt_6af3f4a0773c4242",
            "camera_id": "CAM_ROOM_101_DOOR",
            "track_id": 24,
            "identity": "person_01",
            "direction": "EXIT",
            "timestamp": datetime(
                2026, 9, 29, 10, 50, 0, tzinfo=timezone.utc
            ),
        },
    ]

    person_02_events = [
        {
            "event_id": "evt_48ca6e83b8f74970",
            "camera_id": "CAM_ROOM_101_DOOR",
            "track_id": 9,
            "identity": "person_02",
            "direction": "ENTRY",
            "timestamp": datetime(
                2026, 9, 29, 10, 5, 0, tzinfo=timezone.utc
            ),
        },
        {
            "event_id": "evt_3b86643bac5448d9",
            "camera_id": "CAM_ROOM_101_DOOR",
            "track_id": 25,
            "identity": "person_02",
            "direction": "EXIT",
            "timestamp": datetime(
                2026, 9, 29, 10, 35, 0, tzinfo=timezone.utc
            ),
        },
    ]

    # -------------------------
    # person_01
    # -------------------------

    result_01 = calculate_session_presence(
        person_01_events,
        session_start,
        session_end,
    )

    percentage_01 = calculate_presence_percentage(
        result_01.total_presence_seconds,
        session_start,
        session_end,
    )

    status_01 = determine_attendance_status(
        percentage_01,
        required_presence,
    )

    assert result_01.total_presence_seconds == 50 * 60
    assert percentage_01 == 50 / 60 * 100
    assert status_01 == "PRESENT"

    # -------------------------
    # person_02
    # -------------------------

    result_02 = calculate_session_presence(
        person_02_events,
        session_start,
        session_end,
    )

    percentage_02 = calculate_presence_percentage(
        result_02.total_presence_seconds,
        session_start,
        session_end,
    )

    status_02 = determine_attendance_status(
        percentage_02,
        required_presence,
    )

    assert result_02.total_presence_seconds == 30 * 60
    assert percentage_02 == 50.0
    assert status_02 == "ABSENT"
