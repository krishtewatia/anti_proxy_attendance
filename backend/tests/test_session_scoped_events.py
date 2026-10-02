"""Tests for Step 2C.9 Part 2: Session-Scoped Event Retrieval and Finalization."""

from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.core.config import settings
from app.database import mongodb
from app.database.events import get_events_for_session
from app.schemas.session_roster import SessionRoster
from app.services.session_finalization import finalize_session_attendance


@pytest.fixture(autouse=True)
def setup_test_db():
    mongodb._client = AsyncMongoMockClient()
    yield


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ==============================================================================
# 1. Direct get_events_for_session(session_id) Scoped Retrieval Tests
# ==============================================================================


@pytest.mark.anyio
async def test_get_events_for_session_retrieves_only_target_session():
    """Verify get_events_for_session(session_id) strictly isolates events by session_id."""
    db = mongodb.get_database()
    collection = db[settings.EVENTS_COLLECTION]

    session_a_id = "session_A_morning"
    session_b_id = "session_B_afternoon"

    events = [
        # Session A Events (Room 101, Morning)
        {
            "event_id": "evt_A_01",
            "session_id": session_a_id,
            "classroom_id": "ROOM_101",
            "identity": "person_01",
            "direction": "ENTRY",
            "timestamp": datetime(2026, 10, 20, 9, 5, tzinfo=timezone.utc),
        },
        {
            "event_id": "evt_A_02",
            "session_id": session_a_id,
            "classroom_id": "ROOM_101",
            "identity": "person_01",
            "direction": "EXIT",
            "timestamp": datetime(2026, 10, 20, 9, 55, tzinfo=timezone.utc),
        },
        # Session B Events (Room 101, Afternoon)
        {
            "event_id": "evt_B_01",
            "session_id": session_b_id,
            "classroom_id": "ROOM_101",
            "identity": "person_01",
            "direction": "ENTRY",
            "timestamp": datetime(2026, 10, 20, 11, 5, tzinfo=timezone.utc),
        },
        {
            "event_id": "evt_B_02",
            "session_id": session_b_id,
            "classroom_id": "ROOM_101",
            "identity": "person_01",
            "direction": "EXIT",
            "timestamp": datetime(2026, 10, 20, 11, 55, tzinfo=timezone.utc),
        },
    ]
    await collection.insert_many(events)

    # Query Session A
    events_a = await get_events_for_session(session_id=session_a_id)
    ids_a = [e["event_id"] for e in events_a]
    assert ids_a == ["evt_A_01", "evt_A_02"]

    # Query Session B
    events_b = await get_events_for_session(session_id=session_b_id)
    ids_b = [e["event_id"] for e in events_b]
    assert ids_b == ["evt_B_01", "evt_B_02"]


# ==============================================================================
# 2. Session Isolation in Finalization
# ==============================================================================


