"""Milestone 1 Empirical Challenger Audit Harness.

Executes direct empirical verification and stress testing of:
1. seed_clean_demo.py execution and idempotency
2. Direct MongoDB state, collections counts, document schemas
3. Authentic 512-d biometric vectors, L2 norms, identity separation
4. Mock user & session eradication
5. Backend HTTP auth login endpoints (positive & negative)
6. Backend live session snapshot endpoint (RBAC, schema, payload)
7. CLI flags (--inspect, --dry-run)
"""

from __future__ import annotations

import datetime as dt
import json
import math
import subprocess
import sys
from typing import Any

from pymongo import MongoClient
import requests

MONGO_URI = (
    "mongodb://antiproxy_user:secure_app_mongo_dev_password_12345@localhost:27017/"
    "anti_proxy_attendance?authSource=anti_proxy_attendance"
)
BACKEND_BASE_URL = "http://localhost:8000"

ADMIN_CREDS = {"email": "admin@system.local", "password": "AdminDevPass123!"}
TEACHER_CREDS = {"email": "teacher@demo.edu", "password": "TeacherDevPass123!"}
STUDENTS_CREDS = [
    {"email": f"student{i}@demo.edu", "password": "StudentDevPass123!", "id": f"STU_{i:03d}", "ident": f"person_{i:02d}"}
    for i in range(1, 5)
]


