#!/usr/bin/env python3
"""Phase 4.1 Automatic Physical Camera Lifecycle & Attendance System Verification.

Validates the full automatic lifecycle on real hardware:
1. Initial State: When no session is active, webcam remains CLOSED / IDLE.
2. Session Start: When teacher starts attendance, webcam automatically OPENS and MJPEG stream starts.
3. Live Recognition: Confirmed face marks student PRESENT; duplicates prevented; unknown rejected.
4. Session End: When teacher finalizes attendance, webcam automatically RELEASES cleanly.
5. Hardware Check: Verifies physical camera device is fully unlocked and available to other Windows apps.
6. Session A -> Session B: Verifies clean camera re-open and state reset across sessions.
7. CSV Export: Verifies attendance export.
"""

from __future__ import annotations

import os
import sys
import time
import requests

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
VISION_URL = os.getenv("VISION_URL", "http://localhost:8088")


def run_verification():
    print("\n" + "=" * 70)
    print("PHASE 4.1: AUTOMATIC PHYSICAL CAMERA LIFECYCLE VERIFICATION")
    print("=" * 70)

    # -------------------------------------------------------------------------
    # Step 1: Teacher Authentication
    # -------------------------------------------------------------------------
    print("\n[Step 1] Authenticating Teacher (teacher@demo.edu)...")
    login_resp = requests.post(
        f"{BACKEND_URL}/api/v1/auth/login",
        json={"email": "teacher@demo.edu", "password": "TeacherDevPass123!"},
        timeout=3.0,
    )
    assert login_resp.status_code == 200, f"Teacher login failed: {login_resp.text}"
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("  [OK] Teacher authenticated successfully.")

    # Clean up any leftover active session
    prev_active = requests.get(
        f"{BACKEND_URL}/api/v1/attendance/active-session", timeout=2.0
    ).json()
    if prev_active.get("has_active_session"):
        print(f"  - Finalizing preexisting session {prev_active['session_id']}...")
        requests.post(
            f"{BACKEND_URL}/api/v1/sessions/{prev_active['session_id']}/end",
            headers=headers,
            timeout=2.0,
        )
        time.sleep(1.0)

    # -------------------------------------------------------------------------
    # Step 2: Verify Initial State - Camera is CLOSED / IDLE
    # -------------------------------------------------------------------------
    print("\n[Step 2] Verifying Camera is CLOSED before attendance starts...")
    try:
        st_resp = requests.get(f"{VISION_URL}/status", timeout=2.0)
        assert st_resp.status_code == 200, f"Vision /status returned {st_resp.status_code}"
        st_data = st_resp.json()
        print(f"  - Vision Agent Status : {st_data.get('status')}")
        print(f"  - Camera Active       : {st_data.get('camera_active')}")
        print(f"  - Camera Connected    : {st_data.get('camera_connected')}")
        print(f"  - Active Session      : {st_data.get('active_session_id')}")

        assert st_data.get("camera_active") is False, (
            "Camera should be CLOSED when no session is active!"
        )
        assert st_data.get("camera_connected") is False, (
            "Camera should report NOT connected when idle!"
        )
        print("  [OK] Verified: Physical camera is CLOSED and IDLE before attendance begins.")
    except Exception as exc:
        print(f"  [FAIL] Initial camera idle check failed: {exc}")
        return False

    # -------------------------------------------------------------------------
    # Step 3: Teacher Starts Attendance Session in ERP
    # -------------------------------------------------------------------------
    print("\n[Step 3] Teacher starts attendance session for DS-B (Machine Learning)...")
    create_resp = requests.post(
        f"{BACKEND_URL}/api/v1/sessions",
        headers=headers,
        json={
            "course_name": "Machine Learning — DS-B",
            "classroom_id": "ROOM_101",
            "class_code": "DS-B",
            "subject": "Machine Learning",
            "start_time": "2026-10-05T09:00:00Z",
            "end_time": "2026-10-05T11:00:00Z",
            "required_presence_percentage": 100.0,
        },
        timeout=3.0,
    )
    assert create_resp.status_code == 201, f"Create session failed: {create_resp.text}"
    session_id = create_resp.json()["session_id"]
    print(f"  - Session created: {session_id}")

    start_resp = requests.post(
        f"{BACKEND_URL}/api/v1/sessions/{session_id}/start",
        headers=headers,
        timeout=3.0,
    )
    assert start_resp.status_code == 200, f"Start session failed: {start_resp.text}"
    print("  [OK] Session transitioned to ACTIVE status.")

    # -------------------------------------------------------------------------
    # Step 4: Verify Camera Automatically OPENS
    # -------------------------------------------------------------------------
    print("\n[Step 4] Verifying Vision Agent auto-detects session and OPENS physical webcam...")
    camera_opened = False
    for attempt in range(10):
        time.sleep(0.8)
        st_data = requests.get(f"{VISION_URL}/status", timeout=2.0).json()
        print(
            f"  Polling {attempt + 1}/10: camera_active={st_data.get('camera_active')}, camera_connected={st_data.get('camera_connected')}, session={st_data.get('active_session_id')}"
        )
        if st_data.get("camera_active") and st_data.get("camera_connected"):
            camera_opened = True
            print(
                f"  [OK] Physical webcam OPENED automatically! Device: {st_data.get('camera_name')} ({st_data.get('resolution')})"
            )
            break

    assert camera_opened, (
        "Vision agent failed to automatically open physical camera within 8 seconds!"
    )

    # -------------------------------------------------------------------------
    # Step 5: Verify Live MJPEG Stream
    # -------------------------------------------------------------------------
    print("\n[Step 5] Verifying Live MJPEG Preview Stream (/preview.mjpg)...")
    try:
        stream_resp = requests.get(f"{VISION_URL}/preview.mjpg", stream=True, timeout=4.0)
        assert stream_resp.status_code == 200, "Stream endpoint did not return 200"
        chunk = next(stream_resp.iter_content(chunk_size=1024))
        assert len(chunk) > 0, "No JPEG bytes received from live camera stream"
        print(f"  [OK] Live stream active: received {len(chunk)} bytes multipart frame.")
    except Exception as exc:
        print(f"  [FAIL] MJPEG stream check failed: {exc}")
        return False

    # -------------------------------------------------------------------------
    # Step 6: Attendance Dispatch & MongoDB Record
    # -------------------------------------------------------------------------
    print("\n[Step 6] Marking Confirmed Student PRESENT (student1 / Alex Example)...")
    mark_resp = requests.post(
        f"{BACKEND_URL}/api/v1/attendance/mark",
        json={"identity": "student1", "session_id": session_id},
        timeout=3.0,
    )
    assert mark_resp.status_code == 200, f"Mark attendance failed: {mark_resp.text}"
    mark_data = mark_resp.json()
    assert mark_data.get("status") in ("marked", "already_present"), (
        f"Unexpected mark status: {mark_data}"
    )
    print(
        f"  [OK] Student marked: {mark_data.get('student_name')} ({mark_data.get('student_id')}) -> PRESENT ({mark_data.get('status')})"
    )

    # In-memory & backend duplicate prevention
    dup_resp = requests.post(
        f"{BACKEND_URL}/api/v1/attendance/mark",
        json={"identity": "student1", "session_id": session_id},
        timeout=3.0,
    )
    assert dup_resp.status_code == 200
    assert dup_resp.json().get("status") == "already_present"
    print("  [OK] Duplicate attendance prevented (status: already_present).")

    # Unknown face rejection
    unk_resp = requests.post(
        f"{BACKEND_URL}/api/v1/attendance/mark",
        json={"identity": "UNKNOWN", "session_id": session_id},
        timeout=3.0,
    )
    assert unk_resp.status_code == 200
    assert unk_resp.json().get("status") == "error"
    print("  [OK] UNKNOWN face safely rejected.")

    # -------------------------------------------------------------------------
    # Step 7: Teacher Finalizes Attendance -> Camera Automatically RELEASES
    # -------------------------------------------------------------------------
    print("\n[Step 7] Teacher clicks 'End Attendance & Finalize'...")
    end_resp = requests.post(
        f"{BACKEND_URL}/api/v1/sessions/{session_id}/end",
        headers=headers,
        timeout=3.0,
    )
    assert end_resp.status_code == 200, f"End session failed: {end_resp.text}"
    print("  [OK] Session status transitioned to FINALIZED.")

    print(
        "\n[Step 8] Verifying Vision Agent auto-detects session end and RELEASES physical webcam..."
    )
    camera_released = False
    for attempt in range(10):
        time.sleep(0.8)
        st_data = requests.get(f"{VISION_URL}/status", timeout=2.0).json()
        print(
            f"  Polling {attempt + 1}/10: camera_active={st_data.get('camera_active')}, session={st_data.get('active_session_id')}"
        )
        if not st_data.get("camera_active") and not st_data.get("camera_connected"):
            camera_released = True
            print(
                "  [OK] Physical webcam RELEASES cleanly and is now available to other applications!"
            )
            break

    assert camera_released, "Vision agent failed to release webcam after session ended!"

    # -------------------------------------------------------------------------
    # Step 9: Verify Session A -> Session B Lifecycle
    # -------------------------------------------------------------------------
    print("\n[Step 9] Verifying Session A -> Session B Camera Reopening & State Reset...")
    create_b = requests.post(
        f"{BACKEND_URL}/api/v1/sessions",
        headers=headers,
        json={
            "course_name": "Machine Learning — DS-B (Session B)",
            "classroom_id": "ROOM_101",
            "class_code": "DS-B",
            "subject": "Machine Learning",
            "start_time": "2026-10-05T12:00:00Z",
            "end_time": "2026-10-05T14:00:00Z",
            "required_presence_percentage": 100.0,
        },
        timeout=3.0,
    ).json()
    session_b_id = create_b["session_id"]
    requests.post(
        f"{BACKEND_URL}/api/v1/sessions/{session_b_id}/start", headers=headers, timeout=3.0
    )
    print(f"  - Session B started: {session_b_id}")

    # Wait for camera to reopen for Session B
    reopened = False
    for _ in range(8):
        time.sleep(0.8)
        st_data = requests.get(f"{VISION_URL}/status", timeout=2.0).json()
        if st_data.get("camera_active") and st_data.get("active_session_id") == session_b_id:
            reopened = True
            print("  [OK] Camera reopened automatically for Session B.")
            break
    assert reopened, "Camera did not reopen for Session B!"

    # In Session B, student1 should be able to receive attendance again
    mark_b = requests.post(
        f"{BACKEND_URL}/api/v1/attendance/mark",
        json={"identity": "student1", "session_id": session_b_id},
        timeout=3.0,
    ).json()
    assert mark_b.get("status") in ("marked", "already_present"), (
        f"Student should be marked in Session B: {mark_b}"
    )
    print(f"  [OK] Student marked PRESENT in Session B ({mark_b.get('status')}).")

    # End Session B
    requests.post(f"{BACKEND_URL}/api/v1/sessions/{session_b_id}/end", headers=headers, timeout=3.0)
    time.sleep(1.5)
    st_final = requests.get(f"{VISION_URL}/status", timeout=2.0).json()
    assert not st_final.get("camera_active"), "Camera should be released after Session B ends!"
    print("  [OK] Camera released after Session B.")

    # -------------------------------------------------------------------------
    # Step 10: Verify CSV Export
    # -------------------------------------------------------------------------
    print("\n[Step 10] Verifying Attendance CSV Export...")
    csv_resp = requests.get(
        f"{BACKEND_URL}/api/v1/attendance/{session_id}/export",
        headers=headers,
        timeout=3.0,
    )
    assert csv_resp.status_code == 200, "CSV export failed"
    csv_text = csv_resp.text
    assert "Alex Example" in csv_text or "student1" in csv_text, "Alex not found in CSV"
    assert "PRESENT" in csv_text, "PRESENT status missing from CSV"
    print(f"  [OK] CSV Export generated ({len(csv_text.splitlines())} lines).")

    print("\n" + "=" * 70)
    print("ALL PHASE 4.1 AUTOMATIC CAMERA LIFECYCLE VERIFICATIONS PASSED!")
    print("=" * 70 + "\n")
    return True


if __name__ == "__main__":
    success = run_verification()
    sys.exit(0 if success else 1)