@pytest.mark.anyio
async def test_session_isolation_in_finalization():
    """
    Session A and Session B share the same room (ROOM_101) at different times.
    Finalizing Session A must calculate attendance strictly from Session A events,
    with zero contamination from Session B events.
    """
    db = mongodb.get_database()
    events_col = db[settings.EVENTS_COLLECTION]

    session_a_id = "session_A_0900"
    session_b_id = "session_B_1100"

    start_a = datetime(2026, 10, 20, 9, 0, 0, tzinfo=timezone.utc)
    end_a = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)

    start_b = datetime(2026, 10, 20, 11, 0, 0, tzinfo=timezone.utc)
    end_b = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)

    # Ingest events for both sessions into MongoDB
    await events_col.insert_many([
        # Session A: person_01 present from 09:05 to 09:55 (50 mins = 3000s)
        {
            "event_id": "evt_a_entry",
            "session_id": session_a_id,
            "classroom_id": "ROOM_101",
            "identity": "person_01",
            "direction": "ENTRY",
            "timestamp": start_a + timedelta(minutes=5),
        },
        {
            "event_id": "evt_a_exit",
            "session_id": session_a_id,
            "classroom_id": "ROOM_101",
            "identity": "person_01",
            "direction": "EXIT",
            "timestamp": start_a + timedelta(minutes=55),
        },
        # Session B: person_01 present from 11:10 to 11:25 (15 mins = 900s)
        {
            "event_id": "evt_b_entry",
            "session_id": session_b_id,
            "classroom_id": "ROOM_101",
            "identity": "person_01",
            "direction": "ENTRY",
            "timestamp": start_b + timedelta(minutes=10),
        },
        {
            "event_id": "evt_b_exit",
            "session_id": session_b_id,
            "classroom_id": "ROOM_101",
            "identity": "person_01",
            "direction": "EXIT",
            "timestamp": start_b + timedelta(minutes=25),
        },
    ])

    roster = SessionRoster(
        session_id=session_a_id,
        identities=["person_01"],
    )

    # Finalize Session A
    records_a = await finalize_session_attendance(
        session_id=session_a_id,
        session_start=start_a,
        session_end=end_a,
        required_presence_percentage=75.0,
        roster=roster,
    )

    assert len(records_a) == 1
    rec_a = records_a[0]
    assert rec_a["identity"] == "person_01"
    assert rec_a["session_id"] == session_a_id
    assert rec_a["presence_duration_seconds"] == 3000.0  # 50 min exactly
    assert round(rec_a["presence_percentage"], 2) == 83.33
    assert rec_a["status"] == "PRESENT"
    assert len(rec_a["presence_intervals"]) == 1

    # Finalize Session B
    roster_b = SessionRoster(
        session_id=session_b_id,
        identities=["person_01"],
    )
    records_b = await finalize_session_attendance(
        session_id=session_b_id,
        session_start=start_b,
        session_end=end_b,
        required_presence_percentage=75.0,
        roster=roster_b,
    )

    assert len(records_b) == 1
    rec_b = records_b[0]
    assert rec_b["identity"] == "person_01"
    assert rec_b["session_id"] == session_b_id
    assert rec_b["presence_duration_seconds"] == 900.0  # 15 min exactly
    assert round(rec_b["presence_percentage"], 2) == 25.0
    assert rec_b["status"] == "ABSENT"


# ==============================================================================
# 3. Core Presence Engine Cases Preserved
# ==============================================================================


@pytest.mark.anyio
async def test_entry_plus_exit_correct_presence_interval():
    """ENTRY + EXIT creates correct presence interval and duration."""
    db = mongodb.get_database()
    events_col = db[settings.EVENTS_COLLECTION]

    session_id = "session_entry_exit_test"
    start = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 20, 11, 0, 0, tzinfo=timezone.utc)

    await events_col.insert_many([
        {
            "event_id": "evt_norm_entry",
            "session_id": session_id,
            "identity": "person_01",
            "direction": "ENTRY",
            "timestamp": start + timedelta(minutes=10),
        },
        {
            "event_id": "evt_norm_exit",
            "session_id": session_id,
            "identity": "person_01",
            "direction": "EXIT",
            "timestamp": start + timedelta(minutes=40),
        },
    ])

    roster = SessionRoster(session_id=session_id, identities=["person_01"])

    records = await finalize_session_attendance(
        session_id=session_id,
        session_start=start,
        session_end=end,
        required_presence_percentage=50.0,
        roster=roster,
    )

    assert len(records) == 1
    rec = records[0]
    assert rec["presence_duration_seconds"] == 1800.0  # 30 mins
    assert round(rec["presence_percentage"], 2) == 50.0
    assert rec["status"] == "PRESENT"
    assert len(rec["presence_intervals"]) == 1
    assert _to_utc(rec["presence_intervals"][0]["entry_time"]) == start + timedelta(minutes=10)
    assert _to_utc(rec["presence_intervals"][0]["exit_time"]) == start + timedelta(minutes=40)


