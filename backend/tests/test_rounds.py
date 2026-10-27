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
        await client.post(f"/api/v1/sessions/{session_id}/rounds/ENTRY/finalize", headers=teacher)
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
async def test_a_single_period_needs_both_rounds_and_hand_changes_wait_for_the_final_attendance(vision_frames):
    db = mongodb.get_database()
    async with _client() as client:
        session_id, teacher, admin, roster = await _session(client, periods=1)
        base = f"/api/v1/sessions/{session_id}"
        await client.post(f"{base}/rounds/ENTRY/open", headers=teacher)
        vision_frames.faces = [vision_frames.recognized(session_id, roster[0])]
        await client.post(f"/api/v1/attendance/{session_id}/process-frame", headers=teacher, content=b"f")
        # While a round runs only the camera marks: a teacher's hand change is refused.
        during_round = await client.post(f"{base}/rounds/ENTRY/marks", headers=teacher, json={"identity": roster[1], "status": "PRESENT"})
        await client.post(f"{base}/rounds/ENTRY/finalize", headers=teacher)
        await client.post(f"{base}/rounds/EXIT/open", headers=teacher)
        only_entry = await _record(session_id, roster[0])
        between_rounds = await client.post(f"{base}/rounds/ENTRY/marks", headers=teacher, json={"identity": roster[1], "status": "PRESENT"})
        # An administrator may correct at any time, with a reason; recognition never overrides it.
        admin_mark = await client.post(f"{base}/rounds/EXIT/marks", headers=admin, json={"identity": roster[0], "status": "ABSENT", "reason": "left early"})
        vision_frames.faces = [vision_frames.recognized(session_id, roster[0])]
        locked = (await client.post(f"/api/v1/attendance/{session_id}/process-frame", headers=teacher, content=b"f")).json()["faces"][0]
        await client.post(f"{base}/rounds/EXIT/finalize", headers=teacher)
        # Final attendance: now the teacher may change it by hand.
        by_hand = await client.post(f"{base}/rounds/ENTRY/marks", headers=teacher, json={"identity": roster[1], "status": "PRESENT"})
        await client.post(f"{base}/rounds/EXIT/marks", headers=teacher, json={"identity": roster[1], "status": "PRESENT"})
        not_rostered = await client.post(f"{base}/rounds/EXIT/marks", headers=teacher, json={"identity": "someone_else", "status": "PRESENT"})
        old_route = await client.patch(f"{base}/attendance/att_{session_id}_{roster[0]}", headers=teacher, json={"status": "PRESENT"})
    assert during_round.status_code == 409 and "both finalized" in during_round.json()["detail"]
    assert between_rounds.status_code == 409
    assert only_entry["lectures"] == ["A"]  # single period: ENTRY alone is not enough once EXIT is held
    assert admin_mark.status_code == 200 and admin_mark.json()["lectures"] == ["A"]
    assert locked["mark_status"] == "locked"
    assert by_hand.status_code == 200
    assert (await _record(session_id, roster[1]))["lectures"] == ["P"]
    assert not_rostered.status_code == 404
    assert old_route.status_code in (404, 405, 409)
    audit = await db["audit_events"].find_one({"action": "ATTENDANCE_CORRECTED", "metadata.round": "EXIT", "metadata.identity": roster[0]})
    assert audit["metadata"]["reason"] == "left early"


@pytest.mark.anyio
async def test_entry_then_exit_each_finalized_then_the_session():
    db = mongodb.get_database()
    async with _client() as client:
        session_id, teacher, _, _ = await _session(client, periods=2)
        base = f"/api/v1/sessions/{session_id}"
        entry = (await client.post(f"{base}/rounds/ENTRY/open", headers=teacher)).json()
        exit_too_soon = await client.post(f"{base}/rounds/EXIT/open", headers=teacher)
        await client.post(f"{base}/rounds/ENTRY/close", headers=teacher)
        reopen = (await client.post(f"{base}/rounds/ENTRY/open", headers=teacher)).json()
        session_too_soon = await client.post(f"{base}/finalize", headers=teacher)
        entry_done = (await client.post(f"{base}/rounds/ENTRY/finalize", headers=teacher)).json()
        reopen_finalized = await client.post(f"{base}/rounds/ENTRY/open", headers=teacher)
        exit_too_soon_again = await client.post(f"{base}/finalize", headers=teacher)
        exit_ = (await client.post(f"{base}/rounds/EXIT/open", headers=teacher)).json()
        exit_done = (await client.post(f"{base}/rounds/EXIT/finalize", headers=teacher)).json()
        view = (await client.get(f"/api/v1/attendance/{session_id}", headers=teacher)).json()
        finalized = await client.post(f"{base}/finalize", headers=teacher)
        bad_round = await client.post(f"{base}/rounds/MIDDLE/open", headers=teacher)
        after = await db["sessions"].find_one({"session_id": session_id})
    assert entry["open_round"] == "ENTRY" and reopen["rounds"]["ENTRY"]["times_opened"] == 2
    assert exit_too_soon.status_code == 409 and "Finalize ENTRY first" in exit_too_soon.json()["detail"]
    assert session_too_soon.status_code == 409 and exit_too_soon_again.status_code == 409
    assert entry_done["open_round"] is None and entry_done["rounds"]["ENTRY"]["finalized_at"]
    assert entry_done["next_step"] == "EXIT" and entry_done["rounds"]["ENTRY"]["may_edit"] is True
    assert reopen_finalized.status_code == 409 and "by hand" in reopen_finalized.json()["detail"]
    assert exit_["open_round"] == "EXIT"
    assert exit_done["complete"] is True and exit_done["next_step"] == "FINALIZE"
    assert view["round_info"]["complete"] is True
    assert finalized.status_code == 200 and after["status"] == "FINALIZED"
    assert bad_round.status_code == 404
    assert await db["audit_events"].count_documents({"action": "SESSION_ROUND_CHANGED", "metadata.finalized": True}) == 2


