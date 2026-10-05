import requests
from pymongo import MongoClient

def main():
    # 1. MongoDB check
    client = MongoClient("mongodb://antiproxy_user:secure_app_mongo_dev_password_12345@localhost:27017/anti_proxy_attendance?authSource=anti_proxy_attendance")
    db = client.anti_proxy_attendance
    expected = {
        "users": 6,
        "student_profiles": 4,
        "biometric_profiles": 4,
        "cameras": 1,
        "sessions": 1,
        "session_rosters": 1,
    }
    print("=== Checking MongoDB Counts ===")
    for col, exp in expected.items():
        actual = db[col].count_documents({})
        assert actual == exp, f"{col}: expected {exp}, got {actual}"
        print(f"[OK] {col}: {actual}")

    # Check biometrics details
    bios = list(db.biometric_profiles.find({}))
    for b in bios:
        ident = b["identity"]
        assert len(b["mean_embedding"]) == 512, f"{ident}: len != 512"
        norm = sum(x * x for x in b["mean_embedding"]) ** 0.5
        assert abs(norm - 1.0) < 1e-4, f"{ident}: norm != 1.0 ({norm})"
        assert b["status"] == "ENROLLED", f"{ident}: status != ENROLLED"
        print(f"[OK] Biometric {ident}: 512-d, norm={norm:.6f}, status={b['status']}")

    # 2. HTTP Login check
    print("\n=== Checking Backend Auth ===")
    r_admin = requests.post("http://localhost:8000/api/v1/auth/login", json={"email": "admin@system.local", "password": "AdminDevPass123!"})
    assert r_admin.status_code == 200, f"Admin login failed: {r_admin.text}"
    admin_data = r_admin.json()
    assert admin_data["user"]["role"] == "ADMIN"
    admin_token = admin_data["access_token"]
    print(f"[OK] Admin login successful: {admin_data['user']['email']} ({admin_data['user']['role']})")

    r_teacher = requests.post("http://localhost:8000/api/v1/auth/login", json={"email": "teacher@demo.edu", "password": "TeacherDevPass123!"})
    assert r_teacher.status_code == 200, f"Teacher login failed: {r_teacher.text}"
    teacher_data = r_teacher.json()
    assert teacher_data["user"]["role"] == "TEACHER"
    teacher_token = teacher_data["access_token"]
    print(f"[OK] Teacher login successful: {teacher_data['user']['email']} ({teacher_data['user']['role']})")

    for i in range(1, 5):
        email = f"student{i}@demo.edu"
        r_stu = requests.post("http://localhost:8000/api/v1/auth/login", json={"email": email, "password": "StudentDevPass123!"})
        assert r_stu.status_code == 200, f"Student {i} login failed: {r_stu.text}"
        stu_data = r_stu.json()
        assert stu_data["user"]["role"] == "STUDENT"
        print(f"[OK] Student login successful: {email}")

    # 3. Live session snapshot check with teacher token
    print("\n=== Checking Live Session Snapshot ===")
    r_snap = requests.get("http://localhost:8000/api/v1/sessions/sess_demo_cs101/live-snapshot", headers={"Authorization": f"Bearer {teacher_token}"})
    assert r_snap.status_code == 200, f"Live snapshot failed: {r_snap.status_code} - {r_snap.text}"
    snap_data = r_snap.json()
    print(f"[OK] Live snapshot returned: session_id={snap_data.get('session_id')}, state={snap_data.get('session_state')}, roster count={len(snap_data.get('students', []))}")

    # 4. Students directory check
    print("\n=== Checking Students Directory ===")
    r_dir = requests.get("http://localhost:8000/api/v1/students/directory", headers={"Authorization": f"Bearer {teacher_token}"})
    assert r_dir.status_code == 200, f"Students directory failed: {r_dir.text}"
    dir_data = r_dir.json()
    print(f"[OK] Students directory count={len(dir_data)}, identities={[d['identity'] for d in dir_data]}")

    # 5. Enrollment Gallery check (Admin)
    print("\n=== Checking Biometric Gallery Endpoint ===")
    r_gal = requests.get("http://localhost:8000/api/v1/enrollment/gallery", headers={"Authorization": f"Bearer {admin_token}"})
    assert r_gal.status_code == 200, f"Gallery sync failed: {r_gal.text}"
    gal_data = r_gal.json()
    print(f"[OK] Biometric Gallery returned {gal_data.get('count')} templates: {list(gal_data.get('gallery', {}).keys())}")

    print("\n>>> ALL VERIFICATION CHECKS PASSED SUCCESSFULLY! <<<")

if __name__ == "__main__":
    main()
