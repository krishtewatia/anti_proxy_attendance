"""ENTRY and EXIT rounds of timetable sessions, and the lectures they give.

Names and numbers are made up; the vision service is stubbed.
"""

from datetime import datetime, timedelta, timezone

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.database import mongodb
from app.database.mongodb import init_indexes
from app.main import app
from app.services import organisation_service as org
from app.services.rounds_service import lectures
from tests.test_enrolment_requests import COHORT, SHEET
from tests.test_teaching import DAYS, MONDAY, _students, _user


@pytest.fixture(autouse=True)
async def fresh_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await init_indexes(db)
    await org.seed_structure(db)
    version = await org.import_timetable(db, COHORT, SHEET, source_name="ds3.csv", actor_user_id="seed")
    await org.activate_version(db, version["version_id"], MONDAY, actor_user_id="seed")
    yield
    mongodb._client = AsyncMongoMockClient()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.parametrize(
    ("periods", "entry", "exit_", "held", "expected"),
    [
        (1, True, True, ["ENTRY", "EXIT"], ["P"]),
        (1, True, False, ["ENTRY", "EXIT"], ["A"]),
        (1, False, True, ["ENTRY", "EXIT"], ["A"]),
        (1, False, False, ["ENTRY", "EXIT"], ["A"]),
        (2, True, True, ["ENTRY", "EXIT"], ["P", "P"]),
        (2, True, False, ["ENTRY", "EXIT"], ["P", "A"]),
        (2, False, True, ["ENTRY", "EXIT"], ["A", "P"]),
        (2, False, False, ["ENTRY", "EXIT"], ["A", "A"]),
        # A round never held: the held round counts for both.
        (1, True, False, ["ENTRY"], ["P"]),
        (2, True, False, ["ENTRY"], ["P", "P"]),
        (2, False, True, ["EXIT"], ["P", "P"]),
        (2, False, False, [], ["A", "A"]),
    ],
)
@pytest.mark.anyio
async def test_the_lecture_rule(periods, entry, exit_, held, expected):
    assert lectures(periods, entry, exit_, held) == expected


async def _session(client, periods: int, section: str = "B"):
    """A started timetable session with `periods` periods, its teacher and roster."""
    admin = await _user("admin_r", "ADMIN")
    db = mongodb.get_database()
    slot = await db[org.SLOTS].find_one({"audience.section": section, "periods": periods})
    teacher = await _user(f"t_{section}{periods}", "TEACHER")
    roster = await _students(section, 2)
    await client.put(f"/api/v1/admin/org/classes/{slot['class_id']}/teachers", headers=admin, json={"teacher_ids": [f"t_{section}{periods}"]})
    day = MONDAY + timedelta(days=DAYS.index(slot["day"]))
    started = (await client.post("/api/v1/teachers/sessions/from-slot", headers=teacher, json={"slot_id": slot["slot_id"], "date": day.isoformat()})).json()
    await client.post(f"/api/v1/sessions/{started['session_id']}/start", headers=teacher)
    return started["session_id"], teacher, admin, roster


async def _record(session_id: str, identity: str) -> dict:
    return await mongodb.get_database()["attendance_records"].find_one({"session_id": session_id, "identity": identity})


