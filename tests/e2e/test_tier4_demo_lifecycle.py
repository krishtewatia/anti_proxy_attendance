"""Tier 4: Full Real-World Demo Application Lifecycle E2E Tests.

Simulates the entire 4-student classroom attendance scenario:
1. Teacher authenticates and verifies session CS-101 in ROOM_101.
2. Initial roster check: all 4 students enrolled, all state NOT_SEEN.
3. Person 01 (Student 1) transits doorway (ENTRY) -> transitions to INSIDE.
4. Person 02 (Student 2) transits doorway (ENTRY) -> transitions to INSIDE.
5. Person 03 (Student 3) transits doorway (ENTRY) -> transitions to INSIDE.
6. Person 04 (Student 4) never transits doorway -> remains NOT_SEEN.
7. Dwell accumulation verified in live snapshot.
8. Person 02 exits doorway (EXIT) -> transitions to OUTSIDE with closed interval.
9. Finalization / Ledger calculation: POST /api/v1/sessions/{id}/finalize.
10. Final ledger verification: GET /api/v1/attendance/{id} and audit log verification.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
import sys
from typing import Any
import uuid

# Ensure local test directory is importable
_E2E_DIR = Path(__file__).resolve().parent
if str(_E2E_DIR) not in sys.path:
    sys.path.insert(0, str(_E2E_DIR))

from conftest import (
    CAMERA_ID,
    ROOM_ID,
    STUDENT_ROSTER,
    TEACHER_EMAIL,
)
from httpx import AsyncClient
import pytest
from pymongo.database import Database

pytestmark = [pytest.mark.anyio, pytest.mark.e2e]


def create_event(
    *,
    session_id: str,
    identity: str,
    direction: str,
    timestamp: dt.datetime,
    track_id: int,
) -> dict[str, Any]:
    """Helper to generate an event payload."""
    return {
        "event_id": f"evt_demo4_{identity}_{direction.lower()}_{uuid.uuid4().hex[:6]}",
        "camera_id": CAMERA_ID,
        "track_id": track_id,
        "identity": identity,
        "direction": direction,
        "timestamp": timestamp.isoformat(),
        "evidence": {
            "peak_similarity": 0.94,
            "mean_similarity": 0.91,
            "supporting_frames": 3,
            "total_frames": 3,
            "consistency_pct": 100.0,
            "margin_over_runner_up": 0.40,
            "runner_up_identity": "person_02" if identity != "person_02" else "person_03",
        },
    }


async def test_full_demo_4student_lifecycle_and_ledger(
    api_client: AsyncClient,
    mongo_db: Database,
    teacher_headers: dict[str, str],
    vision_headers: dict[str, str],
    clean_seed: dict[str, Any],
) -> None:
    """Execute complete end-to-end 4-student demonstration lifecycle."""
    now = dt.datetime.now(dt.timezone.utc)

    # -------------------------------------------------------------------------
    # Step 1: Create an isolated Demo Session to guarantee clean ledger testing
    # -------------------------------------------------------------------------
    demo_session_id = f"sess_lifecycle_{uuid.uuid4().hex[:8]}"
    start_time = now - dt.timedelta(minutes=30)
    end_time = now + dt.timedelta(minutes=30)

    # Teacher user_id
    teacher_doc = mongo_db.users.find_one({"email": TEACHER_EMAIL})
    assert teacher_doc is not None
    teacher_uid = teacher_doc["user_id"]

    mongo_db.sessions.insert_one({
        "session_id": demo_session_id,
        "course_name": "CS-101 Introduction to Computer Science",
        "classroom_id": ROOM_ID,
        "teacher_id": teacher_uid,
        "created_by": teacher_uid,
        "start_time": start_time,
        "end_time": end_time,
        "required_presence_percentage": 50.0,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
    })

    mongo_db.session_rosters.insert_one({
        "session_id": demo_session_id,
        "identities": STUDENT_ROSTER,
        "created_at": now,
        "updated_at": now,
    })

    try:
        # ---------------------------------------------------------------------
        # Step 2: Initial State Verification via Live Snapshot
        # ---------------------------------------------------------------------
        snap0_res = await api_client.get(
            f"/api/v1/sessions/{demo_session_id}/live-snapshot",
            headers=teacher_headers,
        )
        assert snap0_res.status_code == 200, f"Snapshot fetch failed: {snap0_res.text}"
        snap0 = snap0_res.json()

        assert snap0["session_state"] == "LIVE"
        assert len(snap0["students"]) == 4
        for stu in snap0["students"]:
            assert stu["state"] == "NOT_SEEN"
            assert stu["presence_duration_seconds"] == 0.0

        # ---------------------------------------------------------------------
        # Step 3: Transit Ingestion - Student 1, 2, 3 enter; Student 4 absent
        # ---------------------------------------------------------------------
        t0 = now - dt.timedelta(seconds=45)

        # Student 1 (person_01) enters at T0
        ev_s1_in = create_event(
            session_id=demo_session_id,
            identity="person_01",
            direction="ENTRY",
            timestamp=t0,
            track_id=101,
        )
        res_s1 = await api_client.post("/api/v1/events", json=ev_s1_in, headers=vision_headers)
        assert res_s1.status_code == 201

        # Student 2 (person_02) enters at T0 + 5s
        t_s2_in = t0 + dt.timedelta(seconds=5)
        ev_s2_in = create_event(
            session_id=demo_session_id,
            identity="person_02",
            direction="ENTRY",
            timestamp=t_s2_in,
            track_id=102,
        )
        res_s2 = await api_client.post("/api/v1/events", json=ev_s2_in, headers=vision_headers)
        assert res_s2.status_code == 201

        # Student 3 (person_03) enters at T0 + 10s
        t_s3_in = t0 + dt.timedelta(seconds=10)
        ev_s3_in = create_event(
            session_id=demo_session_id,
            identity="person_03",
            direction="ENTRY",
            timestamp=t_s3_in,
            track_id=103,
        )
        res_s3 = await api_client.post("/api/v1/events", json=ev_s3_in, headers=vision_headers)
        assert res_s3.status_code == 201

        # Student 4 (person_04) DOES NOT ENTER

        # ---------------------------------------------------------------------
        # Step 4: Verify Live Snapshot reflecting Students 1, 2, 3 INSIDE
        # ---------------------------------------------------------------------
        snap1_res = await api_client.get(
            f"/api/v1/sessions/{demo_session_id}/live-snapshot",
            headers=teacher_headers,
        )
        assert snap1_res.status_code == 200
        snap1 = snap1_res.json()

        st_map1 = {s["identity"]: s for s in snap1["students"]}
        assert st_map1["person_01"]["state"] == "INSIDE"
        assert st_map1["person_02"]["state"] == "INSIDE"
        assert st_map1["person_03"]["state"] == "INSIDE"
        assert st_map1["person_04"]["state"] == "NOT_SEEN"

        # Dwell time must be accumulating for those inside
        assert st_map1["person_01"]["presence_duration_seconds"] > 0.0
        assert st_map1["person_04"]["presence_duration_seconds"] == 0.0

        # ---------------------------------------------------------------------
        # Step 5: Student 2 exits doorway at T0 + 35s (30s visit)
        # ---------------------------------------------------------------------
        t_s2_out = t0 + dt.timedelta(seconds=35)
        ev_s2_out = create_event(
            session_id=demo_session_id,
            identity="person_02",
            direction="EXIT",
            timestamp=t_s2_out,
            track_id=104,
        )
        res_s2_out = await api_client.post("/api/v1/events", json=ev_s2_out, headers=vision_headers)
        assert res_s2_out.status_code == 201

        # ---------------------------------------------------------------------
        # Step 6: Verify Live Snapshot: Student 2 OUTSIDE, 1 & 3 INSIDE, 4 NOT_SEEN
        # ---------------------------------------------------------------------
        snap2_res = await api_client.get(
            f"/api/v1/sessions/{demo_session_id}/live-snapshot",
            headers=teacher_headers,
        )
        assert snap2_res.status_code == 200
        snap2 = snap2_res.json()

        st_map2 = {s["identity"]: s for s in snap2["students"]}
        assert st_map2["person_01"]["state"] == "INSIDE"
        assert st_map2["person_02"]["state"] == "OUTSIDE"
        assert st_map2["person_03"]["state"] == "INSIDE"
        assert st_map2["person_04"]["state"] == "NOT_SEEN"

        # Closed interval for person_02: 35s - 5s = 30 seconds
        s2_dur = st_map2["person_02"]["presence_duration_seconds"]
        assert 28.0 <= s2_dur <= 32.0, f"Expected Student 2 duration ~30s, got {s2_dur}"

        # ---------------------------------------------------------------------
        # Step 7: Finalize Attendance Session & Compute Ledger
        # ---------------------------------------------------------------------
        fin_res = await api_client.post(
            f"/api/v1/sessions/{demo_session_id}/finalize",
            headers=teacher_headers,
        )
        assert fin_res.status_code == 200, f"Finalization failed: {fin_res.text}"
        fin_data = fin_res.json()
        assert fin_data["session_id"] == demo_session_id
        records = fin_data.get("records", [])
        assert len(records) == 4, f"Expected 4 attendance records, got {len(records)}"

        rec_map = {r["identity"]: r for r in records}

        # Check Person 01: Present, continuous presence
        assert "person_01" in rec_map
        assert rec_map["person_01"]["presence_duration_seconds"] > 0.0

        # Check Person 02: Closed presence intervals
        assert "person_02" in rec_map
        assert len(rec_map["person_02"]["presence_intervals"]) >= 1
        assert 28.0 <= rec_map["person_02"]["presence_duration_seconds"] <= 32.0

        # Check Person 03: Present
        assert "person_03" in rec_map
        assert rec_map["person_03"]["presence_duration_seconds"] > 0.0

        # Check Person 04: Never seen, duration 0, ABSENT
        assert "person_04" in rec_map
        assert rec_map["person_04"]["presence_duration_seconds"] == 0.0
        assert rec_map["person_04"]["status"] == "ABSENT"

        # ---------------------------------------------------------------------
        # Step 8: Verify Attendance Ledger via GET /api/v1/attendance/{session_id}
        # ---------------------------------------------------------------------
        att_res = await api_client.get(
            f"/api/v1/attendance/{demo_session_id}",
            headers=teacher_headers,
        )
        assert att_res.status_code == 200, f"Attendance ledger fetch failed: {att_res.text}"
        ledger = att_res.json()
        assert ledger["session_id"] == demo_session_id
        assert len(ledger["records"]) == 4

        # ---------------------------------------------------------------------
        # Step 9: Verify Security Audit Log Recorded ATTENDANCE_FINALIZED
        # ---------------------------------------------------------------------
        audit_event = mongo_db.audit_events.find_one({
            "resource_id": demo_session_id,
            "action": "ATTENDANCE_FINALIZED",
        })
        assert audit_event is not None, "Missing audit event for ATTENDANCE_FINALIZED"
        assert audit_event.get("actor_user_id") == teacher_uid

    finally:
        # Clean up isolated test session
        mongo_db.sessions.delete_one({"session_id": demo_session_id})
        mongo_db.session_rosters.delete_one({"session_id": demo_session_id})
        mongo_db.attendance_events.delete_many({"session_id": demo_session_id})
        mongo_db.attendance_records.delete_many({"session_id": demo_session_id})
