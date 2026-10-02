from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.services.session_resolution_service import (
    clear_camera_registry,
    find_active_session_for_classroom,
    register_camera_classroom,
    resolve_classroom_for_camera,
)


# ==============================================================================
# 1. Camera to Classroom Resolver Unit Tests
# ==============================================================================


def test_resolve_classroom_default_mappings():
    """Verify pre-registered default camera to classroom mappings."""
    clear_camera_registry()

    assert resolve_classroom_for_camera("CAM_ROOM_101_DOOR") == "ROOM_101"
    assert resolve_classroom_for_camera("CAM_ROOM_101") == "ROOM_101"
    assert resolve_classroom_for_camera("cam_01") == "ROOM_101"
    assert resolve_classroom_for_camera("cam_entrance") == "ROOM_101"


def test_resolve_classroom_convention_parsing():
    """Verify pattern parsing for CAM_<CLASSROOM>_<LOCATION> conventions."""
    clear_camera_registry()

    # Prefixes with suffixes
    assert resolve_classroom_for_camera("CAM_LAB-3_DOOR") == "LAB-3"
    assert resolve_classroom_for_camera("CAM_ROOM_204_ENTRANCE") == "ROOM_204"
    assert resolve_classroom_for_camera("CAM_AUD_1_EXIT") == "AUD_1"
    assert resolve_classroom_for_camera("CAM_HALL_B_FRONT") == "HALL_B"
    assert resolve_classroom_for_camera("CAM_HALL_B_BACK") == "HALL_B"

    # Prefixes without location suffix
    assert resolve_classroom_for_camera("CAM_LAB-3") == "LAB-3"
    assert resolve_classroom_for_camera("CAM_AUD-1") == "AUD-1"

    # Bare classroom IDs (pass through)
    assert resolve_classroom_for_camera("ROOM_101") == "ROOM_101"
    assert resolve_classroom_for_camera("LAB-3") == "LAB-3"

    # Empty string
    assert resolve_classroom_for_camera("") == ""


def test_register_custom_camera_mapping():
    """Verify runtime dynamic camera registration."""
    clear_camera_registry()

    register_camera_classroom("CAMERA_EXTERNAL_GATE", "SPECIAL_ROOM")
    assert resolve_classroom_for_camera("CAMERA_EXTERNAL_GATE") == "SPECIAL_ROOM"

    # Reset
    clear_camera_registry()
    assert resolve_classroom_for_camera("CAMERA_EXTERNAL_GATE") == "CAMERA_EXTERNAL_GATE"


# ==============================================================================
# 2. find_active_session_for_classroom Unit & Integration Tests
# ==============================================================================


@pytest.fixture(autouse=True)
def setup_test_db():
    mongodb._client = AsyncMongoMockClient()
    clear_camera_registry()
    yield
    clear_camera_registry()


@pytest.mark.anyio
async def test_matching_classroom_within_session_window():
    """Matching classroom within session window returns the active session."""
    db = mongodb.get_database()

    start_time = datetime(2026, 10, 15, 10, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2026, 10, 15, 11, 30, 0, tzinfo=timezone.utc)

    session_doc = {
        "session_id": "session_math_101",
        "course_name": "Mathematics 101",
        "classroom_id": "ROOM_101",
        "start_time": start_time,
        "end_time": end_time,
        "required_presence_percentage": 75.0,
        "status": "SCHEDULED",
        "created_by": "teacher_01",
    }
    await db["sessions"].insert_one(session_doc)

    # 10:45 UTC is squarely within the 10:00 - 11:30 window
    mid_session_ts = datetime(2026, 10, 15, 10, 45, 0, tzinfo=timezone.utc)

    active_session = await find_active_session_for_classroom(
        classroom_id="ROOM_101",
        timestamp=mid_session_ts,
    )

    assert active_session is not None
    assert active_session["session_id"] == "session_math_101"
    assert active_session["classroom_id"] == "ROOM_101"
    assert active_session["course_name"] == "Mathematics 101"


@pytest.mark.anyio
async def test_different_classroom_returns_none():
    """Same timestamp in a different classroom without a session returns None."""
    db = mongodb.get_database()

    start_time = datetime(2026, 10, 15, 10, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2026, 10, 15, 11, 30, 0, tzinfo=timezone.utc)

    await db["sessions"].insert_one({
        "session_id": "session_math_101",
        "course_name": "Mathematics 101",
        "classroom_id": "ROOM_101",
        "start_time": start_time,
        "end_time": end_time,
        "required_presence_percentage": 75.0,
        "status": "SCHEDULED",
        "created_by": "teacher_01",
    })

    mid_session_ts = datetime(2026, 10, 15, 10, 45, 0, tzinfo=timezone.utc)

    # Querying a different room: ROOM_102
    result = await find_active_session_for_classroom(
        classroom_id="ROOM_102",
        timestamp=mid_session_ts,
    )

    assert result is None


@pytest.mark.anyio
async def test_timestamp_before_session_returns_none():
    """Timestamp before session start_time returns None."""
    db = mongodb.get_database()

    start_time = datetime(2026, 10, 15, 10, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2026, 10, 15, 11, 30, 0, tzinfo=timezone.utc)

    await db["sessions"].insert_one({
        "session_id": "session_math_101",
        "course_name": "Mathematics 101",
        "classroom_id": "ROOM_101",
        "start_time": start_time,
        "end_time": end_time,
        "required_presence_percentage": 75.0,
        "status": "SCHEDULED",
        "created_by": "teacher_01",
    })

    # 1 second before session start
    before_ts = start_time - timedelta(seconds=1)

    result = await find_active_session_for_classroom(
        classroom_id="ROOM_101",
        timestamp=before_ts,
    )

    assert result is None


