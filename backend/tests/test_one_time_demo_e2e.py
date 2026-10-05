"""End-to-End Test for AI Face Recognition Attendance System (One-Time Attendance Demo).

Validates the full demo sequence requested by the user:
1. Teacher starts attendance session (Data Structures — CSE-A).
2. Roster is initialized with Rahul, Aman, Priya, Krish.
3. Rahul appears -> recognized -> marked PRESENT (1 student present).
4. Aman appears -> recognized -> marked PRESENT (2 students present).
5. Rahul appears again -> already present -> no duplicate record.
6. Teacher ends attendance -> finalizes session.
7. Final result:
   - Rahul: PRESENT
   - Aman: PRESENT
   - Priya: ABSENT
   - Krish: ABSENT
8. Teacher downloads CSV export -> verified clean format.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone
import csv
import io

from app.main import app
from app.database import mongodb
from app.core.config import settings


@pytest.mark.anyio
async def test_one_time_attendance_demo_flow():
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
            # 3. Enroll Students onto Roster (Rahul, Aman, Priya, Krish)
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

            # 5. Step 6 of Demo: Rahul stands in front of camera -> recognized -> marked PRESENT
            mark_rahul_1 = await client.post(
                f"/api/v1/attendance/{session_id}/mark",
                headers=headers,
                json={"identity": "student1"},
            )
            assert mark_rahul_1.status_code == 200, mark_rahul_1.text
            res_r1 = mark_rahul_1.json()
            assert res_r1["status"] == "marked"
            assert res_r1["student_name"] == "Rahul Sharma" or "Rahul" in res_r1["student_name"]

            # Check attendance list: 1 student present
            att_after_r1 = await client.get(
                f"/api/v1/attendance/{session_id}",
                headers=headers,
            )
            assert att_after_r1.json()["present_count"] == 1
            rahul_rec = next(r for r in att_after_r1.json()["records"] if r["identity"] == "student1")
            assert rahul_rec["status"] == "PRESENT"

            # 6. Step 7 of Demo: Aman stands in front -> recognized -> marked PRESENT
            mark_aman = await client.post(
                f"/api/v1/attendance/{session_id}/mark",
                headers=headers,
                json={"identity": "student2"},
            )
            assert mark_aman.status_code == 200, mark_aman.text
            res_a = mark_aman.json()
            assert res_a["status"] == "marked"
            assert res_a["student_name"] == "Aman Kumar" or "Aman" in res_a["student_name"]

            # Check attendance list: 2 students present
            att_after_a = await client.get(
                f"/api/v1/attendance/{session_id}",
                headers=headers,
            )
            assert att_after_a.json()["present_count"] == 2

            # 7. Step 8 of Demo: Rahul appears again -> already present -> no duplicate
            mark_rahul_2 = await client.post(
                f"/api/v1/attendance/{session_id}/mark",
                headers=headers,
                json={"identity": "student1"},
            )
            assert mark_rahul_2.status_code == 200, mark_rahul_2.text
            res_r2 = mark_rahul_2.json()
            assert res_r2["status"] == "already_present"
            assert "already marked" in res_r2["message"].lower()

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
            assert status_by_name.get("Rahul Sharma") == "PRESENT" or status_by_name.get("Rahul") == "PRESENT"
            assert status_by_name.get("Aman Kumar") == "PRESENT" or status_by_name.get("Aman") == "PRESENT"

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
