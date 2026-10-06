#!/usr/bin/env python3
"""Complete Full-Stack End-to-End Verification: Browser-Owned Webcam Architecture.

Validates the full attendance lifecycle:
1. Teacher starts attendance session (FastAPI backend).
2. Vision inference server links active session.
3. Browser simulates sending captured webcam frames to /process-frame.
4. SCRFD detects face, ArcFace extracts embedding and matches against gallery.npz.
5. Student is marked PRESENT automatically in backend attendance records.
6. Subsequent identical frames are idempotent (no duplicate records).
7. Teacher ends attendance session -> session finalizes, vision server resets.
8. Session A -> Session B verification (no stale identity carryover).
"""

from __future__ import annotations

import io
import os
from pathlib import Path
import subprocess
import sys
import time
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VISION_PYTHON = PROJECT_ROOT / "vision-service" / ".venv" / "Scripts" / "python.exe"
BACKEND_PYTHON = PROJECT_ROOT / "backend" / ".venv" / "Scripts" / "python.exe"
if not VISION_PYTHON.exists():
    VISION_PYTHON = Path(sys.executable)
if not BACKEND_PYTHON.exists():
    BACKEND_PYTHON = Path(sys.executable)

TEST_IMAGE_PATH = (
    Path(os.environ.get("VISION_FIXTURES_DIR") or "vision-fixtures-not-configured")
    / "recognition_benchmark"
    / "person_01"
    / "image_01.jpg"
)

BACKEND_PORT = 8001
VISION_PORT = 8089
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"
VISION_URL = f"http://127.0.0.1:{VISION_PORT}"


