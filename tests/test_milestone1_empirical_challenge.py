"""Empirical Stress-Test & Challenge Suite for Milestone 1.

Authored by: Challenger 2 (teamwork_preview_challenger)
Purpose: Independent verification and stress-testing of Milestone 1:
  1. Idempotency across multiple consecutive seed executions
  2. Camera boundary geometry & schema validation (CAM_ROOM_101_DOOR x=0.5 vertical line)
  3. Session time window validation (start_time <= current_time <= end_time)
  4. Student profiles, biometric profiles, and session roster consistency (STU_001..STU_004 & person_01..person_04)
  5. Biometric embedding mathematical invariants (512-d, unit norm, distinctness)
  6. End-to-end API verification (Auth, Live Snapshot, Students Directory, Gallery)
"""

from __future__ import annotations

import datetime as dt
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from pymongo import MongoClient
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MONGO_URI = (
    os.getenv("MONGODB_URL")
    or os.getenv("MONGO_URI")
    or "mongodb://antiproxy_user:secure_app_mongo_dev_password_12345@localhost:27017/anti_proxy_attendance?authSource=anti_proxy_attendance"
)
DB_NAME = "anti_proxy_attendance"
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
VISION_API_KEY = os.getenv("VISION_SERVICE_API_KEY", "test_vision_api_key_for_smoke_test_12345")

ADMIN_EMAIL = "admin@system.local"
ADMIN_PASSWORD = "AdminDevPass123!"
TEACHER_EMAIL = "teacher@demo.edu"
TEACHER_PASSWORD = "TeacherDevPass123!"
STUDENT_PASSWORD = "StudentDevPass123!"

EXPECTED_STUDENTS = [
    {"user_id": "user_student_001", "student_id": "STU_001", "identity": "person_01", "name": "student1", "email": "student1@demo.edu"},
    {"user_id": "user_student_002", "student_id": "STU_002", "identity": "person_02", "name": "student2", "email": "student2@demo.edu"},
    {"user_id": "user_student_003", "student_id": "STU_003", "identity": "person_03", "name": "student3", "email": "student3@demo.edu"},
    {"user_id": "user_student_004", "student_id": "STU_004", "identity": "person_04", "name": "student4", "email": "student4@demo.edu"},
]

COLLECTION_TARGETS = {
    "users": 6,
    "student_profiles": 4,
    "biometric_profiles": 4,
    "cameras": 1,
    "sessions": 1,
    "session_rosters": 1,
    "session_roster": 0,
    "attendance_events": 0,
    "attendance_records": 0,
    "attendance_corrections": 0,
}


def get_db():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    return client[DB_NAME], client


def run_seeder() -> subprocess.CompletedProcess:
    """Execute python scripts/seed_clean_demo.py."""
    cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "seed_clean_demo.py")]
    res = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=120)
    return res


def test_idempotency_multi_run():
    """Challenge 1: Re-run seed_clean_demo.py multiple times and assert exact counts and no duplicate key errors."""
    print("\n--- [CHALLENGE 1] Testing Seeding Idempotency Multi-Run ---")
    db, client = get_db()

    for run_idx in range(1, 4):
        print(f"  Executing seed run #{run_idx}...")
        res = run_seeder()
        assert res.returncode == 0, f"Seed run #{run_idx} failed with exit code {res.returncode}:\nSTDERR:\n{res.stderr}\nSTDOUT:\n{res.stdout}"
        assert "E11000 duplicate key error" not in res.stderr
        assert "DuplicateKeyError" not in res.stderr

        # Check collection counts
        for col, expected_count in COLLECTION_TARGETS.items():
            actual_count = db[col].count_documents({})
            assert actual_count == expected_count, (
                f"Run #{run_idx}: Collection '{col}' has {actual_count} docs, expected {expected_count}"
            )
        print(f"  Run #{run_idx} passed: All collection counts exact, zero duplicate key errors.")

    client.close()