@pytest.mark.anyio
async def test_entry_without_exit_preserved():
    """ENTRY without subsequent EXIT is preserved with zero closed intervals."""
    db = mongodb.get_database()
    events_col = db[settings.EVENTS_COLLECTION]

    session_id = "session_no_exit_test"
    start = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 20, 11, 0, 0, tzinfo=timezone.utc)

    await events_col.insert_one({
        "event_id": "evt_unclosed_entry",
        "session_id": session_id,
        "identity": "person_01",
        "direction": "ENTRY",
        "timestamp": start + timedelta(minutes=5),
    })

    roster = SessionRoster(session_id=session_id, identities=["person_01"])

    records = await finalize_session_attendance(
        session_id=session_id,
        session_start=start,
        session_end=end,
        required_presence_percentage=75.0,
        roster=roster,
    )

    assert len(records) == 1
    rec = records[0]
    assert rec["presence_duration_seconds"] == 0.0
    assert rec["presence_percentage"] == 0.0
    assert rec["status"] == "ABSENT"
    assert rec["presence_intervals"] == []


@pytest.mark.anyio
async def test_duplicate_entry_ignored_appropriately():
    """Consecutive ENTRY events ignore the duplicate and use the initial entry."""
    db = mongodb.get_database()
    events_col = db[settings.EVENTS_COLLECTION]

    session_id = "session_dup_entry_test"
    start = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 20, 11, 0, 0, tzinfo=timezone.utc)

    await events_col.insert_many([
        {
            "event_id": "evt_dup_entry_1",
            "session_id": session_id,
            "identity": "person_01",
            "direction": "ENTRY",
            "timestamp": start + timedelta(minutes=5),  # First entry used
        },
        {
            "event_id": "evt_dup_entry_2",
            "session_id": session_id,
            "identity": "person_01",
            "direction": "ENTRY",
            "timestamp": start + timedelta(minutes=15),  # Ignored duplicate
        },
        {
            "event_id": "evt_dup_exit",
            "session_id": session_id,
            "identity": "person_01",
            "direction": "EXIT",
            "timestamp": start + timedelta(minutes=55),
        },
    ])

    roster = SessionRoster(session_id=session_id, identities=["person_01"])

    records = await finalize_session_attendance(
        session_id=session_id,
        session_start=start,
        session_end=end,
        required_presence_percentage=75.0,
        roster=roster,
    )

    assert len(records) == 1
    rec = records[0]
    # Interval starts at 10:05 and ends at 10:55 = 50 min = 3000s
    assert rec["presence_duration_seconds"] == 3000.0
    assert len(rec["presence_intervals"]) == 1
    assert _to_utc(rec["presence_intervals"][0]["entry_time"]) == start + timedelta(minutes=5)


@pytest.mark.anyio
async def test_exit_without_entry_ignored():
    """An EXIT event without an open ENTRY is ignored."""
    db = mongodb.get_database()
    events_col = db[settings.EVENTS_COLLECTION]

    session_id = "session_stray_exit_test"
    start = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 20, 11, 0, 0, tzinfo=timezone.utc)

    await events_col.insert_many([
        # Stray EXIT with no prior entry
        {
            "event_id": "evt_stray_exit",
            "session_id": session_id,
            "identity": "person_01",
            "direction": "EXIT",
            "timestamp": start + timedelta(minutes=2),
        },
        # Legitimate entry and exit
        {
            "event_id": "evt_real_entry",
            "session_id": session_id,
            "identity": "person_01",
            "direction": "ENTRY",
            "timestamp": start + timedelta(minutes=10),
        },
        {
            "event_id": "evt_real_exit",
            "session_id": session_id,
            "identity": "person_01",
            "direction": "EXIT",
            "timestamp": start + timedelta(minutes=50),
        },
    ])

    roster = SessionRoster(session_id=session_id, identities=["person_01"])

    records = await finalize_session_attendance(
        session_id=session_id,
        session_start=start,
        session_end=end,
        required_presence_percentage=50.0,
        roster=roster,
    )

    assert len(records) == 1
    rec = records[0]
    # Interval is 10:10 to 10:50 = 40 min = 2400s
    assert rec["presence_duration_seconds"] == 2400.0
    assert len(rec["presence_intervals"]) == 1
    assert _to_utc(rec["presence_intervals"][0]["entry_time"]) == start + timedelta(minutes=10)


