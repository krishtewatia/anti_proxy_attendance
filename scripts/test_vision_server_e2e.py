#!/usr/bin/env python3
"""End-to-end verification of Vision Inference Server (Browser-Owned Webcam Architecture).

Tests:
1. Server initialization with preloaded InsightFace (SCRFD + ArcFace) and biometric gallery.
2. Initial status: camera is in STANDBY awaiting browser frames (never acquires OpenCV device).
3. Frame processing with registered student (person_01):
   - SCRFD face detection
   - ArcFace embedding extraction & gallery cosine matching
   - Recognition result (Rahul Sharma, similarity > 0.50, margin > 0.15)
   - Bounding box annotation
4. Non-face frame handling (gracefully rejects with detected_faces=0).
5. State reset on session end.
"""

from __future__ import annotations

import os
import io
from pathlib import Path
import subprocess
import sys
import time
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VISION_PYTHON = PROJECT_ROOT / "vision-service" / ".venv" / "Scripts" / "python.exe"
if not VISION_PYTHON.exists():
    VISION_PYTHON = Path(sys.executable)

TEST_IMAGE_PATH = (
    Path(os.environ.get("VISION_FIXTURES_DIR") or "vision-fixtures-not-configured")
    / "recognition_benchmark"
    / "person_01"
    / "image_01.jpg"
)
PORT = 8089
BASE_URL = f"http://127.0.0.1:{PORT}"


def run_test():
    print("\n" + "=" * 70)
    print("VERIFYING BROWSER-OWNED WEBCAM VISION INFERENCE SERVER")
    print("=" * 70)

    # 1. Start server process on test port 8089
    print(f"\n[Step 1] Starting Vision Server on test port {PORT}...")
    server_script = PROJECT_ROOT / "vision-service" / "run_local_webcam.py"
    proc = subprocess.Popen(
        [str(VISION_PYTHON), str(server_script), "--port", str(PORT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(PROJECT_ROOT / "vision-service"),
    )

    try:
        # Wait for server to become responsive
        started = False
        for _ in range(25):
            time.sleep(1.0)
            try:
                r = requests.get(f"{BASE_URL}/status", timeout=1.5)
                if r.status_code == 200:
                    started = True
                    break
            except Exception:
                pass

        if not started:
            proc.terminate()
            stdout, stderr = proc.communicate(timeout=3)
            raise RuntimeError(
                f"Vision server failed to start on port {PORT}!\nSTDOUT: {stdout.decode(errors='ignore')}\nSTDERR: {stderr.decode(errors='ignore')}"
            )

        print("  [OK] Vision Server started and listening.")

        # 2. Check initial standby status
        print("\n[Step 2] Checking Initial Standby Status...")
        st = requests.get(f"{BASE_URL}/status").json()
        print(f"  - status          : {st.get('status')}")
        print(f"  - camera_active   : {st.get('camera_active')}")
        print(f"  - camera_name     : {st.get('camera_name')}")
        print(f"  - backend         : {st.get('backend')}")
        print(f"  - status_message  : {st.get('status_message')}")

        assert st["status"] == "online"
        assert st["camera_active"] is False, (
            "Camera should be inactive before browser streams frames"
        )
        assert "getUserMedia" in st["camera_name"], (
            "Camera should indicate browser getUserMedia architecture"
        )
        print(
            "  [OK] Confirmed: Vision server does NOT acquire physical camera; stands by for browser."
        )

        # 3. Post registered student frame (Rahul Sharma / person_01)
        print("\n[Step 3] Posting Registered Student Frame to /process-frame...")
        assert TEST_IMAGE_PATH.exists(), f"Missing test image: {TEST_IMAGE_PATH}"
        with open(TEST_IMAGE_PATH, "rb") as f:
            frame_bytes = f.read()

        files = {"frame": ("frame.jpg", io.BytesIO(frame_bytes), "image/jpeg")}
        resp = requests.post(f"{BASE_URL}/process-frame", files=files, timeout=5.0)
        assert resp.status_code == 200, f"/process-frame failed: {resp.text}"
        data = resp.json()
        print(f"  - detected_faces  : {data.get('detected_faces')}")
        print(f"  - recognized      : {data.get('recognized')}")
        print(f"  - identity        : {data.get('identity')}")
        print(f"  - student_name    : {data.get('student_name')}")
        print(f"  - similarity      : {data.get('similarity')}")
        print(f"  - margin          : {data.get('margin')}")
        print(f"  - box             : {data.get('box')}")

        assert data["recognized"] is True, "Student should be recognized"
        assert data["student_name"] == "Rahul Sharma", (
            f"Expected Rahul Sharma, got {data.get('student_name')}"
        )
        assert data["similarity"] >= 0.50, (
            f"Expected similarity >= 0.50, got {data.get('similarity')}"
        )
        assert data["margin"] >= 0.15, f"Expected margin >= 0.15, got {data.get('margin')}"
        assert len(data["box"]) == 4, "Expected bounding box coordinates"
        print(
            "  [OK] Confirmed: SCRFD detected face and ArcFace matched identity with high confidence."
        )

        # 4. Verify /status updated after frame
        print("\n[Step 4] Verifying Server Telemetry Updated...")
        st2 = requests.get(f"{BASE_URL}/status").json()
        print(f"  - camera_active   : {st2.get('camera_active')}")
        print(f"  - last_recognized : {st2.get('last_recognized')}")
        assert st2["camera_active"] is True
        assert st2["last_recognized"] == "Rahul Sharma"
        print("  [OK] Confirmed: Server telemetry updated from browser frame.")

        # 5. Post non-face frame
        print("\n[Step 5] Posting Non-Face Frame to /process-frame...")
        try:
            import cv2
            import numpy as np

            blank_img = np.zeros((480, 640, 3), dtype=np.uint8)
            _, blank_buf = cv2.imencode(".jpg", blank_img)
            blank_bytes = blank_buf.tobytes()
        except ImportError:
            from PIL import Image

            img = Image.new("RGB", (640, 480), color="black")
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            blank_bytes = buf.getvalue()
        files_blank = {"frame": ("blank.jpg", io.BytesIO(blank_bytes), "image/jpeg")}
        resp_blank = requests.post(f"{BASE_URL}/process-frame", files=files_blank, timeout=5.0)
        assert resp_blank.status_code == 200
        data_blank = resp_blank.json()
        print(f"  - detected_faces  : {data_blank.get('detected_faces')}")
        print(f"  - recognized      : {data_blank.get('recognized')}")
        assert data_blank["detected_faces"] == 0
        assert data_blank["recognized"] is False
        print("  [OK] Confirmed: Non-face frame safely returns recognized=False.")

        # 6. Test session reset
        print("\n[Step 6] Testing Session Reset (/reset)...")
        r_reset = requests.post(f"{BASE_URL}/reset", json={"session_id": None}, timeout=2.0)
        assert r_reset.status_code == 200
        st3 = requests.get(f"{BASE_URL}/status").json()
        assert st3.get("active_session_id") is None
        print("  [OK] Confirmed: Session state cleanly reset.")

        print("\n" + "=" * 70)
        print("ALL VISION INFERENCE SERVER TESTS PASSED SUCCESSFULLY!")
        print("=" * 70 + "\n")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    run_test()