@pytest.mark.anyio
async def test_hand_changes_for_24_hours_after_a_round_is_finalized_then_locked():
    db = mongodb.get_database()
    async with _client() as client:
        session_id, teacher, admin, roster = await _session(client, periods=2)
        base = f"/api/v1/sessions/{session_id}"
        for rnd in ("ENTRY", "EXIT"):
            await client.post(f"{base}/rounds/{rnd}/open", headers=teacher)
            await client.post(f"{base}/rounds/{rnd}/finalize", headers=teacher)
        await client.post(f"{base}/finalize", headers=teacher)
        mark = {"identity": roster[0], "status": "PRESENT", "reason": "was there"}
        within = await client.post(f"{base}/rounds/ENTRY/marks", headers=teacher, json=mark)
        # ENTRY was finalized 25 h ago, EXIT just now: only EXIT may still change.
        stale = dict((await db["sessions"].find_one({"session_id": session_id}))["rounds"])
        stale["ENTRY"] = {**stale["ENTRY"], "finalized_at": datetime.now(timezone.utc) - timedelta(hours=25)}
        await db["sessions"].update_one({"session_id": session_id}, {"$set": {"rounds": stale}})
        entry_late = await client.post(f"{base}/rounds/ENTRY/marks", headers=teacher, json=mark)
        exit_still = await client.post(f"{base}/rounds/EXIT/marks", headers=teacher, json=mark)
        view = (await client.get(f"/api/v1/attendance/{session_id}", headers=teacher)).json()
        admin_no_reason = await client.post(f"{base}/rounds/ENTRY/marks", headers=admin, json={**mark, "reason": ""})
        admin_mark = await client.post(f"{base}/rounds/ENTRY/marks", headers=admin, json=mark)
        unlock = await client.post(f"/api/v1/admin/sessions/{session_id}/unlock", headers=admin)
        after_unlock = await client.post(f"{base}/rounds/ENTRY/marks", headers=teacher, json=mark)
        teacher_unlock = await client.post(f"/api/v1/admin/sessions/{session_id}/unlock", headers=teacher)
    assert within.status_code == 200
    assert entry_late.status_code == 403 and "24 h" in entry_late.json()["detail"]
    assert exit_still.status_code == 200
    assert view["round_info"]["rounds"]["ENTRY"]["may_edit"] is False and view["round_info"]["rounds"]["EXIT"]["may_edit"] is True
    assert admin_no_reason.status_code == 400 and admin_mark.status_code == 200
    assert unlock.status_code == 200 and after_unlock.status_code == 200
    assert teacher_unlock.status_code == 403
    assert await db["audit_events"].count_documents({"action": "SESSION_UNLOCKED"}) == 1


@pytest.mark.anyio
async def test_an_ended_class_can_be_finished_by_hand_within_24_hours_only():
    db = mongodb.get_database()
    async with _client() as client:
        session_id, teacher, _, _ = await _session(client, periods=1)
        base = f"/api/v1/sessions/{session_id}"
        await client.post(f"{base}/rounds/ENTRY/open", headers=teacher)
        # Ended automatically (the teacher started the next class): EXIT never taken.
        await db["sessions"].update_one(
            {"session_id": session_id},
            {"$set": {"status": "FINALIZED", "ended_automatically": True, "end_time": datetime.now(timezone.utc) - timedelta(hours=1)}},
        )
        entry_done = await client.post(f"{base}/rounds/ENTRY/finalize", headers=teacher)
        await db["sessions"].update_one(
            {"session_id": session_id}, {"$set": {"end_time": datetime.now(timezone.utc) - timedelta(hours=25)}}
        )
        exit_late = await client.post(f"{base}/rounds/EXIT/finalize", headers=teacher)
    assert entry_done.status_code == 200
    assert exit_late.status_code == 403