@pytest.mark.anyio
async def test_student_on_roster_with_no_events_is_absent():
    """Student present on roster with zero events receives status ABSENT."""
    db = mongodb.get_database()
    events_col = db[settings.EVENTS_COLLECTION]

    session_id = "session_absent_test"
    start = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 20, 11, 0, 0, tzinfo=timezone.utc)

    # Only person_01 attended; person_02 did not attend
    await events_col.insert_many([
        {
            "event_id": "evt_p1_in",
            "session_id": session_id,
            "identity": "person_01",
            "direction": "ENTRY",
            "timestamp": start + timedelta(minutes=5),
        },
        {
            "event_id": "evt_p1_out",
            "session_id": session_id,
            "identity": "person_01",
            "direction": "EXIT",
            "timestamp": start + timedelta(minutes=55),
        },
    ])

    roster = SessionRoster(
        session_id=session_id,
        identities=["person_01", "person_02"],
    )

    records = await finalize_session_attendance(
        session_id=session_id,
        session_start=start,
        session_end=end,
        required_presence_percentage=75.0,
        roster=roster,
    )

    assert len(records) == 2
    rec_by_id = {r["identity"]: r for r in records}

    assert rec_by_id["person_01"]["status"] == "PRESENT"
    assert rec_by_id["person_02"]["status"] == "ABSENT"
    assert rec_by_id["person_02"]["presence_duration_seconds"] == 0.0
    assert rec_by_id["person_02"]["presence_percentage"] == 0.0
    assert rec_by_id["person_02"]["presence_intervals"] == []


@pytest.mark.anyio
async def test_non_roster_identity_does_not_create_attendance_record():
    """Camera events for an un-enrolled / non-roster identity produce no attendance record."""
    db = mongodb.get_database()
    events_col = db[settings.EVENTS_COLLECTION]

    session_id = "session_non_roster_test"
    start = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 20, 11, 0, 0, tzinfo=timezone.utc)

    # Events for enrolled person_01 and visitor guest_visitor_99
    await events_col.insert_many([
        {
            "event_id": "evt_p1_in",
            "session_id": session_id,
            "identity": "person_01",
            "direction": "ENTRY",
            "timestamp": start + timedelta(minutes=5),
        },
        {
            "event_id": "evt_p1_out",
            "session_id": session_id,
            "identity": "person_01",
            "direction": "EXIT",
            "timestamp": start + timedelta(minutes=55),
        },
        {
            "event_id": "evt_guest_in",
            "session_id": session_id,
            "identity": "guest_visitor_99",
            "direction": "ENTRY",
            "timestamp": start + timedelta(minutes=10),
        },
        {
            "event_id": "evt_guest_out",
            "session_id": session_id,
            "identity": "guest_visitor_99",
            "direction": "EXIT",
            "timestamp": start + timedelta(minutes=50),
        },
    ])

    roster = SessionRoster(
        session_id=session_id,
        identities=["person_01"],  # guest_visitor_99 is NOT on roster
    )

    records = await finalize_session_attendance(
        session_id=session_id,
        session_start=start,
        session_end=end,
        required_presence_percentage=75.0,
        roster=roster,
    )

    assert len(records) == 1
    assert records[0]["identity"] == "person_01"
    # Verify no record created for guest_visitor_99
    assert all(r["identity"] != "guest_visitor_99" for r in records)
