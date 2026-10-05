"""Pytest fixtures and configuration for Anti-Proxy E2E Testing Track."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import sys
from typing import Any, AsyncGenerator

import bcrypt
import httpx
from httpx import ASGITransport, AsyncClient
import pytest
from pymongo import MongoClient

# Configure sys.path so backend app and utilities are importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Configuration Constants
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
DATABASE_NAME = os.getenv("DATABASE_NAME", "anti_proxy_attendance")

# Credentials adhering to ORIGINAL_REQUEST.md & PROJECT.md
ADMIN_EMAIL = "admin@system.local"
ADMIN_PASSWORD = "AdminDevPass123!"

TEACHER_EMAIL = "teacher@demo.edu"
TEACHER_PASSWORD = "TeacherDevPass123!"

STUDENT_PASSWORD = "StudentDevPass123!"

VISION_SERVICE_API_KEY = os.getenv(
    "VISION_SERVICE_API_KEY", "test_vision_api_key_for_smoke_test_12345"
)
CAMERA_ID = "CAM_ROOM_101_DOOR"
ROOM_ID = "ROOM_101"
SESSION_ID = "sess_demo_cs101"

STUDENT_ROSTER = ["person_01", "person_02", "person_03", "person_04"]
STUDENT_USER_MAP = {
    "person_01": ("student1", "STU_001", "user_student_001"),
    "person_02": ("student2", "STU_002", "user_student_002"),
    "person_03": ("student3", "STU_003", "user_student_003"),
    "person_04": ("student4", "STU_004", "user_student_004"),
}


def get_mongo_connection_uri() -> str:
    """Derive resilient MongoDB connection string with authentication fallback."""
    explicit_uri = os.getenv("MONGO_URI") or os.getenv("MONGODB_URL")
    if explicit_uri and "@" in explicit_uri:
        return explicit_uri

    # Standard dev credentials matching docker-compose / init-mongo.js
    app_user = os.getenv("MONGO_APP_USERNAME", "antiproxy_user")
    app_pwd = os.getenv("MONGO_APP_PASSWORD", "secure_app_mongo_dev_password_12345")
    auth_source = os.getenv("DATABASE_NAME", "anti_proxy_attendance")
    auth_uri = f"mongodb://{app_user}:{app_pwd}@localhost:27017/{auth_source}?authSource={auth_source}"

    # Verify if authenticated URI succeeds
    try:
        c = MongoClient(auth_uri, serverSelectionTimeoutMS=1000)
        c.admin.command("ping")
        c.close()
        return auth_uri
    except Exception:
        pass

    # Root admin fallback
    root_user = os.getenv("MONGO_ROOT_USERNAME", "admin")
    root_pwd = os.getenv("MONGO_ROOT_PASSWORD", "secure_root_mongo_dev_password_12345")
    root_uri = f"mongodb://{root_user}:{root_pwd}@localhost:27017/{auth_source}?authSource=admin"
    try:
        c = MongoClient(root_uri, serverSelectionTimeoutMS=1000)
        c.admin.command("ping")
        c.close()
        return root_uri
    except Exception:
        pass

    # Default unauthenticated localhost fallback
    return explicit_uri or "mongodb://localhost:27017"


@pytest.fixture(scope="session")
def mongo_client() -> MongoClient:
    """Session-scoped PyMongo client."""
    uri = get_mongo_connection_uri()
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except Exception as exc:
        pytest.fail(f"Could not connect to MongoDB at {uri}: {exc}")
    yield client
    client.close()


@pytest.fixture(scope="session")
def mongo_db(mongo_client: MongoClient):
    """Session-scoped PyMongo database instance."""
    return mongo_client[DATABASE_NAME]


def load_benchmark_embeddings() -> dict[str, list[float]]:
    """Load authentic 512-d InsightFace embeddings from survey_explorer_1."""
    embed_file = PROJECT_ROOT / ".agents" / "teamwork" / "survey_explorer_1" / "benchmark_embeddings.json"
    if embed_file.exists():
        with open(embed_file, "r", encoding="utf-8") as f:
            return json.load(f)
    raise FileNotFoundError(f"Benchmark embeddings file missing at {embed_file}")


def seed_clean_demo_state(db) -> dict[str, Any]:
    """Seed pristine 4-student demo state adhering to PROJECT.md & ORIGINAL_REQUEST.md."""
    now = dt.datetime.now(dt.timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    # 1. Clean synthetic mock collections
    db.users.delete_many({})
    db.student_profiles.delete_many({})
    db.biometric_profiles.delete_many({})
    db.sessions.delete_many({})
    db.session_rosters.delete_many({})
    if "session_roster" in db.list_collection_names():
        db.session_roster.delete_many({})
    db.cameras.delete_many({})
    db.attendance_events.delete_many({})
    db.attendance_records.delete_many({})
    db.attendance_corrections.delete_many({})

    # 2. Seed Admin
    admin_pw_hash = bcrypt.hashpw(ADMIN_PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    admin_doc = {
        "user_id": "user_admin_001",
        "email": ADMIN_EMAIL,
        "role": "ADMIN",
        "password_hash": admin_pw_hash,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    db.users.insert_one(admin_doc)

    # 3. Seed Teacher
    teacher_pw_hash = bcrypt.hashpw(TEACHER_PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    teacher_doc = {
        "user_id": "user_teacher_demo",
        "email": TEACHER_EMAIL,
        "role": "TEACHER",
        "password_hash": teacher_pw_hash,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    db.users.insert_one(teacher_doc)

    # 4. Seed 4 Students & Biometric Profiles
    embeddings = load_benchmark_embeddings()
    student_pw_hash = bcrypt.hashpw(STUDENT_PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    for identity, (stu_name, stu_id, user_uid) in STUDENT_USER_MAP.items():
        # User record
        db.users.insert_one({
            "user_id": user_uid,
            "email": f"{stu_name}@demo.edu",
            "role": "STUDENT",
            "student_id": stu_id,
            "name": f"Student {stu_name[-1]}",
            "password_hash": student_pw_hash,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        })

        # Student Profile
        db.student_profiles.insert_one({
            "user_id": user_uid,
            "identity": identity,
            "student_id": stu_id,
            "name": f"Student {stu_name[-1]}",
            "created_at": now,
            "updated_at": now,
        })

        # Biometric Profile
        mean_vec = embeddings[identity]
        db.biometric_profiles.insert_one({
            "identity": identity,
            "student_id": stu_id,
            "model": "buffalo_l",
            "dim": 512,
            "mean_embedding": mean_vec,
            "sample_count": 3,
            "quality_score": 0.95,
            "enrolled_by": "seed_clean_demo",
            "status": "ENROLLED",
            "created_at": now,
            "updated_at": now,
        })

    # 5. Seed Doorway Camera with Vertical Boundary
    db.cameras.insert_one({
        "camera_id": CAMERA_ID,
        "classroom_id": ROOM_ID,
        "role": "BOTH",
        "source_type": "PHONE",
        "rtsp_url": None,
        "secret_reference": None,
        "enabled": True,
        "boundary_config": {
            "p1": [0.5, 0.0],
            "p2": [0.5, 1.0],
            "entry_side": "SIDE_A",
            "deadband_pixels": 4.0,
        },
        "status": "CONNECTED",
        "last_seen": now,
        "fps": 15.0,
        "created_at": now,
        "updated_at": now,
    })

    # 6. Seed Active Session & Roster
    db.sessions.insert_one({
        "session_id": SESSION_ID,
        "course_name": "CS-101 Introduction to Computer Science",
        "classroom_id": ROOM_ID,
        "teacher_id": "user_teacher_demo",
        "created_by": "user_teacher_demo",
        "start_time": today_start,
        "end_time": today_end,
        "required_presence_percentage": 75.0,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
    })

    db.session_rosters.insert_one({
        "session_id": SESSION_ID,
        "identities": STUDENT_ROSTER,
        "created_at": now,
        "updated_at": now,
    })

    return {
        "admin": ADMIN_EMAIL,
        "teacher": TEACHER_EMAIL,
        "students": STUDENT_ROSTER,
        "session_id": SESSION_ID,
        "camera_id": CAMERA_ID,
    }


@pytest.fixture(scope="session")
def clean_seed(mongo_db) -> dict[str, Any]:
    """Ensure clean demo database seeding is applied for E2E tests."""
    return seed_clean_demo_state(mongo_db)


@pytest.fixture
def anyio_backend():
    """Specify AsyncIO backend for AnyIO pytest runner."""
    return "asyncio"


@pytest.fixture
async def api_client() -> AsyncGenerator[AsyncClient, None]:
    """Asynchronous HTTP test client targeting live FastAPI or ASGI fallback."""
    # Check if live server is reachable on API_BASE_URL
    is_live = False
    try:
        async with AsyncClient(base_url=API_BASE_URL, timeout=1.0) as check_client:
            res = await check_client.get("/health")
            if res.status_code == 200:
                is_live = True
    except Exception:
        is_live = False

    if is_live:
        async with AsyncClient(base_url=API_BASE_URL, timeout=10.0) as client:
            yield client
    else:
        # Fallback to ASGI in-process transport
        from app.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver", timeout=10.0) as client:
            yield client


@pytest.fixture
async def admin_token(api_client: AsyncClient, clean_seed) -> str:
    """Retrieve authenticated JWT bearer token for Admin."""
    res = await api_client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert res.status_code == 200, f"Admin login failed: {res.text}"
    return res.json()["access_token"]


@pytest.fixture
async def teacher_token(api_client: AsyncClient, clean_seed) -> str:
    """Retrieve authenticated JWT bearer token for Demo Teacher."""
    res = await api_client.post(
        "/api/v1/auth/login",
        json={"email": TEACHER_EMAIL, "password": TEACHER_PASSWORD},
    )
    assert res.status_code == 200, f"Teacher login failed: {res.text}"
    return res.json()["access_token"]


@pytest.fixture
async def student_token(api_client: AsyncClient, clean_seed) -> str:
    """Retrieve authenticated JWT bearer token for Demo Student 1."""
    res = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "student1@demo.edu", "password": STUDENT_PASSWORD},
    )
    assert res.status_code == 200, f"Student login failed: {res.text}"
    return res.json()["access_token"]


@pytest.fixture
def teacher_headers(teacher_token: str) -> dict[str, str]:
    """HTTP headers with Teacher authorization."""
    return {"Authorization": f"Bearer {teacher_token}"}


@pytest.fixture
def vision_headers() -> dict[str, str]:
    """HTTP headers for camera/vision service event dispatch."""
    return {"X-API-Key": VISION_SERVICE_API_KEY}