@pytest.mark.anyio
async def test_timestamp_after_session_returns_none():
    """Timestamp after session end_time returns None."""
    db = mongodb.get_database()

    start_time = datetime(2026, 10, 15, 10, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2026, 10, 15, 11, 30, 0, tzinfo=timezone.utc)

    await db["sessions"].insert_one({
        "session_id": "session_math_101",
        "course_name": "Mathematics 101",
        "classroom_id": "ROOM_101",
        "start_time": start_time,
        "end_time": end_time,
        "required_presence_percentage": 75.0,
        "status": "SCHEDULED",
        "created_by": "teacher_01",
    })

    # 1 second after session end
    after_ts = end_time + timedelta(seconds=1)

    result = await find_active_session_for_classroom(
        classroom_id="ROOM_101",
        timestamp=after_ts,
    )

    assert result is None


@pytest.mark.anyio
async def test_boundary_timestamps_handled_correctly():
    """Exact start_time and end_time timestamps are included in the session window."""
    db = mongodb.get_database()

    start_time = datetime(2026, 10, 15, 10, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2026, 10, 15, 11, 30, 0, tzinfo=timezone.utc)

    await db["sessions"].insert_one({
        "session_id": "session_math_101",
        "course_name": "Mathematics 101",
        "classroom_id": "ROOM_101",
        "start_time": start_time,
        "end_time": end_time,
        "required_presence_percentage": 75.0,
        "status": "SCHEDULED",
        "created_by": "teacher_01",
    })

    # Exact start boundary
    at_start = await find_active_session_for_classroom(
        classroom_id="ROOM_101",
        timestamp=start_time,
    )
    assert at_start is not None
    assert at_start["session_id"] == "session_math_101"

    # Exact end boundary
    at_end = await find_active_session_for_classroom(
        classroom_id="ROOM_101",
        timestamp=end_time,
    )
    assert at_end is not None
    assert at_end["session_id"] == "session_math_101"


@pytest.mark.anyio
async def test_multiple_concurrent_sessions_isolated_by_classroom():
    """Concurrent sessions in different classrooms resolve independently."""
    db = mongodb.get_database()

    start_time = datetime(2026, 10, 15, 10, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2026, 10, 15, 11, 30, 0, tzinfo=timezone.utc)

    # Session in Room 101
    await db["sessions"].insert_one({
        "session_id": "session_room101",
        "course_name": "Algorithms",
        "classroom_id": "ROOM_101",
        "start_time": start_time,
        "end_time": end_time,
        "required_presence_percentage": 75.0,
        "status": "SCHEDULED",
        "created_by": "teacher_01",
    })

    # Concurrent Session in Lab 3
    await db["sessions"].insert_one({
        "session_id": "session_lab3",
        "course_name": "Operating Systems",
        "classroom_id": "LAB-3",
        "start_time": start_time,
        "end_time": end_time,
        "required_presence_percentage": 75.0,
        "status": "SCHEDULED",
        "created_by": "teacher_02",
    })

    test_ts = datetime(2026, 10, 15, 10, 15, 0, tzinfo=timezone.utc)

    res_101 = await find_active_session_for_classroom("ROOM_101", test_ts)
    res_lab = await find_active_session_for_classroom("LAB-3", test_ts)

    assert res_101 is not None and res_101["session_id"] == "session_room101"
    assert res_lab is not None and res_lab["session_id"] == "session_lab3"


@pytest.mark.anyio
async def test_sequential_sessions_in_same_classroom():
    """Sequential sessions in the same classroom resolve according to timestamp."""
    db = mongodb.get_database()

    # Morning session: 09:00 - 10:30
    await db["sessions"].insert_one({
        "session_id": "session_morning",
        "course_name": "Physics 101",
        "classroom_id": "ROOM_101",
        "start_time": datetime(2026, 10, 15, 9, 0, 0, tzinfo=timezone.utc),
        "end_time": datetime(2026, 10, 15, 10, 30, 0, tzinfo=timezone.utc),
        "required_presence_percentage": 75.0,
        "status": "COMPLETED",
        "created_by": "teacher_01",
    })

    # Afternoon session: 11:00 - 12:30
    await db["sessions"].insert_one({
        "session_id": "session_afternoon",
        "course_name": "Chemistry 101",
        "classroom_id": "ROOM_101",
        "start_time": datetime(2026, 10, 15, 11, 0, 0, tzinfo=timezone.utc),
        "end_time": datetime(2026, 10, 15, 12, 30, 0, tzinfo=timezone.utc),
        "required_presence_percentage": 75.0,
        "status": "SCHEDULED",
        "created_by": "teacher_02",
    })

    # Morning timestamp
    res_morning = await find_active_session_for_classroom(
        "ROOM_101",
        datetime(2026, 10, 15, 9, 45, 0, tzinfo=timezone.utc),
    )
    assert res_morning is not None
    assert res_morning["session_id"] == "session_morning"

    # Gap between sessions: 10:45 -> None
    res_gap = await find_active_session_for_classroom(
        "ROOM_101",
        datetime(2026, 10, 15, 10, 45, 0, tzinfo=timezone.utc),
    )
    assert res_gap is None

    # Afternoon timestamp
    res_afternoon = await find_active_session_for_classroom(
        "ROOM_101",
        datetime(2026, 10, 15, 11, 15, 0, tzinfo=timezone.utc),
    )
    assert res_afternoon is not None
    assert res_afternoon["session_id"] == "session_afternoon"
