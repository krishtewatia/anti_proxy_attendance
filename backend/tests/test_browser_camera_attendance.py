from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password


@pytest.fixture(autouse=True)
async def setup_test_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await db["sessions"].delete_many({})
    await db["attendance_records"].delete_many({})
    await db["session_rosters"].delete_many({})
    await db["users"].delete_many({})
    yield
    await db["sessions"].delete_many({})
    await db["attendance_records"].delete_many({})
    await db["session_rosters"].delete_many({})
    await db["users"].delete_many({})


@pytest.fixture
async def teacher_auth_headers():
    await create_user(
        user_id="teacher_browser_test",
        email="teacher@browser.edu",
        password_hash=hash_password("TeacherPass123!"),
        role="TEACHER",
    )
    token = create_access_token(user_id="teacher_browser_test", role="TEACHER")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
async def test_active_session_query(teacher_auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Initially no active session
        resp = await client.get("/api/v1/attendance/active-session")
        assert resp.status_code == 200
        assert resp.json()["has_active_session"] is False

        # Create active session
        db = mongodb.get_database()
        await db["sessions"].insert_one(
            {
                "session_id": "sess_live_123",
                "course_name": "Machine Learning — DS-B",
                "classroom_id": "ROOM_101",
                "status": "ACTIVE",
                "created_by": "teacher_browser_test",
                "start_time": datetime.now(timezone.utc),
            }
        )

        resp2 = await client.get("/api/v1/attendance/active-session")
        assert resp2.status_code == 200
        assert resp2.json()["has_active_session"] is True
        assert resp2.json()["session_id"] == "sess_live_123"


@pytest.mark.anyio
async def test_mark_student_present_and_duplicate_prevention(teacher_auth_headers):
    transport = ASGITransport(app=app)
    db = mongodb.get_database()
    await db["sessions"].insert_one(
        {
            "session_id": "sess_browser_001",
            "course_name": "Machine Learning — DS-B",
            "classroom_id": "ROOM_101",
            "status": "ACTIVE",
            "created_by": "teacher_browser_test",
            "start_time": datetime.now(timezone.utc),
        }
    )
    await db["student_profiles"].insert_one(
        {
            "student_id": "DS202601",
            "full_name": "Rahul Sharma",
            "biometric_identity": "student1",
        }
    )
    await db["session_rosters"].insert_one(
        {
            "session_id": "sess_browser_001",
            "identities": ["student1", "student2", "student3"],
        }
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. First recognition marks PRESENT
        mark_resp = await client.post(
            "/api/v1/attendance/mark",
            json={"identity": "student1", "session_id": "sess_browser_001"},
        )
        assert mark_resp.status_code == 200
        data1 = mark_resp.json()
        assert data1["status"] == "marked"
        assert data1["identity"] == "student1"
        assert data1["student_name"] == "Rahul Sharma"

        # 2. Duplicate frame recognition is idempotent
        dup_resp = await client.post(
            "/api/v1/attendance/mark",
            json={"identity": "student1", "session_id": "sess_browser_001"},
        )
        assert dup_resp.status_code == 200
        data2 = dup_resp.json()
        assert data2["status"] == "already_present"

        # 3. Check session attendance records
        att_resp = await client.get(
            "/api/v1/attendance/sess_browser_001",
            headers=teacher_auth_headers,
        )
        assert att_resp.status_code == 200
        records = att_resp.json()["records"]
        student1_rec = next((r for r in records if r["identity"] == "student1"), None)
        assert student1_rec is not None
        assert student1_rec["status"] == "PRESENT"


@pytest.mark.anyio
async def test_mark_attendance_rejects_unknown():
    transport = ASGITransport(app=app)
    db = mongodb.get_database()
    await db["sessions"].insert_one(
        {
            "session_id": "sess_browser_002",
            "status": "ACTIVE",
            "start_time": datetime.now(timezone.utc),
        }
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/attendance/mark",
            json={"identity": "UNKNOWN", "session_id": "sess_browser_002"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"


@pytest.mark.anyio
async def test_vision_gallery_sync_endpoint():
    transport = ASGITransport(app=app)
    db = mongodb.get_database()
    await db["student_profiles"].insert_one(
        {
            "student_id": "DS202699",
            "name": "Vikram Verma",
            "identity": "DS202699",
            "class_code": "DS-B",
            "has_biometric": True,
        }
    )
    dummy_vec = [0.05] * 512
    await db["biometric_profiles"].insert_one(
        {
            "identity": "DS202699",
            "mean_embedding": dummy_vec,
            "sample_count": 1,
            "quality_score": 0.95,
            "enrolled_by": "self",
        }
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/attendance/vision-gallery")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        vikram = next((g for g in data["gallery"] if g["identity"] == "DS202699"), None)
        assert vikram is not None
        assert vikram["name"] == "Vikram Verma"
        assert vikram["student_id"] == "DS202699"
        assert len(vikram["embedding"]) == 512


@pytest.mark.anyio
async def test_newly_enrolled_student_marked_present(teacher_auth_headers):
    transport = ASGITransport(app=app)
    db = mongodb.get_database()
    sess_id = "sess_browser_new_001"
    await db["sessions"].insert_one(
        {
            "session_id": sess_id,
            "course_name": "Machine Learning — DS-B",
            "status": "ACTIVE",
            "created_by": "teacher_browser_test",
            "start_time": datetime.now(timezone.utc),
        }
    )
    await db["student_profiles"].insert_one(
        {
            "student_id": "DS202699",
            "name": "Vikram Verma",
            "identity": "DS202699",
            "class_code": "DS-B",
            "has_biometric": True,
        }
    )
    await db["session_rosters"].insert_one(
        {
            "session_id": sess_id,
            "identities": ["student1", "DS202699"],
        }
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Mark newly enrolled student
        resp = await client.post(
            "/api/v1/attendance/mark",
            json={"identity": "DS202699", "session_id": sess_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "marked"
        assert data["identity"] == "DS202699"
        assert data["student_name"] == "Vikram Verma"

        # Check idempotency
        resp_dup = await client.post(
            "/api/v1/attendance/mark",
            json={"identity": "DS202699", "session_id": sess_id},
        )
        assert resp_dup.status_code == 200
        assert resp_dup.json()["status"] == "already_present"

        # Verify session roster status
        att_resp = await client.get(
            f"/api/v1/attendance/{sess_id}",
            headers=teacher_auth_headers,
        )
        assert att_resp.status_code == 200
        records = att_resp.json()["records"]
        vikram_rec = next((r for r in records if r["identity"] == "DS202699"), None)
        assert vikram_rec is not None
        assert vikram_rec["status"] == "PRESENT"
        assert vikram_rec["student_name"] == "Vikram Verma"