def test_camera_boundary_configuration():
    """Challenge 2: Validate CAM_ROOM_101_DOOR has vertical dividing line x=0.5."""
    print("\n--- [CHALLENGE 2] Validating Camera Boundary Configuration ---")
    db, client = get_db()

    camera = db.cameras.find_one({"camera_id": "CAM_ROOM_101_DOOR"})
    assert camera is not None, "Camera CAM_ROOM_101_DOOR not found in MongoDB"
    assert camera["classroom_id"] == "ROOM_101", f"Expected classroom_id 'ROOM_101', got {camera.get('classroom_id')}"
    assert camera["enabled"] is True, "Camera must be enabled"
    assert camera["status"] == "CONNECTED", f"Expected status 'CONNECTED', got {camera.get('status')}"

    boundary = camera.get("boundary_config")
    assert boundary is not None, "boundary_config is missing from camera document"
    assert "p1" in boundary and "p2" in boundary, f"p1 or p2 missing in boundary_config: {boundary}"

    p1 = boundary["p1"]
    p2 = boundary["p2"]
    assert isinstance(p1, (list, tuple)) and len(p1) == 2, f"p1 must be 2D coordinate, got {p1}"
    assert isinstance(p2, (list, tuple)) and len(p2) == 2, f"p2 must be 2D coordinate, got {p2}"

    # Strict mathematical verification of vertical line at x = 0.5
    x1, y1 = float(p1[0]), float(p1[1])
    x2, y2 = float(p2[0]), float(p2[1])

    assert math.isclose(x1, 0.5, abs_tol=1e-5), f"p1 x-coordinate must be 0.5, got {x1}"
    assert math.isclose(x2, 0.5, abs_tol=1e-5), f"p2 x-coordinate must be 0.5, got {x2}"
    assert math.isclose(x1, x2, abs_tol=1e-5), f"Boundary line must be vertical (x1 == x2), got x1={x1}, x2={x2}"
    assert y1 != y2, f"Boundary line cannot have zero length (y1={y1}, y2={y2})"
    assert boundary.get("entry_side") == "SIDE_A", f"Expected entry_side 'SIDE_A', got {boundary.get('entry_side')}"

    print(f"  [OK] Camera CAM_ROOM_101_DOOR boundary verified: p1=({x1}, {y1}), p2=({x2}, {y2}), entry_side={boundary.get('entry_side')}")
    client.close()


def test_session_time_window():
    """Challenge 3: Validate session time window: assert start_time <= current_time <= end_time."""
    print("\n--- [CHALLENGE 3] Validating Session Time Window ---")
    db, client = get_db()

    session = db.sessions.find_one({"session_id": "sess_demo_cs101"})
    assert session is not None, "Session sess_demo_cs101 not found in MongoDB"
    assert session["classroom_id"] == "ROOM_101"
    assert session["status"] == "ACTIVE"
    assert session["teacher_id"] == "user_teacher_demo"
    assert session["created_by"] == "user_teacher_demo"

    now_utc = dt.datetime.now(dt.timezone.utc)
    start_time = session.get("start_time")
    end_time = session.get("end_time")

    assert start_time is not None, "start_time is missing from session"
    assert end_time is not None, "end_time is missing from session"

    # Make tz-aware if naive UTC
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=dt.timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=dt.timezone.utc)

    # Core assertion: start_time <= current_time <= end_time
    assert start_time <= now_utc <= end_time, (
        f"Session time window failure: start_time ({start_time}) <= now ({now_utc}) <= end_time ({end_time}) violated!"
    )
    assert start_time < end_time, f"start_time ({start_time}) must be strictly earlier than end_time ({end_time})"

    # Span assertion: window should cover the full 24-hour day
    duration = (end_time - start_time).total_seconds()
    assert duration >= 86300.0, f"Expected session window >= ~24 hours (86400s), got {duration}s"

    print(f"  [OK] Session window verified: {start_time.isoformat()} <= {now_utc.isoformat()} <= {end_time.isoformat()} (duration: {duration:.1f}s)")
    client.close()