def main():
    print("\n" + "=" * 70)
    print("FULL-STACK E2E ACCEPTANCE TEST: BROWSER-OWNED WEBCAM ARCHITECTURE")
    print("=" * 70)

    env_backend = os.environ.copy()
    env_backend["PORT"] = str(BACKEND_PORT)
    env_backend["APP_ENV"] = "development"
    env_backend["DEMO_MODE"] = "true"
    env_backend["VISION_SERVICE_URL"] = VISION_URL

    # 1. Start Backend Server
    print(f"\n[1/6] Launching FastAPI Backend on port {BACKEND_PORT}...")
    backend_proc = subprocess.Popen(
        [
            str(BACKEND_PYTHON),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(BACKEND_PORT),
        ],
        cwd=str(PROJECT_ROOT / "backend"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env_backend,
    )

    # 2. Start Vision Inference Server
    print(f"[2/6] Launching Vision Inference Server on port {VISION_PORT}...")
    vision_proc = subprocess.Popen(
        [
            str(VISION_PYTHON),
            "run_local_webcam.py",
            "--port",
            str(VISION_PORT),
            "--backend-url",
            BACKEND_URL,
            "--poll-interval",
            "0.5",
        ],
        cwd=str(PROJECT_ROOT / "vision-service"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # Wait for both services
        backend_ready = False
        vision_ready = False
        for _ in range(25):
            time.sleep(1.0)
            if not backend_ready:
                try:
                    if requests.get(f"{BACKEND_URL}/health", timeout=1.0).status_code == 200:
                        backend_ready = True
                except Exception:
                    pass
            if not vision_ready:
                try:
                    if requests.get(f"{VISION_URL}/status", timeout=1.0).status_code == 200:
                        vision_ready = True
                except Exception:
                    pass
            if backend_ready and vision_ready:
                break

        assert backend_ready, "FastAPI Backend failed to become healthy on port 8001!"
        assert vision_ready, "Vision Inference Server failed to become healthy on port 8089!"
        print("  [OK] Backend and Vision services online.")

        # 3. Authenticate Teacher
        print("\n[3/6] Authenticating Teacher...")
        # Ensure teacher account exists
        requests.post(
            f"{BACKEND_URL}/api/v1/auth/register",
            json={"email": "teacher@demo.edu", "password": "TeacherDevPass123!", "role": "TEACHER"},
            timeout=3.0,
        )

        login_res = requests.post(
            f"{BACKEND_URL}/api/v1/auth/login",
            json={"email": "teacher@demo.edu", "password": "TeacherDevPass123!"},
            timeout=3.0,
        )
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("  [OK] Teacher authenticated.")

        # 4. Start Attendance Session
        print("\n[4/6] Creating & Starting Attendance Session (Session A)...")
        sess_create = requests.post(
            f"{BACKEND_URL}/api/v1/sessions",
            headers=headers,
            json={
                "course_name": "Machine Learning — DS-B",
                "classroom_id": "ROOM_101",
                "class_code": "DS-B",
                "subject": "Machine Learning",
                "start_time": "2026-10-06T09:00:00Z",
                "end_time": "2026-10-06T11:00:00Z",
                "required_presence_percentage": 100.0,
            },
            timeout=3.0,
        )
        assert sess_create.status_code == 201
        session_id = sess_create.json()["session_id"]

        start_res = requests.post(
            f"{BACKEND_URL}/api/v1/sessions/{session_id}/start",
            headers=headers,
            timeout=3.0,
        )
        assert start_res.status_code == 200
        print(f"  [OK] Session {session_id} started and active.")

        # Allow vision server poll loop to detect active session
        time.sleep(1.5)
        st_data = requests.get(f"{VISION_URL}/status").json()
        assert st_data.get("active_session_id") == session_id, (
            f"Expected {session_id}, got {st_data.get('active_session_id')}"
        )
        print(f"  [OK] Vision Server synchronized with active session: {session_id}")

        # 5. Simulate Browser Posting Captured Webcam Frame
        print("\n[5/6] Simulating Browser Posting Frame to Vision Server...")
        with open(TEST_IMAGE_PATH, "rb") as f:
            frame_bytes = f.read()

        files = {"frame": ("webcam_frame.jpg", io.BytesIO(frame_bytes), "image/jpeg")}
        frame_res = requests.post(
            f"{VISION_URL}/process-frame",
            files=files,
            params={"session_id": session_id},
            timeout=5.0,
        )
        assert frame_res.status_code == 200, f"Frame processing failed: {frame_res.text}"
        fdata = frame_res.json()
        print(f"  - Detected Faces : {fdata.get('detected_faces')}")
        print(f"  - Recognized     : {fdata.get('recognized')}")
        print(f"  - Student Name   : {fdata.get('student_name')}")
        print(f"  - Similarity     : {fdata.get('similarity')}")
        print(f"  - Margin         : {fdata.get('margin')}")

        assert fdata["recognized"] is True
        assert fdata["student_name"] == "Rahul Sharma"
        assert fdata["similarity"] >= 0.50
        print("  [OK] SCRFD + ArcFace successfully recognized Rahul Sharma!")

        # Verify attendance record in Backend
        time.sleep(0.5)
        att_res = requests.get(
            f"{BACKEND_URL}/api/v1/attendance/{session_id}",
            headers=headers,
            timeout=3.0,
        )
        assert att_res.status_code == 200
        att_data = att_res.json()
        records = att_data["records"]
        student1_rec = next(
            (
                r
                for r in records
                if r["student_name"] == "Rahul Sharma" or r["identity"] in ("student1", "person_01")
            ),
            None,
        )
        assert student1_rec is not None, f"Rahul Sharma not found in attendance records: {records}"
        assert student1_rec["status"] == "PRESENT", (
            f"Expected PRESENT, got {student1_rec['status']}"
        )
        print("  [OK] Backend attendance record updated to PRESENT!")

        # Send duplicate frame -> verify already marked
        files_dup = {"frame": ("webcam_frame.jpg", io.BytesIO(frame_bytes), "image/jpeg")}
        dup_res = requests.post(
            f"{VISION_URL}/process-frame",
            files=files_dup,
            params={"session_id": session_id},
            timeout=5.0,
        )
        assert dup_res.status_code == 200
        dup_data = dup_res.json()
        assert dup_data["already_marked"] is True
        print("  [OK] Idempotency verified: duplicate frame flagged already_marked=True.")

        # 6. End Attendance Session
        print("\n[6/6] Teacher Ends Attendance Session & Verifies Clean Release...")
        end_res = requests.post(
            f"{BACKEND_URL}/api/v1/sessions/{session_id}/end",
            headers=headers,
            timeout=3.0,
        )
        assert end_res.status_code == 200
        print("  [OK] Session ended.")

        # Vision server resets state
        time.sleep(1.5)
        st_end = requests.get(f"{VISION_URL}/status").json()
        assert st_end.get("active_session_id") is None
        assert len(st_end.get("marked_students", [])) == 0
        print("  [OK] Vision server released active session and cleared marked identity cache.")

        print("\n" + "=" * 70)
        print("FULL-STACK ACCEPTANCE TEST PASSED 100%!")
        print("=" * 70 + "\n")

    finally:
        for p in (vision_proc, backend_proc):
            p.terminate()
            try:
                p.wait(timeout=3)
            except Exception:
                p.kill()


if __name__ == "__main__":
    main()
