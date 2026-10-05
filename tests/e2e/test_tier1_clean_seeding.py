"""Tier 1: Clean Seeding & Biometric Validation E2E Tests.

Validates Requirement R1 & Milestone M1:
- Collection counts after purge (no mock users alice, bob, charlie).
- Exact demo accounts: 1 Admin, 1 Teacher, 4 Students.
- Camera configuration: CAM_ROOM_101_DOOR with vertical line boundary.
- Biometric profiles: Genuine 512-d unit vectors from InsightFace.
- Authentication: Bcrypt verification & login via /api/v1/auth/login.
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
import sys
from typing import Any

# Ensure local test directory is importable
_E2E_DIR = Path(__file__).resolve().parent
if str(_E2E_DIR) not in sys.path:
    sys.path.insert(0, str(_E2E_DIR))

from conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    CAMERA_ID,
    ROOM_ID,
    SESSION_ID,
    STUDENT_PASSWORD,
    STUDENT_ROSTER,
    STUDENT_USER_MAP,
    TEACHER_EMAIL,
    TEACHER_PASSWORD,
)
from httpx import AsyncClient
import numpy as np
import pytest
from pymongo.database import Database

pytestmark = [pytest.mark.anyio, pytest.mark.e2e]


async def test_clean_seeding_collection_counts(mongo_db: Database, clean_seed: dict[str, Any]) -> None:
    """Validate that collections contain exactly the demo entities and zero mock remnants."""
    # 1. Assert synthetic mock users are completely absent
    legacy_mock_emails = ["alice@demo.edu", "bob@demo.edu", "charlie@demo.edu", "david@demo.edu"]
    mock_users = list(mongo_db.users.find({"email": {"$in": legacy_mock_emails}}))
    assert len(mock_users) == 0, f"Found unexpected mock users in database: {mock_users}"

    legacy_mock_identities = ["student_alice", "student_bob", "student_charlie", "student_david"]
    mock_bios = list(mongo_db.biometric_profiles.find({"identity": {"$in": legacy_mock_identities}}))
    assert len(mock_bios) == 0, f"Found unexpected mock biometric profiles: {mock_bios}"

    # 2. Assert exact demo collection counts
    users_count = mongo_db.users.count_documents({})
    assert users_count == 6, f"Expected exactly 6 users (1 admin, 1 teacher, 4 students), found {users_count}"

    student_profiles_count = mongo_db.student_profiles.count_documents({})
    assert student_profiles_count == 4, f"Expected 4 student profiles, found {student_profiles_count}"

    bio_count = mongo_db.biometric_profiles.count_documents({})
    assert bio_count == 4, f"Expected 4 biometric profiles, found {bio_count}"

    camera_count = mongo_db.cameras.count_documents({})
    assert camera_count == 1, f"Expected 1 camera, found {camera_count}"

    session_count = mongo_db.sessions.count_documents({})
    assert session_count == 1, f"Expected 1 active demo session, found {session_count}"

    roster_count = mongo_db.session_rosters.count_documents({})
    assert roster_count == 1, f"Expected 1 session roster, found {roster_count}"


async def test_doorway_camera_vertical_boundary(mongo_db: Database, clean_seed: dict[str, Any]) -> None:
    """Validate that CAM_ROOM_101_DOOR has vertical boundary geometry."""
    camera = mongo_db.cameras.find_one({"camera_id": CAMERA_ID})
    assert camera is not None, f"Camera {CAMERA_ID} missing from database"
    assert camera.get("classroom_id") == ROOM_ID
    assert camera.get("enabled") is True
    assert camera.get("status") == "CONNECTED"

    boundary = camera.get("boundary_config")
    assert boundary is not None, "Missing boundary_config on camera"
    p1 = boundary.get("p1")
    p2 = boundary.get("p2")
    assert p1 == [0.5, 0.0], f"Expected p1 == [0.5, 0.0], got {p1}"
    assert p2 == [0.5, 1.0], f"Expected p2 == [0.5, 1.0], got {p2}"
    assert boundary.get("entry_side") == "SIDE_A"

    # Mathematical assertion: line is purely vertical (x1 == x2 == 0.5)
    assert math.isclose(p1[0], 0.5, abs_tol=1e-5)
    assert math.isclose(p2[0], 0.5, abs_tol=1e-5)
    assert math.isclose(p1[1], 0.0, abs_tol=1e-5)
    assert math.isclose(p2[1], 1.0, abs_tol=1e-5)


async def test_authentic_512d_biometric_embeddings(mongo_db: Database, clean_seed: dict[str, Any]) -> None:
    """Validate authentic 512-d InsightFace unit vectors for person_01..04."""
    profiles = list(mongo_db.biometric_profiles.find({"identity": {"$in": STUDENT_ROSTER}}))
    assert len(profiles) == 4, f"Expected 4 biometric profiles, found {len(profiles)}"

    vectors: dict[str, np.ndarray] = {}

    for prof in profiles:
        ident = prof["identity"]
        assert ident in STUDENT_ROSTER
        assert prof.get("student_id") is not None

        emb = prof.get("mean_embedding")
        assert isinstance(emb, list), f"mean_embedding for {ident} must be a list"
        assert len(emb) == 512, f"Embedding for {ident} must be exactly 512 floats, got {len(emb)}"

        arr = np.array(emb, dtype=np.float32)

        # 1. L2 Norm must be exactly 1.0 (unit vector)
        norm = float(np.linalg.norm(arr))
        assert math.isclose(norm, 1.0, abs_tol=1e-4), (
            f"Embedding for {ident} must be L2-normalized to 1.0, got {norm:.6f}"
        )

        # 2. Vector variance must be non-trivial (not constant zeros or repeated mock formula)
        variance = float(np.var(arr))
        assert variance > 1e-4, f"Variance for {ident} too low ({variance}); likely dummy/mock data"

        vectors[ident] = arr

    # 3. Assert identity separation (cosine similarity between distinct individuals < 0.80)
    for i in range(len(STUDENT_ROSTER)):
        for j in range(i + 1, len(STUDENT_ROSTER)):
            id_a = STUDENT_ROSTER[i]
            id_b = STUDENT_ROSTER[j]
            cos_sim = float(np.dot(vectors[id_a], vectors[id_b]))
            assert cos_sim < 0.80, (
                f"Cosine similarity between {id_a} and {id_b} too high ({cos_sim:.4f}); identities not separated"
            )


async def test_user_credentials_authentication(api_client: AsyncClient, clean_seed: dict[str, Any]) -> None:
    """Validate bcrypt password hashing and login via POST /api/v1/auth/login."""
    # 1. Admin Login
    admin_res = await api_client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert admin_res.status_code == 200, f"Admin login failed: {admin_res.text}"
    admin_data = admin_res.json()
    assert "access_token" in admin_data
    assert admin_data.get("token_type") == "bearer"

    # 2. Teacher Login
    teacher_res = await api_client.post(
        "/api/v1/auth/login",
        json={"email": TEACHER_EMAIL, "password": TEACHER_PASSWORD},
    )
    assert teacher_res.status_code == 200, f"Teacher login failed: {teacher_res.text}"
    teacher_data = teacher_res.json()
    assert "access_token" in teacher_data

    # 3. All 4 Students Login
    for ident, (stu_name, stu_id, _) in STUDENT_USER_MAP.items():
        stu_res = await api_client.post(
            "/api/v1/auth/login",
            json={"email": f"{stu_name}@demo.edu", "password": STUDENT_PASSWORD},
        )
        assert stu_res.status_code == 200, f"Student {stu_name} login failed: {stu_res.text}"
        stu_data = stu_res.json()
        assert "access_token" in stu_data

    # 4. Bad Password Rejection
    bad_res = await api_client.post(
        "/api/v1/auth/login",
        json={"email": TEACHER_EMAIL, "password": "WrongPassword999!"},
    )
    assert bad_res.status_code == 401, f"Expected 401 on bad password, got {bad_res.status_code}"


async def test_active_demo_session_configuration(mongo_db: Database, clean_seed: dict[str, Any]) -> None:
    """Validate active session sess_demo_cs101 time window and roster."""
    session = mongo_db.sessions.find_one({"session_id": SESSION_ID})
    assert session is not None, f"Session {SESSION_ID} missing from database"
    assert session.get("classroom_id") == ROOM_ID
    assert session.get("created_by") == "user_teacher_demo"
    assert session.get("status") == "ACTIVE"

    now = dt.datetime.now(dt.timezone.utc)
    start_time = session.get("start_time")
    end_time = session.get("end_time")

    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=dt.timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=dt.timezone.utc)

    # Time window must span current moment
    assert start_time <= now <= end_time, (
        f"Session window [{start_time} - {end_time}] does not encompass current time {now}"
    )

    # Roster must enroll all 4 demo students
    roster = mongo_db.session_rosters.find_one({"session_id": SESSION_ID})
    assert roster is not None, f"Session roster for {SESSION_ID} missing"
    identities = roster.get("identities", [])
    for ident in STUDENT_ROSTER:
        assert ident in identities, f"Student {ident} missing from session roster: {identities}"