@pytest.mark.anyio
async def test_frames_mark_only_the_open_round_and_lectures_follow(vision_frames):
    async with _client() as client:
        session_id, teacher, _, roster = await _session(client, periods=2)
        frame_url = f"/api/v1/attendance/{session_id}/process-frame"
        vision_frames.faces = [vision_frames.recognized(session_id, roster[0])]
        before_any_round = (await client.post(frame_url, headers=teacher, content=b"f")).json()["faces"][0]
        await client.post(f"/api/v1/sessions/{session_id}/rounds/ENTRY/open", headers=teacher)
        vision_frames.faces = [vision_frames.recognized(session_id, roster[0])]
        entry = (await client.post(frame_url, headers=teacher, content=b"f")).json()["faces"][0]
        after_entry = await _record(session_id, roster[0])
        await client.post(f"/api/v1/sessions/{session_id}/rounds/EXIT/open", headers=teacher)
        vision_frames.faces = [vision_frames.recognized(session_id, roster[1])]
        await client.post(frame_url, headers=teacher, content=b"f")
        view = (await client.get(f"/api/v1/attendance/{session_id}", headers=teacher)).json()
        csv = (await client.get(f"/api/v1/attendance/{session_id}/export", headers=teacher)).text

    assert before_any_round["mark_status"] == "rejected" and before_any_round["mark_reason"] == "no_round_open"
    assert before_any_round["name"] != "UNKNOWN"  # the face is still shown
    assert entry["mark_status"] == "marked"
    # Only ENTRY held so far: it counts for both lectures.
    assert after_entry["lectures"] == ["P", "P"] and after_entry["status"] == "PRESENT"
    lectures_by = {r["identity"]: r["lectures"] for r in view["records"]}
    assert lectures_by == {roster[0]: ["P", "A"], roster[1]: ["A", "P"]}
    assert view["round_info"]["open_round"] == "EXIT" and view["round_info"]["held"] == ["ENTRY", "EXIT"]
    assert view["round_info"]["periods"] == 2 and view["round_info"]["teacher_may_edit"] is True
    lines = csv.strip().splitlines()
    assert lines[0] == "Roll No,Student Name,ENTRY,ENTRY time,EXIT,EXIT time,Lectures"
    assert {line.split(",")[2] + line.split(",")[4] + line.split(",")[6] for line in lines[1:]} == {"PA1/2", "AP1/2"}


@pytest.mark.anyio
async def test_a_single_period_needs_both_rounds_and_manual_marks_lock_the_round(vision_frames):
    db = mongodb.get_database()
    async with _client() as client:
        session_id, teacher, _, roster = await _session(client, periods=1)
        await client.post(f"/api/v1/sessions/{session_id}/rounds/ENTRY/open", headers=teacher)
        vision_frames.faces = [vision_frames.recognized(session_id, roster[0])]
        await client.post(f"/api/v1/attendance/{session_id}/process-frame", headers=teacher, content=b"f")
        await client.post(f"/api/v1/sessions/{session_id}/rounds/EXIT/open", headers=teacher)
        only_entry = await _record(session_id, roster[0])
        # Marked absent by hand in EXIT: recognition may not override it.
        manual = await client.post(f"/api/v1/sessions/{session_id}/rounds/EXIT/marks", headers=teacher,
                                   json={"identity": roster[0], "status": "ABSENT", "reason": "left early"})
        vision_frames.faces = [vision_frames.recognized(session_id, roster[0])]
        locked = (await client.post(f"/api/v1/attendance/{session_id}/process-frame", headers=teacher, content=b"f")).json()["faces"][0]
        by_hand = await client.post(f"/api/v1/sessions/{session_id}/rounds/ENTRY/marks", headers=teacher,
                                    json={"identity": roster[1], "status": "PRESENT"})
        await client.post(f"/api/v1/sessions/{session_id}/rounds/EXIT/marks", headers=teacher,
                          json={"identity": roster[1], "status": "PRESENT"})
        not_rostered = await client.post(f"/api/v1/sessions/{session_id}/rounds/EXIT/marks", headers=teacher,
                                         json={"identity": "someone_else", "status": "PRESENT"})
        old_route = await client.patch(f"/api/v1/sessions/{session_id}/attendance/att_{session_id}_{roster[0]}", headers=teacher,
                                       json={"status": "PRESENT"})
    assert only_entry["lectures"] == ["A"]  # single period: ENTRY alone is not enough once EXIT is held
    assert manual.status_code == 200 and manual.json()["lectures"] == ["A"]
    assert locked["mark_status"] == "locked"
    assert by_hand.status_code == 200
    assert (await _record(session_id, roster[1]))["lectures"] == ["P"]
    assert not_rostered.status_code == 404
    assert old_route.status_code in (404, 405, 409)
    audit = await db["audit_events"].find_one({"action": "ATTENDANCE_CORRECTED", "metadata.round": "EXIT", "metadata.identity": roster[0]})
    assert audit["metadata"]["reason"] == "left early"