def test_student_roster_and_profiles_consistency():
    """Challenge 4: Validate student profiles and session roster: assert student_ids match STU_001..STU_004 and person_01..person_04."""
    print("\n--- [CHALLENGE 4] Validating Student Profiles & Session Roster Consistency ---")
    db, client = get_db()

    # 1. Check student_profiles
    profiles = list(db.student_profiles.find({}))
    assert len(profiles) == 4, f"Expected 4 student profiles, got {len(profiles)}"

    profile_by_stu_id = {p["student_id"]: p for p in profiles}
    profile_by_ident = {p["identity"]: p for p in profiles}

    for spec in EXPECTED_STUDENTS:
        sid = spec["student_id"]
        ident = spec["identity"]
        assert sid in profile_by_stu_id, f"student_id {sid} missing from student_profiles"
        assert ident in profile_by_ident, f"identity {ident} missing from student_profiles"

        p = profile_by_stu_id[sid]
        assert p["identity"] == ident, f"Profile mismatch for {sid}: expected {ident}, got {p.get('identity')}"
        assert p["user_id"] == spec["user_id"], f"user_id mismatch for {sid}: expected {spec['user_id']}, got {p.get('user_id')}"
        assert p["name"] == spec["name"], f"name mismatch for {sid}: expected {spec['name']}, got {p.get('name')}"

    # 2. Check biometric_profiles
    bios = list(db.biometric_profiles.find({}))
    assert len(bios) == 4, f"Expected 4 biometric profiles, got {len(bios)}"
    bio_by_ident = {b["identity"]: b for b in bios}

    for spec in EXPECTED_STUDENTS:
        ident = spec["identity"]
        sid = spec["student_id"]
        assert ident in bio_by_ident, f"identity {ident} missing from biometric_profiles"
        b = bio_by_ident[ident]
        assert b["student_id"] == sid, f"Biometric profile student_id mismatch for {ident}: expected {sid}, got {b.get('student_id')}"
        assert b["status"] == "ENROLLED", f"Biometric status for {ident} must be ENROLLED, got {b.get('status')}"
        assert b["enrolled_by"] == "user_teacher_demo"

        # Check embedding dimensions and norm
        emb = b.get("mean_embedding")
        assert isinstance(emb, list) and len(emb) == 512, f"Embedding for {ident} must be 512 floats, got {len(emb) if isinstance(emb, list) else type(emb)}"
        norm = math.sqrt(sum(float(x) * float(x) for x in emb))
        assert math.isclose(norm, 1.0, abs_tol=1e-5), f"Embedding for {ident} must be unit-normalized, got norm {norm:.6f}"

    # 3. Check session_rosters
    roster_doc = db.session_rosters.find_one({"session_id": "sess_demo_cs101"})
    assert roster_doc is not None, "session_rosters document missing for sess_demo_cs101"

    roster_idents = roster_doc.get("identities", [])
    roster_sids = roster_doc.get("student_ids", [])

    expected_idents = [s["identity"] for s in EXPECTED_STUDENTS]
    expected_sids = [s["student_id"] for s in EXPECTED_STUDENTS]

    assert sorted(roster_idents) == sorted(expected_idents), f"Roster identities mismatch: expected {expected_idents}, got {roster_idents}"
    assert sorted(roster_sids) == sorted(expected_sids), f"Roster student_ids mismatch: expected {expected_sids}, got {roster_sids}"

    # 4. Check users collection
    student_users = list(db.users.find({"role": "STUDENT"}))
    assert len(student_users) == 4, f"Expected 4 student users, got {len(student_users)}"
    user_by_email = {u["email"]: u for u in student_users}

    for spec in EXPECTED_STUDENTS:
        em = spec["email"]
        assert em in user_by_email, f"User {em} missing from users collection"
        u = user_by_email[em]
        assert u["user_id"] == spec["user_id"], f"user_id mismatch in users: expected {spec['user_id']}, got {u.get('user_id')}"
        assert u["student_id"] == spec["student_id"], f"student_id mismatch in users: expected {spec['student_id']}, got {u.get('student_id')}"
        assert u["is_active"] is True

    print(f"  [OK] All cross-collection student identities and rosters verified: STU_001..STU_004 <-> person_01..person_04")
    client.close()


def test_biometric_distinctness_oracle():
    """Challenge 5: Pairwise cosine similarity oracle across all 4 biometric profiles."""
    print("\n--- [CHALLENGE 5] Validating Biometric Distinctness & Mathematical Invariants ---")
    db, client = get_db()

    bios = list(db.biometric_profiles.find({}))
    emb_dict = {b["identity"]: b["mean_embedding"] for b in bios}

    identities = ["person_01", "person_02", "person_03", "person_04"]
    for i in range(len(identities)):
        for j in range(i + 1, len(identities)):
            id_a = identities[i]
            id_b = identities[j]
            v_a = emb_dict[id_a]
            v_b = emb_dict[id_b]
            cos_sim = sum(a * b for a, b in zip(v_a, v_b))
            print(f"  Cosine similarity {id_a} vs {id_b}: {cos_sim:.4f}")
            assert cos_sim < 0.80, f"Identities {id_a} and {id_b} have high similarity ({cos_sim:.4f}), embeddings not distinct!"

    print("  [OK] Biometric distinctness confirmed: all pairwise cosine similarities < 0.80")
    client.close()


