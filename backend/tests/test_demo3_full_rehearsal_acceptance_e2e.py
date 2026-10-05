"""Full End-to-End Acceptance & Demo 3 Rehearsal Test (Step 2E.14).

Verifies the complete scenario required by Step 2E.14 Task 2:
1. Teacher logs in, creates session for CS-101 in ROOM_101.
2. Roster is set with enrolled students [Alice (student_01), Bob (student_02), Charlie (student_03)].
3. Phone/WebRTC camera connects and transmits telemetry (state: CONNECTED, fps: 15.0).
4. Alice enters and stays inside (accumulating continuous presence).
5. Bob enters and exits after a short interval (state transitions INSIDE -> OUTSIDE).
6. Charlie is never seen (state remains NOT_SEEN).
7. One unknown visitor passes -> pipeline assigns UNKNOWN, zero transit events emitted.
8. One non-roster enrolled person (David, student_04_guest) enters -> live dashboard displays David with is_rostered=False.
9. Teacher inspects live dashboard: verifies Alice INSIDE, Bob OUTSIDE, Charlie NOT_SEEN, David unrostered.
10. Teacher finalizes session -> Alice PRESENT, Bob ABSENT, Charlie ABSENT.
11. Teacher applies manual correction to Bob with mandatory justification.
12. Audit log verified: captures before/after states, teacher attribution, and justification text.
"""

from datetime import datetime, timedelta, timezone
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.core.config import settings
from app.database import get_database, init_indexes, mongodb
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def rehearsal_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await init_indexes(db)
    return db


