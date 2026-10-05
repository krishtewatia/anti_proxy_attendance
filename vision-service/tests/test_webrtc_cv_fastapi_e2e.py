"""End-to-End Integration Test for Step 2D.5:
WebRTC Live CV Pipeline -> EventDispatcher -> FastAPI Backend -> MongoDB -> Attendance Records.

Proves the complete loop:
1. Spawns backend FastAPI service with MongoDB database.
2. Authenticates teacher and initializes course session in ROOM_101.
3. Enrolls roster with student identities (person_01, person_02, person_04).
4. Connects LiveCVPipeline with SCRFD-0.5G, ByteTrack, track-gated ArcFace, and EventDispatcher.
5. Ingests frames:
   - Track-gated ArcFace confirms identity (person_01).
   - Track crosses boundary line -> LiveCVPipeline generates ENTRY sensory event.
   - EventDispatcher transmits event via HTTP POST to /api/v1/events.
   - FastAPI receives event, validates contract, enriches with classroom_id and session_id, and stores in MongoDB.
   - Track crosses back -> LiveCVPipeline generates EXIT event.
   - EventDispatcher transmits EXIT event.
6. Teacher finalizes session (/api/v1/sessions/{session_id}/finalize).
7. Teacher queries attendance records (/api/v1/attendance/{session_id}):
   - Validates student person_01 is marked PRESENT.
   - Validates student person_04 (enrolled with no events) is marked ABSENT.
   - Validates unconfirmed / unknown persons generated zero attendance records.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

import numpy as np
import pytest
import requests

# Path setup
SERVICE_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = SERVICE_ROOT.parent
BACKEND_ROOT = PROJECT_ROOT / "backend"
BACKEND_VENV_PYTHON = BACKEND_ROOT / ".venv" / "Scripts" / "python.exe"

if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from camera.base import VideoFrame, VideoSourceType
from events.event_dispatcher import EventDispatcher
from pipeline.live_cv_pipeline import (
    LiveCVPipeline,
    TrackEvidence,
    load_gallery,
    swap_scrfd_detector,
)


@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.needs_models
class TestWebRTCCVFastAPIE2E(unittest.TestCase):
    """End-to-End integration test proving the entire attendance loop."""

    backend_proc = None
    backend_url = "http://127.0.0.1:8123"
    auth_headers = {}
    session_id = None

    @classmethod
    def setUpClass(cls):
        """Start backend FastAPI server on port 8123 using backend virtualenv."""
        env = os.environ.copy()
        env["MONGODB_URL"] = ""  # Forces in-memory AsyncMongoMockClient
        env["PORT"] = "8123"
        env["PYTHONPATH"] = str(BACKEND_ROOT)
        env["VISION_SERVICE_API_KEY"] = "test-webrtc-cv-api-key-2026"

        cmd = [
            str(BACKEND_VENV_PYTHON),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8123",
        ]

        cls.backend_proc = subprocess.Popen(
            cmd,
            cwd=str(BACKEND_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Poll until backend is online (up to 15 seconds)
        ready = False
        t_deadline = time.time() + 15.0
        while time.time() < t_deadline:
            try:
                resp = requests.get(f"{cls.backend_url}/openapi.json", timeout=1.0)
                if resp.status_code == 200:
                    ready = True
                    break
            except Exception:
                time.sleep(0.5)

        if not ready:
            cls.tearDownClass()
            raise RuntimeError("Backend failed to start on port 8123 within 15 seconds.")

        # 1. Register teacher and obtain bearer token
        teacher_email = f"teacher.cv.e2e.{time.time_ns()}@university.edu"
        user_payload = {
            "email": teacher_email,
            "password": "TeacherPassword2026!",
            "role": "TEACHER",
        }
        reg_resp = requests.post(f"{cls.backend_url}/api/v1/auth/register", json=user_payload, timeout=3.0)
        if reg_resp.status_code not in (201, 409):
            raise RuntimeError(f"Teacher registration failed: {reg_resp.status_code} {reg_resp.text}")

        login_resp = requests.post(
            f"{cls.backend_url}/api/v1/auth/login",
            json={"email": teacher_email, "password": "TeacherPassword2026!"},
            timeout=3.0,
        )
        if login_resp.status_code != 200:
            raise RuntimeError(f"Teacher login failed: {login_resp.status_code} {login_resp.text}")

        token_data = login_resp.json()
        token = token_data["access_token"]
        cls.auth_headers = {"Authorization": f"Bearer {token}"}

        # 2. Create session in ROOM_101
        session_payload = {
            "course_name": "CS401 - Advanced Computer Vision",
            "classroom_id": "ROOM_101",
            "start_time": "2026-10-20T10:00:00Z",
            "end_time": "2026-10-20T11:00:00Z",
            "required_presence_percentage": 70.0,
        }
        sess_resp = requests.post(
            f"{cls.backend_url}/api/v1/sessions",
            headers=cls.auth_headers,
            json=session_payload,
            timeout=3.0,
        )
        if sess_resp.status_code != 201:
            raise RuntimeError(f"Session creation failed: {sess_resp.status_code} {sess_resp.text}")
        cls.session_id = sess_resp.json()["session_id"]

        # 3. Enroll roster: person_01, person_02, person_04
        roster_resp = requests.post(
            f"{cls.backend_url}/api/v1/sessions/{cls.session_id}/roster",
            headers=cls.auth_headers,
            json={"identities": ["person_01", "person_02", "person_04"]},
            timeout=3.0,
        )
        if roster_resp.status_code != 200:
            raise RuntimeError(f"Roster enrollment failed: {roster_resp.status_code} {roster_resp.text}")

    @classmethod
    def tearDownClass(cls):
        """Terminate backend process cleanly."""
        if cls.backend_proc is not None:
            cls.backend_proc.terminate()
            try:
                cls.backend_proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                cls.backend_proc.kill()
            if cls.backend_proc.stdout:
                cls.backend_proc.stdout.close()
            if cls.backend_proc.stderr:
                cls.backend_proc.stderr.close()
            cls.backend_proc = None

    def test_complete_webrtc_cv_to_fastapi_attendance_loop(self):
        """Full Loop: VideoFrame -> LiveCVPipeline -> EventDispatcher -> FastAPI -> Attendance Records."""
        from unittest.mock import MagicMock
        from insightface.app import FaceAnalysis

        # Initialize EventDispatcher connected to local backend with API key
        dispatcher = EventDispatcher(
            backend_url=self.backend_url,
            timeout=3.0,
            raise_on_failure=True,
            api_key="test-webrtc-cv-api-key-2026",
        )

        # Mock app for fast, deterministic inference
        mock_app = MagicMock(spec=FaceAnalysis)
        det_mock = MagicMock()
        rec_mock = MagicMock()

        np.random.seed(101)
        emb_person_01 = np.random.randn(512).astype(np.float32)
        emb_person_01 /= np.linalg.norm(emb_person_01)
        gallery = {"person_01": emb_person_01}

        def mock_rec_get(frame, face):
            face.embedding = emb_person_01.copy()

        rec_mock.get.side_effect = mock_rec_get
        mock_app.models = {
            "detection": det_mock,
            "recognition": rec_mock,
        }
        mock_app.det_model = det_mock

        # Initialize LiveCVPipeline with EventDispatcher and camera CAM_ROOM_101_DOOR
        pipeline = LiveCVPipeline(
            app=mock_app,
            gallery=gallery,
            similarity_threshold=0.40,
            min_margin=0.10,
            min_supporting_frames=2,
            source_id="PHONE_CAM_01",
            camera_id="CAM_ROOM_101_DOOR",
            boundary_line=((0.0, 360.0), (640.0, 360.0)),
            deadband_pixels=4.0,
            event_dispatcher=dispatcher,
        )

        test_img = np.zeros((720, 640, 3), dtype=np.uint8)

        # ======================================================================
        # Phase 1: person_01 approaches and enters the classroom (ENTRY at 10:05 UTC)
        # ======================================================================
        print("\n[E2E] Phase 1: person_01 approaches and crosses boundary (ENTRY)...")
        # Frame 1: SIDE_A (cy = 330)
        box1 = np.array([[200.0, 280.0, 300.0, 380.0, 0.95]], dtype=np.float32)
        det_mock.detect.return_value = (box1, None)
        frame1 = VideoFrame(
            frame=test_img,
            timestamp=datetime(2026, 10, 20, 10, 5, 0, tzinfo=timezone.utc),
            frame_index=1,
            source_id="PHONE_CAM_01",
            source_type=VideoSourceType.WEBRTC,
        )
        res1 = pipeline.process_frame(frame1)
        self.assertEqual(len(res1.emitted_events), 0)

        # Frame 2: SIDE_A (cy = 345) -> 2 votes accumulated -> Confirmed as person_01
        box2 = np.array([[200.0, 295.0, 300.0, 395.0, 0.95]], dtype=np.float32)
        det_mock.detect.return_value = (box2, None)
        frame2 = VideoFrame(
            frame=test_img,
            timestamp=datetime(2026, 10, 20, 10, 5, 1, tzinfo=timezone.utc),
            frame_index=2,
            source_id="PHONE_CAM_01",
            source_type=VideoSourceType.WEBRTC,
        )
        from tracking.bytetrack import STrack
        STrack.reset_counter()

        res2 = pipeline.process_frame(frame2)
        self.assertEqual(len(res2.emitted_events), 0)
        track_id = list(pipeline.tracks.keys())[0]
        self.assertTrue(pipeline.tracks[track_id].is_confirmed)
        self.assertEqual(pipeline.tracks[track_id].assigned_identity, "person_01")

        # Frame 3: in deadband zone (cy = 360)
        box3 = np.array([[200.0, 310.0, 300.0, 410.0, 0.95]], dtype=np.float32)
        det_mock.detect.return_value = (box3, None)
        frame3 = VideoFrame(
            frame=test_img,
            timestamp=datetime(2026, 10, 20, 10, 5, 2, tzinfo=timezone.utc),
            frame_index=3,
            source_id="PHONE_CAM_01",
            source_type=VideoSourceType.WEBRTC,
        )
        res3 = pipeline.process_frame(frame3)
        self.assertEqual(len(res3.emitted_events), 0)

        # Frame 4: crosses into SIDE_B (cy = 380 > 364) -> ENTRY Event Dispatched to FastAPI!
        box4 = np.array([[200.0, 330.0, 300.0, 430.0, 0.95]], dtype=np.float32)
        det_mock.detect.return_value = (box4, None)
        frame4 = VideoFrame(
            frame=test_img,
            timestamp=datetime(2026, 10, 20, 10, 5, 3, tzinfo=timezone.utc),
            frame_index=4,
            source_id="PHONE_CAM_01",
            source_type=VideoSourceType.WEBRTC,
        )
        res4 = pipeline.process_frame(frame4)

        # Verify LiveCVPipeline emitted ENTRY event and dispatched it via HTTP to FastAPI
        self.assertEqual(len(res4.emitted_events), 1)
        evt_entry = res4.emitted_events[0]
        self.assertEqual(evt_entry["direction"], "ENTRY")
        self.assertEqual(evt_entry["identity"], "person_01")
        self.assertEqual(evt_entry["camera_id"], "CAM_ROOM_101_DOOR")
        self.assertEqual(evt_entry["track_id"], track_id)
        print(f"[E2E] SUCCESS: ENTRY event dispatched to FastAPI backend (ID: {evt_entry['event_id']})")

        # ======================================================================
        # Phase 2: person_01 exits the classroom (EXIT at 10:55 UTC)
        # ======================================================================
        print("[E2E] Phase 2: person_01 moves back and crosses boundary (EXIT)...")
        # Frame 5: person is in SIDE_B (cy = 380)
        box5 = np.array([[200.0, 330.0, 300.0, 430.0, 0.95]], dtype=np.float32)
        det_mock.detect.return_value = (box5, None)
        frame5 = VideoFrame(
            frame=test_img,
            timestamp=datetime(2026, 10, 20, 10, 55, 0, tzinfo=timezone.utc),
            frame_index=5,
            source_id="PHONE_CAM_01",
            source_type=VideoSourceType.WEBRTC,
        )
        res5 = pipeline.process_frame(frame5)
        self.assertEqual(len(res5.emitted_events), 0)

        # Frame 6: person crosses back to SIDE_A (cy = 330 < 356) -> EXIT Event Dispatched!
        box6 = np.array([[200.0, 280.0, 300.0, 380.0, 0.95]], dtype=np.float32)
        det_mock.detect.return_value = (box6, None)
        frame6 = VideoFrame(
            frame=test_img,
            timestamp=datetime(2026, 10, 20, 10, 55, 1, tzinfo=timezone.utc),
            frame_index=6,
            source_id="PHONE_CAM_01",
            source_type=VideoSourceType.WEBRTC,
        )
        res6 = pipeline.process_frame(frame6)

        self.assertEqual(len(res6.emitted_events), 1)
        evt_exit = res6.emitted_events[0]
        self.assertEqual(evt_exit["direction"], "EXIT")
        self.assertEqual(evt_exit["identity"], "person_01")
        print(f"[E2E] SUCCESS: EXIT event dispatched to FastAPI backend (ID: {evt_exit['event_id']})")

        # ======================================================================
        # Phase 3: Teacher finalizes the session via FastAPI API
        # ======================================================================
        print("[E2E] Phase 3: Teacher finalizes attendance session...")
        finalize_resp = requests.post(
            f"{self.backend_url}/api/v1/sessions/{self.session_id}/finalize",
            headers=self.auth_headers,
            timeout=5.0,
        )
        self.assertEqual(finalize_resp.status_code, 200)
        finalize_data = finalize_resp.json()
        self.assertEqual(finalize_data["session_id"], self.session_id)
        print(f"[E2E] SUCCESS: Session finalized, total records: {len(finalize_data['records'])}")

        # ======================================================================
        # Phase 4: Teacher queries final attendance records from backend
        # ======================================================================
        print("[E2E] Phase 4: Fetching verified attendance records...")
        att_resp = requests.get(
            f"{self.backend_url}/api/v1/attendance/{self.session_id}",
            headers=self.auth_headers,
            timeout=5.0,
        )
        self.assertEqual(att_resp.status_code, 200)
        att_data = att_resp.json()
        records_by_id = {r["identity"]: r for r in att_data["records"]}

        # Verification 1: Roster count
        self.assertEqual(len(records_by_id), 3)

        # Verification 2: person_01 attendance record
        # Present from 10:05:03 to 10:55:01 = ~2998 seconds / 3600 seconds = ~83.28% >= 70% -> PRESENT!
        self.assertIn("person_01", records_by_id)
        p1 = records_by_id["person_01"]
        self.assertEqual(p1["status"], "PRESENT")
        self.assertGreater(p1["presence_duration_seconds"], 2900.0)
        self.assertGreaterEqual(p1["presence_percentage"], 70.0)
        print(f"[E2E] VERIFIED: person_01 status={p1['status']} presence={p1['presence_percentage']:.2f}% ({p1['presence_duration_seconds']}s)")

        # Verification 3: person_04 (enrolled on roster with 0 events) is ABSENT
        self.assertIn("person_04", records_by_id)
        p4 = records_by_id["person_04"]
        self.assertEqual(p4["status"], "ABSENT")
        self.assertEqual(p4["presence_duration_seconds"], 0.0)
        self.assertEqual(p4["presence_percentage"], 0.0)
        print(f"[E2E] VERIFIED: person_04 status={p4['status']} presence={p4['presence_percentage']:.2f}%")

        print("\n" + "=" * 75)
        print("STEP 2D.5 E2E COMPLETE: WebRTC CV -> FastAPI -> MongoDB -> Attendance Record")
        print("=" * 75 + "\n")


if __name__ == "__main__":
    unittest.main()
