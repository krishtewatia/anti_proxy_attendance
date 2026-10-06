from datetime import datetime, timezone

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.database import mongodb
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from tests.conftest import FRAME_BYTES


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
async def test_active_session_query(teacher_auth_headers, service_key_headers):
    # The active-session lookup is an internal route: it now needs the service key.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Initially no active session
        resp = await client.get("/api/v1/attendance/active-session", headers=service_key_headers)
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

        resp2 = await client.get("/api/v1/attendance/active-session", headers=service_key_headers)
        assert resp2.status_code == 200
        assert resp2.json()["has_active_session"] is True
        assert resp2.json()["session_id"] == "sess_live_123"


@pytest.mark.anyio
async def test_mark_student_present_and_duplicate_prevention(teacher_auth_headers, vision_frames):
    # Marking now happens only through the authenticated frame route, backed by a
    # signed recognition result from the (stubbed) vision service.
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
            "full_name": "Alex Example",
            "biometric_identity": "student1",
        }
    )
    await db["session_rosters"].insert_one(
        {
            "session_id": "sess_browser_001",
            "identities": ["student1", "student2", "student3"],
        }
    )
    frame_url = "/api/v1/attendance/sess_browser_001/process-frame"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. First recognition marks PRESENT
        vision_frames.faces = [
            vision_frames.recognized("sess_browser_001", "student1", name="Alex Example")
        ]
        mark_resp = await client.post(frame_url, headers=teacher_auth_headers, content=FRAME_BYTES)
        assert mark_resp.status_code == 200
        data1 = mark_resp.json()
        assert data1["faces"][0]["mark_status"] == "marked"
        assert data1["identity"] == "student1"
        assert data1["student_name"] == "Alex Example"

        # 2. Duplicate frame recognition is idempotent
        vision_frames.faces = [
            vision_frames.recognized("sess_browser_001", "student1", name="Alex Example")
        ]
        dup_resp = await client.post(frame_url, headers=teacher_auth_headers, content=FRAME_BYTES)
        assert dup_resp.status_code == 200
        data2 = dup_resp.json()
        assert data2["faces"][0]["mark_status"] == "already_present"

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
async def test_mark_attendance_rejects_unknown(teacher_auth_headers, vision_frames):
    # An UNKNOWN face in a frame never produces an attendance record.
    transport = ASGITransport(app=app)
    db = mongodb.get_database()
    await db["sessions"].insert_one(
        {
            "session_id": "sess_browser_002",
            "status": "ACTIVE",
            "created_by": "teacher_browser_test",
            "start_time": datetime.now(timezone.utc),
        }
    )
    await db["session_rosters"].insert_one(
        {"session_id": "sess_browser_002", "identities": ["student1"]}
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        vision_frames.faces = [vision_frames.unknown()]
        resp = await client.post(
            "/api/v1/attendance/sess_browser_002/process-frame",
            headers=teacher_auth_headers,
            content=FRAME_BYTES,
        )
        assert resp.status_code == 200
        assert resp.json()["recognized"] is False
        assert resp.json()["faces"][0]["status"] == "unknown"

    assert await db["attendance_records"].count_documents({"session_id": "sess_browser_002"}) == 0


@pytest.mark.anyio
async def test_vision_gallery_sync_endpoint(service_key_headers):
    # The biometric gallery is an internal route: it now needs the service key.
    transport = ASGITransport(app=app)
    db = mongodb.get_database()
    await db["student_profiles"].insert_one(
        {
            "student_id": "DS202699",
            "name": "Eden Testcase",
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
        unauthenticated = await client.get("/api/v1/attendance/vision-gallery")
        assert unauthenticated.status_code == 401

        resp = await client.get("/api/v1/attendance/vision-gallery", headers=service_key_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        eden = next((g for g in data["gallery"] if g["identity"] == "DS202699"), None)
        assert eden is not None
        assert eden["name"] == "Eden Testcase"
        assert eden["student_id"] == "DS202699"
        assert len(eden["embedding"]) == 512


@pytest.mark.anyio
async def test_newly_enrolled_student_marked_present(teacher_auth_headers, vision_frames):
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
            "name": "Eden Testcase",
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
    frame_url = f"/api/v1/attendance/{sess_id}/process-frame"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Mark newly enrolled student
        vision_frames.faces = [vision_frames.recognized(sess_id, "DS202699", name="Eden Testcase")]
        resp = await client.post(frame_url, headers=teacher_auth_headers, content=FRAME_BYTES)
        assert resp.status_code == 200
        data = resp.json()
        assert data["faces"][0]["mark_status"] == "marked"
        assert data["identity"] == "DS202699"
        assert data["student_name"] == "Eden Testcase"

        # Check idempotency
        vision_frames.faces = [vision_frames.recognized(sess_id, "DS202699", name="Eden Testcase")]
        resp_dup = await client.post(frame_url, headers=teacher_auth_headers, content=FRAME_BYTES)
        assert resp_dup.status_code == 200
        assert resp_dup.json()["faces"][0]["mark_status"] == "already_present"

        # Verify session roster status
        att_resp = await client.get(
            f"/api/v1/attendance/{sess_id}",
            headers=teacher_auth_headers,
        )
        assert att_resp.status_code == 200
        records = att_resp.json()["records"]
        eden_rec = next((r for r in records if r["identity"] == "DS202699"), None)
        assert eden_rec is not None
        assert eden_rec["status"] == "PRESENT"
        assert eden_rec["student_name"] == "Eden Testcase"