def test_backend_api_integration():
    """Challenge 6: Validate live backend endpoints with seeded credentials."""
    print("\n--- [CHALLENGE 6] Validating Backend API Integration ---")

    # 1. Admin login
    r_admin = requests.post(f"{API_BASE_URL}/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=5)
    assert r_admin.status_code == 200, f"Admin login failed: {r_admin.status_code} {r_admin.text}"
    admin_token = r_admin.json()["access_token"]
    assert r_admin.json()["user"]["role"] == "ADMIN"
    print("  [OK] Admin login successful")

    # 2. Teacher login
    r_teacher = requests.post(f"{API_BASE_URL}/api/v1/auth/login", json={"email": TEACHER_EMAIL, "password": TEACHER_PASSWORD}, timeout=5)
    assert r_teacher.status_code == 200, f"Teacher login failed: {r_teacher.status_code} {r_teacher.text}"
    teacher_token = r_teacher.json()["access_token"]
    assert r_teacher.json()["user"]["role"] == "TEACHER"
    print("  [OK] Teacher login successful")

    # 3. Student logins
    for spec in EXPECTED_STUDENTS:
        r_stu = requests.post(f"{API_BASE_URL}/api/v1/auth/login", json={"email": spec["email"], "password": STUDENT_PASSWORD}, timeout=5)
        assert r_stu.status_code == 200, f"Student {spec['name']} login failed: {r_stu.status_code} {r_stu.text}"
    print("  [OK] All 4 student logins successful")

    # 4. Teacher live session snapshot
    headers = {"Authorization": f"Bearer {teacher_token}"}
    r_snap = requests.get(f"{API_BASE_URL}/api/v1/sessions/sess_demo_cs101/live-snapshot", headers=headers, timeout=5)
    assert r_snap.status_code == 200, f"Live snapshot failed: {r_snap.status_code} {r_snap.text}"
    snap_data = r_snap.json()
    assert snap_data.get("session_id") == "sess_demo_cs101"
    assert snap_data.get("session_state") == "LIVE"
    roster_list = snap_data.get("roster", [])
    assert len(roster_list) == 4, f"Expected 4 students in snapshot roster, got {len(roster_list)}"
    snap_sids = [s["student_id"] for s in roster_list]
    for spec in EXPECTED_STUDENTS:
        assert spec["student_id"] in snap_sids, f"{spec['student_id']} missing from live snapshot"
    print("  [OK] Live snapshot endpoint returns session_state='LIVE' and 4 students in roster")

    # 5. Students directory
    r_dir = requests.get(f"{API_BASE_URL}/api/v1/students/directory", headers=headers, timeout=5)
    assert r_dir.status_code == 200, f"Students directory failed: {r_dir.status_code}"
    dir_data = r_dir.json()
    assert len(dir_data) == 4, f"Expected 4 students in directory, got {len(dir_data)}"
    print("  [OK] Students directory returns 4 students")

    # 6. Biometric gallery endpoint
    vis_headers = {"X-API-Key": VISION_API_KEY}
    r_gal = requests.get(f"{API_BASE_URL}/api/v1/enrollment/gallery", headers=vis_headers, timeout=5)
    assert r_gal.status_code == 200, f"Gallery endpoint failed: {r_gal.status_code} {r_gal.text}"
    gal_data = r_gal.json()
    assert "templates" in gal_data
    assert len(gal_data["templates"]) == 4, f"Expected 4 gallery templates, got {len(gal_data['templates'])}"
    for t in gal_data["templates"]:
        assert len(t["embedding"]) == 512, f"Template embedding dimension must be 512, got {len(t['embedding'])}"
    print("  [OK] Biometric gallery endpoint returns 4 512-d templates")


def main():
    print("=" * 75)
    print("EMPIRICAL CHALLENGER 2: MILESTONE 1 STRESS TEST HARNESS")
    print("=" * 75)
    try:
        test_idempotency_multi_run()
        test_camera_boundary_configuration()
        test_session_time_window()
        test_student_roster_and_profiles_consistency()
        test_biometric_distinctness_oracle()
        test_backend_api_integration()
        print("\n" + "=" * 75)
        print(">>> ALL 6 EMPIRICAL CHALLENGES PASSED! VERDICT: APPROVE <<<")
        print("=" * 75 + "\n")
        return 0
    except AssertionError as exc:
        print("\n" + "=" * 75)
        print(f"!!! CHALLENGE FAILURE: {exc} !!!")
        print("VERDICT: REQUEST_CHANGES")
        print("=" * 75 + "\n")
        return 1
    except Exception as exc:
        print(f"\nUNEXPECTED EXCEPTION: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
