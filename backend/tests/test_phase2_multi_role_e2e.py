"""Comprehensive End-to-End Tests for Phase 2: Multi-Role Student, Teacher & Admin Management."""

import base64
from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient

from app.database import mongodb
from app.main import app


@pytest.mark.anyio
async def test_phase2_academic_structure_and_seeding():
    """Verify standard academic classes and subjects are seeded and accessible."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login as teacher
        login_res = await client.post(
            "/api/v1/auth/login",
            json={"email": "teacher@demo.edu", "password": "TeacherDevPass123!"},
        )
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        struct_res = await client.get("/api/v1/academic/structure", headers=headers)
        assert struct_res.status_code == 200
        data = struct_res.json()
        assert "branches" in data
        assert "classes" in data
        assert "subjects" in data

        class_codes = [c["class_code"] for c in data["classes"]]
        assert "DS-B" in class_codes
        assert "CS-A" in class_codes

        subject_names = [s["name"] for s in data["subjects"]]
        assert "Machine Learning" in subject_names


@pytest.mark.anyio
async def test_phase2_student_registration_and_biometric():
    """Verify student registration with academic grouping and photo generates biometric profile."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Dummy base64 jpeg image for registration
        dummy_img = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
        dummy_b64 = base64.b64encode(dummy_img).decode("utf-8")

        test_email = f"rahul_p2_{int(datetime.now().timestamp())}@example.com"
        test_student_id = f"DS2026_{int(datetime.now().timestamp())}"

        reg_payload = {
            "name": "Rahul Sharma",
            "email": test_email,
            "password": "StudentSecurePass123!",
            "student_id": test_student_id,
            "roll_number": "20261234",
            "branch": "Data Science",
            "section": "B",
            "photo_base64": dummy_b64,
        }

        try:
            reg_res = await client.post("/api/v1/students/register", json=reg_payload)
            assert reg_res.status_code == 201, reg_res.text
            profile = reg_res.json()
            assert profile["name"] == "Rahul Sharma"
            assert profile["student_id"] == test_student_id
            assert profile["branch"] == "Data Science"
            assert profile["section"] == "B"
            assert profile["class_code"] == "DS-B"
            assert profile["has_biometric"] is True

            # Test student login
            login_res = await client.post(
                "/api/v1/auth/login",
                json={"email": test_email, "password": "StudentSecurePass123!"},
            )
            assert login_res.status_code == 200
            stu_token = login_res.json()["access_token"]
            stu_headers = {"Authorization": f"Bearer {stu_token}"}

            # Test get full profile
            me_res = await client.get("/api/v1/students/me", headers=stu_headers)
            assert me_res.status_code == 200
            assert me_res.json()["student_id"] == test_student_id

            # Verify security: student cannot access teacher dashboard
            teach_res = await client.get("/api/v1/teachers/dashboard", headers=stu_headers)
            assert teach_res.status_code == 403

            # Verify security: student cannot access admin users
            admin_res = await client.get("/api/v1/admin/users", headers=stu_headers)
            assert admin_res.status_code == 403
        finally:
            # Clean up temporary test student
            db = mongodb.get_database()
            await db["users"].delete_many({"email": test_email})
            await db["student_profiles"].delete_many({"student_id": test_student_id})
            await db["biometric_profiles"].delete_many({"identity": test_student_id})