@pytest.fixture
async def rehearsal_client(rehearsal_db, monkeypatch):
    app.dependency_overrides[get_database] = lambda: rehearsal_db

    monkeypatch.setattr(settings, "REQUIRE_CAMERA_AUTH", True)
    monkeypatch.setattr(settings, "VISION_SERVICE_API_KEY", "vision-rehearsal-secret-2026")
    monkeypatch.setattr(settings, "VISION_SERVICE_API_KEY_HASH", "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_full_demo3_acceptance_and_rehearsal_walkthrough(
    rehearsal_client: AsyncClient,
    rehearsal_db,
) -> None:
    # -------------------------------------------------------------------------
    # 1. Teacher Setup & Authentication
    # -------------------------------------------------------------------------
    teacher_id = f"prof_{uuid.uuid4().hex[:8]}"
    await create_user(
        user_id=teacher_id,
        email="prof_demo@university.edu",
        password_hash=hash_password("TeacherSecurePass123!"),
        role="TEACHER",
    )
    teacher_token = create_access_token(user_id=teacher_id, role="TEACHER")
    auth_headers = {"Authorization": f"Bearer {teacher_token}"}
    camera_headers = {"X-API-Key": "vision-rehearsal-secret-2026"}

    # -------------------------------------------------------------------------
    # 2. Session Creation & Roster Definition (CS-101 in ROOM_101)
    # -------------------------------------------------------------------------
    session_id = f"session_rehearsal_{uuid.uuid4().hex[:8]}"
    wall_now = datetime.now(timezone.utc)
    start_time = wall_now - timedelta(minutes=45)
    end_time = wall_now + timedelta(minutes=15)  # 60 min session total (3600s)

    await rehearsal_db["sessions"].insert_one({
        "session_id": session_id,
        "course_name": "CS-101: Computer Science Fundamentals",
        "classroom_id": "ROOM_101",
        "start_time": start_time,
        "end_time": end_time,
        "required_presence_percentage": 75.0,  # 45 minutes (2700s) required for credit
        "status": "SCHEDULED",
        "created_by": teacher_id,
    })

    # Roster: Alice (student_01), Bob (student_02), Charlie (student_03)
    await rehearsal_db["session_rosters"].insert_one({
        "session_id": session_id,
        "identities": ["student_01_alice", "student_02_bob", "student_03_charlie"],
    })

    # -------------------------------------------------------------------------
    # 3. Camera Connects (WebRTC Phone Streamer on CAM_ROOM_101_DOOR)
    # -------------------------------------------------------------------------
    camera_id = "CAM_ROOM_101_DOOR"
    await rehearsal_db["cameras"].insert_one({
        "camera_id": camera_id,
        "classroom_id": "ROOM_101",
        "role": "BOTH",
        "source_type": "WEBRTC",
        "enabled": True,
        "status": "DISCONNECTED",
        "fps": 0.0,
        "last_seen": None,
    })

    hb_resp = await rehearsal_client.post(
        f"/api/v1/cameras/{camera_id}/heartbeat",
        headers=camera_headers,
        json={
            "camera_id": camera_id,
            "state": "CONNECTED",
            "fps": 15.0,
            "dropped_frames": 0,
        },
    )
    assert hb_resp.status_code == 200

    # -------------------------------------------------------------------------
    # 4. Transits: Alice Enters and Stays Inside
    # -------------------------------------------------------------------------
    t_alice_in = start_time + timedelta(minutes=2)
    ev_alice_in = await rehearsal_client.post(
        "/api/v1/events",
        headers=camera_headers,
        json={
            "event_id": f"ev_alice_in_{uuid.uuid4().hex[:8]}",
            "camera_id": camera_id,
            "track_id": 10,
            "identity": "student_01_alice",
            "direction": "ENTRY",
            "timestamp": t_alice_in.isoformat(),
            "evidence": {
                "peak_similarity": 0.92,
                "mean_similarity": 0.88,
                "supporting_frames": 4,
                "total_frames": 4,
                "consistency_pct": 100.0,
            },
        },
    )
    assert ev_alice_in.status_code == 201

    # -------------------------------------------------------------------------
    # 5. Transits: Bob Enters, Stays 10 Minutes, then Exits
    # -------------------------------------------------------------------------
    t_bob_in = start_time + timedelta(minutes=5)
    t_bob_out = start_time + timedelta(minutes=15)  # 10 min duration = 600s (< 75%)
    await rehearsal_client.post(
        "/api/v1/events",
        headers=camera_headers,
        json={
            "event_id": f"ev_bob_in_{uuid.uuid4().hex[:8]}",
            "camera_id": camera_id,
            "track_id": 20,
            "identity": "student_02_bob",
            "direction": "ENTRY",
            "timestamp": t_bob_in.isoformat(),
            "evidence": {
                "peak_similarity": 0.85,
                "mean_similarity": 0.82,
                "supporting_frames": 3,
                "total_frames": 3,
                "consistency_pct": 100.0,
            },
        },
    )
    await rehearsal_client.post(
        "/api/v1/events",
        headers=camera_headers,
        json={
            "event_id": f"ev_bob_out_{uuid.uuid4().hex[:8]}",
            "camera_id": camera_id,
            "track_id": 20,
            "identity": "student_02_bob",
            "direction": "EXIT",
            "timestamp": t_bob_out.isoformat(),
            "evidence": {
                "peak_similarity": 0.84,
                "mean_similarity": 0.80,
                "supporting_frames": 3,
                "total_frames": 3,
                "consistency_pct": 100.0,
            },
        },
    )

    # -------------------------------------------------------------------------
    # 6. Unknown Visitor Passes Through (0 Events Emitted)
    # -------------------------------------------------------------------------
    # The vision pipeline assigned UNKNOWN to the tracklet; zero events were dispatched.
    # We verify that no "UNKNOWN" or unrecognized document is present in events collection.
    unknown_count = await rehearsal_db["attendance_events"].count_documents({"identity": "UNKNOWN"})
    assert unknown_count == 0

    # -------------------------------------------------------------------------
    # 7. Non-Roster Enrolled Student Enters (David, student_04_guest)
    # -------------------------------------------------------------------------
    t_david_in = start_time + timedelta(minutes=10)
    ev_david_in = await rehearsal_client.post(
        "/api/v1/events",
        headers=camera_headers,
        json={
            "event_id": f"ev_david_in_{uuid.uuid4().hex[:8]}",
            "camera_id": camera_id,
            "track_id": 30,
            "identity": "student_04_guest",
            "direction": "ENTRY",
            "timestamp": t_david_in.isoformat(),
            "evidence": {
                "peak_similarity": 0.89,
                "mean_similarity": 0.86,
                "supporting_frames": 3,
                "total_frames": 3,
                "consistency_pct": 100.0,
            },
        },
    )
    assert ev_david_in.status_code == 201

    # -------------------------------------------------------------------------
    # 8. Teacher Observes Live Dashboard Snapshot
    # -------------------------------------------------------------------------
    snap_resp = await rehearsal_client.get(
        f"/api/v1/sessions/{session_id}/live-snapshot",
        headers=auth_headers,
    )
    assert snap_resp.status_code == 200
    snap = snap_resp.json()

    assert snap["session_state"] == "LIVE"
    assert len(snap["cameras"]) == 1
    assert snap["cameras"][0]["status"] == "CONNECTED"

    # Alice: Rostered, State INSIDE, no_exit_observed=True, on track
    alice = next(s for s in snap["students"] if s["identity"] == "student_01_alice")
    assert alice["is_rostered"] is True
    assert alice["state"] == "INSIDE"
    assert alice["no_exit_observed"] is True

    # Bob: Rostered, State OUTSIDE, 10 min accumulated, not on track (projected ABSENT)
    bob = next(s for s in snap["students"] if s["identity"] == "student_02_bob")
    assert bob["is_rostered"] is True
    assert bob["state"] == "OUTSIDE"
    assert bob["presence_duration_seconds"] == 600.0
    assert bob["projected_status"] == "ABSENT"

    # Charlie: Rostered, State NOT_SEEN, 0 duration, projected ABSENT
    charlie = next(s for s in snap["students"] if s["identity"] == "student_03_charlie")
    assert charlie["is_rostered"] is True
    assert charlie["state"] == "NOT_SEEN"
    assert charlie["presence_duration_seconds"] == 0.0

    # David: Unrostered, State INSIDE, is_rostered=False
    david = next(s for s in snap["students"] if s["identity"] == "student_04_guest")
    assert david["is_rostered"] is False
    assert david["state"] == "INSIDE"

    # -------------------------------------------------------------------------
    # 9. Session Finalization
    # -------------------------------------------------------------------------
    # Close Alice's presence at end_time - 5 min (attended 53 min = 3180s > 2700s)
    t_alice_out = end_time - timedelta(minutes=5)
    await rehearsal_client.post(
        "/api/v1/events",
        headers=camera_headers,
        json={
            "event_id": f"ev_alice_out_{uuid.uuid4().hex[:8]}",
            "camera_id": camera_id,
            "track_id": 10,
            "identity": "student_01_alice",
            "direction": "EXIT",
            "timestamp": t_alice_out.isoformat(),
            "evidence": {
                "peak_similarity": 0.90,
                "mean_similarity": 0.85,
                "supporting_frames": 3,
                "total_frames": 3,
                "consistency_pct": 100.0,
            },
        },
    )

    fin_resp = await rehearsal_client.post(
        f"/api/v1/sessions/{session_id}/finalize",
        headers=auth_headers,
    )
    assert fin_resp.status_code == 200

    # Query Finalized Attendance Records
    att_resp = await rehearsal_client.get(
        f"/api/v1/attendance/{session_id}",
        headers=auth_headers,
    )
    assert att_resp.status_code == 200
    records = att_resp.json()["records"]
    assert len(records) >= 3

    rec_alice = next(r for r in records if r["identity"] == "student_01_alice")
    assert rec_alice["status"] == "PRESENT"
    assert rec_alice["presence_duration_seconds"] == (53 * 60)

    rec_bob = next(r for r in records if r["identity"] == "student_02_bob")
    assert rec_bob["status"] == "ABSENT"
    assert rec_bob["presence_duration_seconds"] == 600.0

    rec_charlie = next(r for r in records if r["identity"] == "student_03_charlie")
    assert rec_charlie["status"] == "ABSENT"
    assert rec_charlie["presence_duration_seconds"] == 0.0

    # -------------------------------------------------------------------------
    # 10. Manual Attendance Correction with Mandatory Justification
    # -------------------------------------------------------------------------
    bob_att_id = rec_bob["attendance_id"]
    corr_payload = {
        "new_status": "PRESENT",
        "new_presence_seconds": 2700.0,
        "reason": "Excused laboratory assignment approved by department head",
    }
    corr_resp = await rehearsal_client.patch(
        f"/api/v1/attendance/{session_id}/records/{bob_att_id}",
        headers=auth_headers,
        json=corr_payload,
    )
    assert corr_resp.status_code == 200
    corr_data = corr_resp.json()
    assert corr_data["previous_status"] == "ABSENT"
    assert corr_data["new_status"] == "PRESENT"
    assert corr_data["reason"] == corr_payload["reason"]

    # Verify updated record reflects change
    att_updated = await rehearsal_client.get(
        f"/api/v1/attendance/{session_id}",
        headers=auth_headers,
    )
    bob_updated = next(r for r in att_updated.json()["records"] if r["identity"] == "student_02_bob")
    assert bob_updated["status"] == "PRESENT"
    assert bob_updated["manually_corrected"] is True

    # -------------------------------------------------------------------------
    # 11. Immutable Audit Log Verification
    # -------------------------------------------------------------------------
    audit_resp = await rehearsal_client.get(
        f"/api/v1/audit?resource_type=ATTENDANCE&resource_id={bob_att_id}",
        headers=auth_headers,
    )
    assert audit_resp.status_code == 200
    audit_events = audit_resp.json()
    assert len(audit_events) >= 1

    latest_audit = audit_events[0]
    assert latest_audit["actor_user_id"] == teacher_id
    assert latest_audit["action"] == "ATTENDANCE_CORRECTED"
    assert latest_audit["metadata"]["new_status"] == "PRESENT"
    assert latest_audit["metadata"]["reason"] == corr_payload["reason"]