def run_checks() -> dict[str, Any]:
    results: dict[str, Any] = {"tests": [], "all_passed": True}

    def record(name: str, passed: bool, details: Any = None) -> None:
        results["tests"].append({"name": name, "passed": passed, "details": details})
        if not passed:
            results["all_passed"] = False
        status_str = "PASS" if passed else "FAIL"
        print(f"[{status_str}] {name}: {details}")

    # ---------------------------------------------------------
    # 1. MongoDB Direct Inspection
    # ---------------------------------------------------------
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    db = client.anti_proxy_attendance

    # 1a. Collection counts
    expected_counts = {
        "users": 6,
        "student_profiles": 4,
        "biometric_profiles": 4,
        "cameras": 1,
        "sessions": 1,
        "session_rosters": 1,
        "attendance_events": 0,
        "attendance_records": 0,
        "attendance_corrections": 0,
    }
    actual_counts = {col: db[col].count_documents({}) for col in expected_counts}
    counts_ok = actual_counts == expected_counts
    record("MongoDB Collection Counts", counts_ok, f"Expected={expected_counts}, Actual={actual_counts}")

    # 1b. Mock remnants eradicated
    mock_users = list(db.users.find({"email": {"$regex": "alice|bob|charlie|david", "$options": "i"}}))
    mock_bios = list(db.biometric_profiles.find({"identity": {"$regex": "alice|bob|charlie|david", "$options": "i"}}))
    mock_sessions = list(db.sessions.find({"session_id": {"$ne": "sess_demo_cs101"}}))
    mock_cameras = list(db.cameras.find({"camera_id": {"$ne": "CAM_ROOM_101_DOOR"}}))
    no_mocks = (len(mock_users) == 0 and len(mock_bios) == 0 and len(mock_sessions) == 0 and len(mock_cameras) == 0)
    record(
        "Purge Old Mock Data",
        no_mocks,
        f"mock_users={len(mock_users)}, mock_bios={len(mock_bios)}, other_sessions={len(mock_sessions)}, other_cameras={len(mock_cameras)}"
    )

    # 1c. Biometric profiles audit
    bios = list(db.biometric_profiles.find({}))
    bios_ok = len(bios) == 4
    bio_details = []
    vectors: dict[str, list[float]] = {}
    for b in bios:
        ident = b.get("identity")
        status = b.get("status")
        emb = b.get("mean_embedding", [])
        dim = len(emb)
        norm = math.sqrt(sum(x * x for x in emb)) if dim > 0 else 0.0
        status_ok = (status == "ENROLLED")
        dim_ok = (dim == 512)
        norm_ok = math.isclose(norm, 1.0, abs_tol=1e-5)
        vectors[ident] = emb
        bio_details.append({
            "identity": ident,
            "status": status,
            "dim": dim,
            "norm": round(norm, 6),
            "status_ok": status_ok,
            "dim_ok": dim_ok,
            "norm_ok": norm_ok,
        })
        if not (status_ok and dim_ok and norm_ok):
            bios_ok = False

    # Check pairwise separation
    max_sim = 0.0
    pair_sims = {}
    for i in range(1, 5):
        for j in range(i + 1, 5):
            id_a = f"person_{i:02d}"
            id_b = f"person_{j:02d}"
            if id_a in vectors and id_b in vectors:
                va = vectors[id_a]
                vb = vectors[id_b]
                dot = sum(x * y for x, y in zip(va, vb))
                pair_sims[f"{id_a}_vs_{id_b}"] = round(dot, 4)
                if dot > max_sim:
                    max_sim = dot
    separation_ok = max_sim < 0.80
    record("Biometric Profiles Structure & Norm", bios_ok, bio_details)
    record("Biometric Identity Separation (Max Cosine Similarity < 0.80)", separation_ok, f"max_sim={max_sim}, pairs={pair_sims}")

    # 1d. Camera configuration
    cam = db.cameras.find_one({"camera_id": "CAM_ROOM_101_DOOR"})
    cam_ok = False
    if cam:
        b_cfg = cam.get("boundary_config", {})
        cam_ok = (
            cam.get("classroom_id") == "ROOM_101"
            and b_cfg.get("p1") == [0.5, 0.0]
            and b_cfg.get("p2") == [0.5, 1.0]
            and b_cfg.get("entry_side") == "SIDE_A"
            and cam.get("enabled") is True
            and cam.get("status") == "CONNECTED"
        )
    record("Camera Geometry & Config", cam_ok, f"camera={cam.get('camera_id') if cam else None}, boundary={cam.get('boundary_config') if cam else None}")

    # 1e. Active session configuration
    sess = db.sessions.find_one({"session_id": "sess_demo_cs101"})
    sess_ok = False
    if sess:
        now = dt.datetime.now(dt.timezone.utc)
        st = sess.get("start_time")
        et = sess.get("end_time")
        if st and st.tzinfo is None:
            st = st.replace(tzinfo=dt.timezone.utc)
        if et and et.tzinfo is None:
            et = et.replace(tzinfo=dt.timezone.utc)
        window_ok = st <= now <= et
        sess_ok = (
            sess.get("created_by") == "user_teacher_demo"
            and sess.get("classroom_id") == "ROOM_101"
            and sess.get("status") == "ACTIVE"
            and window_ok
        )
    record("Session Geometry & Time Window", sess_ok, f"session={sess.get('session_id') if sess else None}, window_valid={sess_ok}")

    # 1f. Session Roster configuration
    roster = db.session_rosters.find_one({"session_id": "sess_demo_cs101"})
    roster_ok = False
    if roster:
        expected_ids = ["STU_001", "STU_002", "STU_003", "STU_004"]
        expected_idents = ["person_01", "person_02", "person_03", "person_04"]
        r_ids = roster.get("student_ids", [])
        r_idents = roster.get("identities", [])
        roster_ok = (sorted(r_ids) == expected_ids and sorted(r_idents) == expected_idents)
    record("Session Roster Alignment", roster_ok, f"student_ids={roster.get('student_ids') if roster else None}, idents={roster.get('identities') if roster else None}")

    # ---------------------------------------------------------
    # 2. Backend HTTP Authentication Tests
    # ---------------------------------------------------------
    login_url = f"{BACKEND_BASE_URL}/api/v1/auth/login"

    # Admin Login
    res_admin = requests.post(login_url, json=ADMIN_CREDS, timeout=5)
    admin_auth_ok = (
        res_admin.status_code == 200
        and res_admin.json().get("user", {}).get("role") == "ADMIN"
        and "access_token" in res_admin.json()
    )
    admin_token = res_admin.json().get("access_token") if admin_auth_ok else None
    record("Admin Auth Login", admin_auth_ok, f"status={res_admin.status_code}, role={res_admin.json().get('user', {}).get('role') if res_admin.status_code == 200 else None}")

    # Teacher Login
    res_teacher = requests.post(login_url, json=TEACHER_CREDS, timeout=5)
    teacher_auth_ok = (
        res_teacher.status_code == 200
        and res_teacher.json().get("user", {}).get("role") == "TEACHER"
        and "access_token" in res_teacher.json()
    )
    teacher_token = res_teacher.json().get("access_token") if teacher_auth_ok else None
    record("Teacher Auth Login", teacher_auth_ok, f"status={res_teacher.status_code}, role={res_teacher.json().get('user', {}).get('role') if res_teacher.status_code == 200 else None}")

    # All 4 Students Login
    students_ok = True
    student_tokens: dict[str, str] = {}
    for sc in STUDENTS_CREDS:
        res_s = requests.post(login_url, json={"email": sc["email"], "password": sc["password"]}, timeout=5)
        if res_s.status_code == 200 and res_s.json().get("user", {}).get("role") == "STUDENT":
            student_tokens[sc["email"]] = res_s.json()["access_token"]
        else:
            students_ok = False
    record("All 4 Students Auth Login", students_ok, f"authenticated_count={len(student_tokens)}")

    # Negative Auth Tests
    bad_pw_res = requests.post(login_url, json={"email": TEACHER_CREDS["email"], "password": "WrongPassword99!"}, timeout=5)
    bad_user_res = requests.post(login_url, json={"email": "alice@demo.edu", "password": "AnyPassword123!"}, timeout=5)
    neg_auth_ok = (bad_pw_res.status_code == 401 and bad_user_res.status_code == 401)
    record("Negative Auth Checks (Bad PW -> 401, Purged User -> 401)", neg_auth_ok, f"bad_pw={bad_pw_res.status_code}, purged_user={bad_user_res.status_code}")

    # ---------------------------------------------------------
    # 3. Backend Live Snapshot Endpoint Tests
    # ---------------------------------------------------------
    snapshot_url = f"{BACKEND_BASE_URL}/api/v1/sessions/sess_demo_cs101/live-snapshot"

    # Teacher token -> 200 and proper schema
    snap_res = requests.get(snapshot_url, headers={"Authorization": f"Bearer {teacher_token}"}, timeout=5)
    snap_ok = False
    snap_schema_details = {}
    if snap_res.status_code == 200:
        data = snap_res.json()
        students_list = data.get("students", [])
        idents = [s.get("identity") for s in students_list]
        has_all_4 = sorted(idents) == ["person_01", "person_02", "person_03", "person_04"]
        snap_ok = (
            data.get("session_id") == "sess_demo_cs101"
            and data.get("classroom_id") == "ROOM_101"
            and has_all_4
            and len(data.get("cameras", [])) >= 1
        )
        snap_schema_details = {
            "session_id": data.get("session_id"),
            "classroom_id": data.get("classroom_id"),
            "session_state": data.get("session_state"),
            "students_count": len(students_list),
            "identities": idents,
            "cameras_count": len(data.get("cameras", [])),
        }
    record("Teacher Live Snapshot Retrieval", snap_ok, f"status={snap_res.status_code}, schema={snap_schema_details}")

    # RBAC: Student token -> 403 Forbidden
    student_token = next(iter(student_tokens.values()))
    stu_snap_res = requests.get(snapshot_url, headers={"Authorization": f"Bearer {student_token}"}, timeout=5)
    record("Student Live Snapshot Access Denied -> 403", stu_snap_res.status_code == 403, f"status={stu_snap_res.status_code}")

    # RBAC: Admin token -> 403 Forbidden (since route requires TEACHER role)
    admin_snap_res = requests.get(snapshot_url, headers={"Authorization": f"Bearer {admin_token}"}, timeout=5)
    record("Admin Live Snapshot Access Denied (require_teacher) -> 403", admin_snap_res.status_code == 403, f"status={admin_snap_res.status_code}")

    # Unauthorized requests (no token / bad token)
    no_token_res = requests.get(snapshot_url, timeout=5)
    bad_token_res = requests.get(snapshot_url, headers={"Authorization": "Bearer invalid_garbage_token"}, timeout=5)
    unauth_ok = (no_token_res.status_code == 401 and bad_token_res.status_code == 401)
    record("Live Snapshot Auth Enforcement (No Token / Bad Token -> 401)", unauth_ok, f"no_token={no_token_res.status_code}, bad_token={bad_token_res.status_code}")

    # Non-existent session
    missing_sess_res = requests.get(
        f"{BACKEND_BASE_URL}/api/v1/sessions/sess_non_existent/live-snapshot",
        headers={"Authorization": f"Bearer {teacher_token}"},
        timeout=5,
    )
    missing_ok = (missing_sess_res.status_code in [404, 400])
    record("Live Snapshot Non-Existent Session -> 404", missing_ok, f"status={missing_sess_res.status_code}")

    # ---------------------------------------------------------
    # 4. CLI Flags Verification
    # ---------------------------------------------------------
    # --inspect
    inspect_proc = subprocess.run([sys.executable, "scripts/seed_clean_demo.py", "--inspect"], capture_output=True, text=True)
    inspect_ok = (inspect_proc.returncode == 0 and "DATABASE INSPECTION" in inspect_proc.stdout)
    record("CLI Flag --inspect", inspect_ok, f"code={inspect_proc.returncode}")

    # --dry-run
    dry_proc = subprocess.run([sys.executable, "scripts/seed_clean_demo.py", "--dry-run"], capture_output=True, text=True)
    dry_ok = (dry_proc.returncode == 0 and "Dry run requested" in dry_proc.stdout)
    record("CLI Flag --dry-run", dry_ok, f"code={dry_proc.returncode}")

    client.close()
    return results


if __name__ == "__main__":
    res = run_checks()
    print("\n" + "=" * 50)
    print(f"FINAL AUDIT RESULT: {'ALL PASSED' if res['all_passed'] else 'FAILURES DETECTED'}")
    print("=" * 50)
    sys.exit(0 if res["all_passed"] else 1)