@pytest.mark.anyio
async def test_phase2_teacher_flow_auto_roster_and_one_active_session():
    """Verify teacher session creation auto-loads DS-B roster and enforces 1-active-session rule."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login as teacher
        login_res = await client.post(
            "/api/v1/auth/login",
            json={"email": "teacher@demo.edu", "password": "TeacherDevPass123!"},
        )
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        teacher_id = login_res.json()["user"]["user_id"]

        # Ensure no active sessions exist for teacher
        db = mongodb.get_database()
        await db["sessions"].update_many(
            {"created_by": teacher_id, "status": "ACTIVE"},
            {"$set": {"status": "FINALIZED"}},
        )

        # Ensure our test student from earlier or seeded student is in DS-B
        from app.database.student_profiles import upsert_student_profile
        await upsert_student_profile(
            user_id="user_test_stu_dsb",
            identity="DS_STU_001",
            name="Rahul Sharma",
            email="rahul.dsb@campus.edu",
            student_id="DS_STU_001",
            roll_number="101",
            branch="Data Science",
            section="B",
            class_code="DS-B",
            has_biometric=True,
        )

        session_id = None
        try:
            # 1. Teacher starts attendance session for class DS-B, subject Machine Learning
            create_res = await client.post(
                "/api/v1/sessions",
                headers=headers,
                json={
                    "course_name": "Machine Learning — DS-B",
                    "classroom_id": "ROOM_201",
                    "class_code": "DS-B",
                    "subject": "Machine Learning",
                    "start_time": datetime.now(timezone.utc).isoformat(),
                    "end_time": datetime.now(timezone.utc).isoformat(),
                    "required_presence_percentage": 100.0,
                },
            )
            assert create_res.status_code == 201, create_res.text
            session = create_res.json()
            session_id = session["session_id"]
            assert session["class_code"] == "DS-B"

            # 2. Transition to ACTIVE
            start_res = await client.post(f"/api/v1/sessions/{session_id}/start", headers=headers)
            assert start_res.status_code == 200
            assert start_res.json()["status"] == "ACTIVE"

            # 3. Rule 8: Teacher tries to create ANOTHER active session -> MUST FAIL WITH 400
            conflict_res = await client.post(
                "/api/v1/sessions",
                headers=headers,
                json={
                    "course_name": "Deep Learning — DS-C",
                    "classroom_id": "ROOM_202",
                    "class_code": "DS-C",
                    "subject": "Deep Learning",
                    "start_time": datetime.now(timezone.utc).isoformat(),
                    "end_time": datetime.now(timezone.utc).isoformat(),
                },
            )
            assert conflict_res.status_code == 400
            assert "already have an active attendance session" in conflict_res.json()["detail"]

            # 4. Check that roster for DS-B was automatically loaded and initialized to ABSENT
            att_res = await client.get(f"/api/v1/attendance/{session_id}", headers=headers)
            assert att_res.status_code == 200
            records = att_res.json()["records"]
            student_rec = next((r for r in records if r["identity"] == "DS_STU_001"), None)
            assert student_rec is not None
            assert student_rec["status"] == "ABSENT"

            # 5. One-time attendance marking: Face recognized -> PRESENT
            mark_res = await client.post(
                f"/api/v1/attendance/{session_id}/mark",
                json={"session_id": session_id, "identity": "DS_STU_001"},
            )
            assert mark_res.status_code == 200
            assert mark_res.json()["status"] == "marked"

            # 6. Duplicate face seen -> Already Present
            dup_res = await client.post(
                f"/api/v1/attendance/{session_id}/mark",
                json={"session_id": session_id, "identity": "DS_STU_001"},
            )
            assert dup_res.status_code == 200
            assert dup_res.json()["status"] == "already_present"

            # 7. End session -> status FINALIZED
            end_res = await client.post(f"/api/v1/sessions/{session_id}/end", headers=headers)
            assert end_res.status_code == 200
            assert end_res.json()["status"] == "FINALIZED"

            # 8. Teacher manual correction: toggle DS_STU_001 back to ABSENT
            att_id = f"att_{session_id}_DS_STU_001"
            patch_res = await client.patch(
                f"/api/v1/attendance/{session_id}/records/{att_id}",
                headers=headers,
                json={"status": "ABSENT"},
            )
            assert patch_res.status_code == 200
            assert patch_res.json()["status"] == "ABSENT"

            # 9. Toggle back to PRESENT
            patch_res2 = await client.patch(
                f"/api/v1/attendance/{session_id}/records/{att_id}",
                headers=headers,
                json={"status": "PRESENT"},
            )
            assert patch_res2.status_code == 200
            assert patch_res2.json()["status"] == "PRESENT"

            # 10. Teacher dashboard reflects finalized session
            dash_res = await client.get("/api/v1/teachers/dashboard", headers=headers)
            assert dash_res.status_code == 200
            dash_data = dash_res.json()
            assert dash_data["active_session"] is None  # no active session
            prev_ids = [s["session_id"] for s in dash_data["previous_sessions"]]
            assert session_id in prev_ids
        finally:
            # Clean up test session, attendance records, and student
            db = mongodb.get_database()
            if session_id:
                await db["sessions"].delete_many({"session_id": session_id})
                await db["session_rosters"].delete_many({"session_id": session_id})
                await db["attendance_records"].delete_many({"session_id": session_id})
            await db["student_profiles"].delete_many({"user_id": "user_test_stu_dsb"})


@pytest.mark.anyio
async def test_phase2_admin_panel():
    """Verify admin has full management access to students, teachers, academic structure, and sessions."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login as Admin
        admin_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@system.local", "password": "AdminDevPass123!"},
        )
        assert admin_login.status_code == 200
        admin_token = admin_login.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 1. Admin views students table
        students_res = await client.get("/api/v1/admin/students", headers=admin_headers)
        assert students_res.status_code == 200
        assert isinstance(students_res.json(), list)

        # 2. Admin views teachers table
        teachers_res = await client.get("/api/v1/admin/teachers", headers=admin_headers)
        assert teachers_res.status_code == 200
        assert isinstance(teachers_res.json(), list)

        # 3. Admin adds a new academic class
        new_class_code = f"TEST-{int(datetime.now().timestamp())%1000}"
        try:
            # 3. Admin adds a new academic class
            add_class_res = await client.post(
                "/api/v1/admin/academic/classes",
                headers=admin_headers,
                json={
                    "class_code": new_class_code,
                    "branch": "Test Branch",
                    "section": "A",
                    "semester": 1,
                },
            )
            assert add_class_res.status_code == 201

            # 4. Admin views sessions with filters
            sessions_res = await client.get("/api/v1/admin/sessions?status=FINALIZED", headers=admin_headers)
            assert sessions_res.status_code == 200
            for s in sessions_res.json():
                assert s["status"] == "FINALIZED"
        finally:
            db = mongodb.get_database()
            await db["academic_classes"].delete_many({"class_code": new_class_code})
