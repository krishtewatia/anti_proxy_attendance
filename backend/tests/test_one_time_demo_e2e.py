"""End-to-End Test for AI Face Recognition Attendance System (One-Time Attendance Demo).

Validates the full demo sequence requested by the user:
1. Teacher starts attendance session (Data Structures — CSE-A).
2. Roster is initialized with Alex, Blake, Casey, Devon.
3. Alex appears -> recognized -> marked PRESENT (1 student present).
4. Blake appears -> recognized -> marked PRESENT (2 students present).
5. Alex appears again -> already present -> no duplicate record.
6. Teacher ends attendance -> finalizes session.
7. Final result:
   - Alex: PRESENT
   - Blake: PRESENT
   - Casey: ABSENT
   - Devon: ABSENT
8. Teacher downloads CSV export -> verified clean format.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone
import csv
import io

from app.main import app
from tests.conftest import FRAME_BYTES
from app.database import mongodb
from app.core.config import settings


# Needs the seeded demo accounts and a running vision service (see README).
pytestmark = pytest.mark.integration


@pytest.mark.anyio
async def test_one_time_attendance_demo_flow(vision_frames):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Login as Teacher
        login_res = await client.post(
            "/api/v1/auth/login",
            json={"email": "teacher@demo.edu", "password": "TeacherDevPass123!"},
        )
        assert login_res.status_code == 200, login_res.text
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        teacher_user_id = login_res.json()["user"]["user_id"]

        # Finalize any leftover active session for clean test isolation
        db = mongodb.get_database()
        await db["sessions"].update_many(
            {"created_by": teacher_user_id, "status": "ACTIVE"},
            {"$set": {"status": "FINALIZED"}},
        )

        # 2. Start Attendance Session
        create_res = await client.post(
            "/api/v1/sessions",
            headers=headers,
            json={
                "course_name": "Data Structures — CSE-A",
                "classroom_id": "ROOM_101",
                "start_time": datetime.now(timezone.utc).isoformat(),
                "end_time": datetime.now(timezone.utc).isoformat(),
                "required_presence_percentage": 100.0,
            },
        )
        assert create_res.status_code == 201, create_res.text
        session = create_res.json()
        session_id = session["session_id"]

        try:
            # 3. Enroll Students onto Roster (Alex, Blake, Casey, Devon)
            roster_res = await client.put(
                f"/api/v1/sessions/{session_id}/roster",
                headers=headers,
                json={"identities": ["student1", "student2", "student3", "student4"]},
            )
            assert roster_res.status_code == 200, roster_res.text

            # 4. Initial Attendance State: All 4 students are ABSENT
            att_init = await client.get(
                f"/api/v1/attendance/{session_id}",
                headers=headers,
            )
            assert att_init.status_code == 200, att_init.text
            init_data = att_init.json()
            assert init_data["total_students"] == 4
            assert init_data["present_count"] == 0
            for r in init_data["records"]:
                assert r["status"] == "ABSENT"

            # Attendance can only be marked while the session is ACTIVE
            start_res = await client.post(f"/api/v1/sessions/{session_id}/start", headers=headers)
            assert start_res.status_code == 200, start_res.text

            frame_url = f"/api/v1/attendance/{session_id}/process-frame"

            # 5. Step 6 of Demo: Alex stands in front of camera -> recognized -> marked PRESENT
            # (frames go through the authenticated backend route; the vision call is stubbed
            # and returns a signed recognition result, as the real service does)
            vision_frames.faces = [
                vision_frames.recognized(session_id, "student1", name="Alex Example")
            ]
            mark_alex_1 = await client.post(frame_url, headers=headers, content=FRAME_BYTES)
            assert mark_alex_1.status_code == 200, mark_alex_1.text
            res_r1 = mark_alex_1.json()
            assert res_r1["faces"][0]["mark_status"] == "marked"
            assert res_r1["student_name"] == "Alex Example" or "Alex" in res_r1["student_name"]

            # Check attendance list: 1 student present
            att_after_r1 = await client.get(
                f"/api/v1/attendance/{session_id}",
                headers=headers,
            )
            assert att_after_r1.json()["present_count"] == 1
            alex_rec = next(r for r in att_after_r1.json()["records"] if r["identity"] == "student1")
            assert alex_rec["status"] == "PRESENT"

            # 6. Step 7 of Demo: Blake stands in front -> recognized -> marked PRESENT
            vision_frames.faces = [
                vision_frames.recognized(session_id, "student2", name="Blake Sample")
            ]
            mark_blake = await client.post(frame_url, headers=headers, content=FRAME_BYTES)
            assert mark_blake.status_code == 200, mark_blake.text
            res_a = mark_blake.json()
            assert res_a["faces"][0]["mark_status"] == "marked"
            assert res_a["student_name"] == "Blake Sample" or "Blake" in res_a["student_name"]

            # Check attendance list: 2 students present
            att_after_a = await client.get(
                f"/api/v1/attendance/{session_id}",
                headers=headers,
            )
            assert att_after_a.json()["present_count"] == 2

            # 7. Step 8 of Demo: Alex appears again -> already present -> no duplicate
            vision_frames.faces = [
                vision_frames.recognized(session_id, "student1", name="Alex Example")
            ]
            mark_alex_2 = await client.post(frame_url, headers=headers, content=FRAME_BYTES)
            assert mark_alex_2.status_code == 200, mark_alex_2.text
            res_r2 = mark_alex_2.json()
            assert res_r2["faces"][0]["mark_status"] == "already_present"

            # Present count still 2
            att_after_r2 = await client.get(
                f"/api/v1/attendance/{session_id}",
                headers=headers,
            )
            assert att_after_r2.json()["present_count"] == 2

            # 8. Step 9: Teacher ends attendance -> finalizes session
            fin_res = await client.post(
                f"/api/v1/sessions/{session_id}/finalize",
                headers=headers,
            )
            assert fin_res.status_code == 200, fin_res.text

            # 9. Step 10: Final result verification
            final_att = await client.get(
                f"/api/v1/attendance/{session_id}",
                headers=headers,
            )
            assert final_att.status_code == 200
            final_data = final_att.json()
            assert final_data["total_students"] == 4
            assert final_data["present_count"] == 2

            status_by_name = {r["student_name"]: r["status"] for r in final_data["records"]}
            assert status_by_name.get("Alex Example") == "PRESENT" or status_by_name.get("Alex") == "PRESENT"
            assert status_by_name.get("Blake Sample") == "PRESENT" or status_by_name.get("Blake") == "PRESENT"

            # 10. Step 11: Teacher downloads attendance CSV
            export_res = await client.get(
                f"/api/v1/attendance/{session_id}/export",
                headers=headers,
            )
            assert export_res.status_code == 200
            assert "text/csv" in export_res.headers.get("content-type", "")

            csv_reader = csv.reader(io.StringIO(export_res.text))
            rows = list(csv_reader)
            assert rows[0] == ["Student ID", "Student Name", "Status"]
        finally:
            # Clean up test session and attendance records
            await db["sessions"].delete_many({"session_id": session_id})
            await db["session_rosters"].delete_many({"session_id": session_id})
            await db["attendance_records"].delete_many({"session_id": session_id})