@pytest.mark.anyio
async def test_one_round_open_at_a_time_reopen_and_finalize_closes_it():
    db = mongodb.get_database()
    async with _client() as client:
        session_id, teacher, _, _ = await _session(client, periods=2)
        entry = (await client.post(f"/api/v1/sessions/{session_id}/rounds/ENTRY/open", headers=teacher)).json()
        exit_ = (await client.post(f"/api/v1/sessions/{session_id}/rounds/EXIT/open", headers=teacher)).json()
        reopen = (await client.post(f"/api/v1/sessions/{session_id}/rounds/ENTRY/open", headers=teacher)).json()
        close_wrong = await client.post(f"/api/v1/sessions/{session_id}/rounds/EXIT/close", headers=teacher)
        bad_round = await client.post(f"/api/v1/sessions/{session_id}/rounds/MIDDLE/open", headers=teacher)
        await client.post(f"/api/v1/sessions/{session_id}/finalize", headers=teacher)
        after = await db["sessions"].find_one({"session_id": session_id})
        closed_session = await client.post(f"/api/v1/sessions/{session_id}/rounds/EXIT/open", headers=teacher)
    assert entry["open_round"] == "ENTRY" and exit_["open_round"] == "EXIT"
    assert exit_["rounds"]["ENTRY"]["closed_at"] is not None
    assert reopen["open_round"] == "ENTRY" and reopen["rounds"]["ENTRY"]["times_opened"] == 2
    assert close_wrong.status_code == 409 and bad_round.status_code == 404
    assert after["status"] == "FINALIZED" and after["open_round"] is None
    assert closed_session.status_code == 409
    assert await db["audit_events"].count_documents({"action": "SESSION_ROUND_CHANGED"}) == 3


@pytest.mark.anyio
async def test_the_edit_window_and_the_admin_unlock():
    db = mongodb.get_database()
    async with _client() as client:
        session_id, teacher, admin, roster = await _session(client, periods=2)
        await client.post(f"/api/v1/sessions/{session_id}/finalize", headers=teacher)
        mark = {"identity": roster[0], "status": "PRESENT", "reason": "was there"}
        after_finalize = await client.post(f"/api/v1/sessions/{session_id}/rounds/ENTRY/marks", headers=teacher, json=mark)
        admin_no_reason = await client.post(f"/api/v1/sessions/{session_id}/rounds/ENTRY/marks", headers=admin, json={**mark, "reason": ""})
        admin_mark = await client.post(f"/api/v1/sessions/{session_id}/rounds/ENTRY/marks", headers=admin, json=mark)
        unlock = await client.post(f"/api/v1/admin/sessions/{session_id}/unlock", headers=admin)
        after_unlock = await client.post(f"/api/v1/sessions/{session_id}/rounds/EXIT/marks", headers=teacher, json=mark)
        teacher_unlock = await client.post(f"/api/v1/admin/sessions/{session_id}/unlock", headers=teacher)
        # Past the window (end of class + 48 h), without an unlock.
        await db["sessions"].update_one(
            {"session_id": session_id},
            {"$set": {"status": "ACTIVE", "unlocked_until": None, "end_time": datetime.now(timezone.utc) - timedelta(hours=49)}},
        )
        late = await client.post(f"/api/v1/sessions/{session_id}/rounds/EXIT/marks", headers=teacher, json=mark)
    # Ended, but within 48 h of the class end: the teacher may still correct it.
    assert after_finalize.status_code == 200
    assert admin_no_reason.status_code == 400 and admin_mark.status_code == 200
    assert unlock.status_code == 200 and after_unlock.status_code == 200
    assert teacher_unlock.status_code == 403
    assert late.status_code == 403
    assert await db["audit_events"].count_documents({"action": "SESSION_UNLOCKED"}) == 1