async def _late_student(section: str, n: int) -> str:
    """A student approved for every class of ``section`` after the class started."""
    from app.database.users import create_user

    db = mongodb.get_database()
    class_ids = [c["class_id"] async for c in db[org.CLASSES].find({"audience.section": section})]
    user_id, identity = f"late_{section}{n}", f"stu_late_{section.lower()}{n}"
    await create_user(user_id=user_id, email=f"{user_id}@niet.co.in", password_hash="x", role="STUDENT", status="APPROVED")
    await db["student_profiles"].insert_one(
        {"user_id": user_id, "identity": identity, "student_id": identity, "name": f"Late {section}{n}", "roll_number": f"77{ord(section)}{n:03d}"}
    )
    await db["enrolments"].insert_one({"user_id": user_id, "identity": identity, "section": section, "choices": {}, "class_ids": class_ids})
    return identity


@pytest.mark.anyio
async def test_a_student_approved_after_the_class_started_is_added_and_marked(vision_frames, monkeypatch):
    from app.services import recognition_service, teaching_service

    db = mongodb.get_database()
    recognition_service._NOT_IN_CLASS.clear()
    async with _client() as client:
        session_id, teacher, _, _ = await _session(client, periods=1)
        late_b = await _late_student("B", 1)
        other_c = await _late_student("C", 1)
        await client.post(f"/api/v1/sessions/{session_id}/rounds/ENTRY/open", headers=teacher)
        frame_url = f"/api/v1/attendance/{session_id}/process-frame"
        vision_frames.faces = [vision_frames.recognized(session_id, late_b)]
        late = (await client.post(frame_url, headers=teacher, content=b"f")).json()["faces"][0]

        lookups = []
        original = teaching_service.add_late_student

        async def counted(db_, session, identity):
            lookups.append(identity)
            return await original(db_, session, identity)

        monkeypatch.setattr(teaching_service, "add_late_student", counted)
        outsider = []
        for _ in range(3):
            vision_frames.faces = [vision_frames.recognized(session_id, other_c)]
            outsider.append((await client.post(frame_url, headers=teacher, content=b"f")).json()["faces"][0])
        view = (await client.get(f"/api/v1/attendance/{session_id}", headers=teacher)).json()

    roster = await db["session_rosters"].find_one({"session_id": session_id})
    assert late["mark_status"] == "marked"
    assert late_b in roster["identities"] and other_c not in roster["identities"]
    assert (await _record(session_id, late_b))["rounds"]["ENTRY"]["status"] == "PRESENT"
    assert late_b in {r["identity"] for r in view["records"]}
    assert all(f["mark_status"] == "rejected" and f["mark_reason"] == "not_on_roster" for f in outsider)
    assert outsider[0]["name"] != "UNKNOWN"  # still shown, with the reason
    assert lookups == [other_c]  # asked once, then remembered for a minute
    assert await db["audit_events"].count_documents({"action": "ROSTER_UPDATED", "metadata.added": late_b}) == 1


@pytest.mark.anyio
async def test_the_teacher_is_told_why_a_recognised_face_is_not_in_the_class(vision_frames):
    from app.database.users import create_user
    from app.services import recognition_service

    db = mongodb.get_database()
    recognition_service._NOT_IN_CLASS.clear()

    async def student(user_id: str, *, status: str = "APPROVED", setup: str | None = None) -> str:
        identity = f"stu_{user_id}"
        await create_user(user_id=user_id, email=f"{user_id}@niet.co.in", password_hash="x", role="STUDENT", status=status)
        await db["student_profiles"].insert_one({"user_id": user_id, "identity": identity, "student_id": identity, "name": user_id})
        if setup == "waiting":
            await db["enrolment_requests"].insert_one({"request_id": f"req_{user_id}", "user_id": user_id, "status": "PENDING"})
        return identity

    async with _client() as client:
        session_id, teacher, _, _ = await _session(client, periods=1)
        waiting = await student("why_waiting", setup="waiting")
        nothing = await student("why_nothing")
        pending = await student("why_pending", status="PENDING")
        elsewhere = await _late_student("C", 7)
        await client.post(f"/api/v1/sessions/{session_id}/rounds/ENTRY/open", headers=teacher)
        details = {}
        for identity in (waiting, nothing, pending, elsewhere):
            vision_frames.faces = [vision_frames.recognized(session_id, identity)]
            face = (await client.post(f"/api/v1/attendance/{session_id}/process-frame", headers=teacher, content=b"f")).json()["faces"][0]
            details[identity] = (face["mark_reason"], face.get("mark_detail"))
    assert details == {
        waiting: ("not_on_roster", "setup_pending"),
        nothing: ("not_on_roster", "no_setup"),
        pending: ("not_on_roster", "account_pending"),
        elsewhere: ("not_on_roster", "other_class"),
    }


@pytest.mark.anyio
async def test_a_timetable_teacher_cannot_start_an_old_style_class():
    async with _client() as client:
        _, teacher, _, _ = await _session(client, periods=1)
        old_style = await client.post(
            "/api/v1/sessions", headers=teacher,
            json={"course_name": "CN — DS-B", "class_code": "DS-B", "start_time": "2026-11-02T09:00:00Z", "end_time": "2026-11-02T10:00:00Z"},
        )
    assert old_style.status_code == 409 and "today's timetable" in old_style.json()["detail"]
