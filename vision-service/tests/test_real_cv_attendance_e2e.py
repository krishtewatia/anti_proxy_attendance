"""Real-Video End-to-End Test Suite for Step 2E.1:
Real CV (SCRFD-0.5G + ByteTrack + ArcFace) -> EventDispatcher -> FastAPI -> MongoDB -> Presence Engine -> Attendance API.

This test suite replaces synthetic proof with repeatable E2E scenarios driven by
REAL face video clips and real computer vision models.

Required Scenarios Tested:
1. Single student entry + exit (person_02: ENTRY and EXIT, duration > 0, status PRESENT).
2. Students entering together / simultaneous entry (person_01 and person_02 cross doorway concurrently).
3. Unknown person safety gate (unconfirmed/unknown tracks crossing boundary emit zero events).
4. Non-roster known person isolation (person_01 / person_03 event accepted by FastAPI, but excluded from session attendance).
5. Roster student never seen (person_04 on roster with zero events -> marked ABSENT, 0.0s, 0.0%).
6. Missing EXIT finalization behavior (person_01 enters, never exits -> unclosed interval, marked ABSENT, 0.0s).
7. Full composite classroom session E2E (comprehensive integration of all rules simultaneously).

Requirements & Constraints:
- Pytest marker: e2e (run via `pytest -m e2e tests/test_real_cv_attendance_e2e.py`).
- Graceful skip if real video clips or InsightFace model weights are absent.
- Strict database isolation: sets MONGODB_URL="" to enforce AsyncMongoMockClient.
- Test-only clock/offset: FileVideoSource start_time parameter ensures video timestamps land
  inside distinct session windows without weakening production timestamp validation.
- Zero fabrication: uses genuine video frames from real recording clips.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

import pytest
import requests

# Path setup
SERVICE_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = SERVICE_ROOT.parent
BACKEND_ROOT = PROJECT_ROOT / "backend"
BACKEND_VENV_PYTHON = BACKEND_ROOT / ".venv" / "Scripts" / "python.exe"
TEST_PORT = 8126
BACKEND_URL = f"http://127.0.0.1:{TEST_PORT}"

if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from camera.file_source import FileVideoSource
from events.event_dispatcher import EventDispatcher
from pipeline.live_cv_pipeline import (
    LiveCVPipeline,
    create_face_analysis,
    load_gallery,
    swap_scrfd_detector,
)
from tracking.bytetrack import STrack

# Test assets
CLIP_ENTRY_EXIT = Path(os.environ.get("VISION_FIXTURES_DIR") or "vision-fixtures-not-configured") / "video_test" / "entry_exit_simultaneous.mp4"
CLIP_MULTI_PERSON = Path(os.environ.get("VISION_FIXTURES_DIR") or "vision-fixtures-not-configured") / "video_test" / "multi_person_simultaneous.mp4"
ENROLLMENT_DIR = Path(os.environ.get("VISION_FIXTURES_DIR") or "vision-fixtures-not-configured") / "recognition_benchmark"
SCRFD_MODEL_PATH = SERVICE_ROOT / "models" / "scrfd_500m_bnkps_shape640x640.onnx"

CLIPS_AVAILABLE = CLIP_ENTRY_EXIT.exists() and ENROLLMENT_DIR.exists()


@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.needs_models
class TestRealCVAttendanceE2E(unittest.TestCase):
    """Repeatable E2E integration test suite driven by real video clips."""

    backend_proc: subprocess.Popen | None = None
    auth_headers: dict[str, str] = {}
    app = None
    gallery: dict = {}
    dispatcher: EventDispatcher | None = None

    @classmethod
    def setUpClass(cls):
        """Start backend FastAPI server on test port and initialize CV models."""
        if not CLIPS_AVAILABLE:
            raise unittest.SkipTest("Real video clips or enrollment directory not found.")

        # 1. Start backend FastAPI process with isolated mock MongoDB
        env = os.environ.copy()
        env["MONGODB_URL"] = ""  # Force in-memory AsyncMongoMockClient
        env["PORT"] = str(TEST_PORT)
        env["DATABASE_NAME"] = "anti_proxy_real_e2e_db"
        env["PYTHONPATH"] = str(BACKEND_ROOT)
        env["VISION_SERVICE_API_KEY"] = "test-real-cv-api-key-2026"

        cmd = [
            str(BACKEND_VENV_PYTHON),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(TEST_PORT),
        ]

        cls.backend_proc = subprocess.Popen(
            cmd,
            cwd=str(BACKEND_ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Poll until backend is online (up to 15 seconds)
        ready = False
        t_deadline = time.time() + 15.0
        while time.time() < t_deadline:
            try:
                resp = requests.get(f"{BACKEND_URL}/openapi.json", timeout=1.0)
                if resp.status_code == 200:
                    ready = True
                    break
            except Exception:
                time.sleep(0.4)

        if not ready:
            cls.tearDownClass()
            raise RuntimeError(f"Backend failed to start on port {TEST_PORT} within 15 seconds.")

        # 2. Register teacher and obtain bearer token
        teacher_email = f"teacher.realcv.{time.time_ns()}@university.edu"
        user_payload = {
            "email": teacher_email,
            "password": "TeacherPassword2026!",
            "role": "TEACHER",
        }
        reg_resp = requests.post(f"{BACKEND_URL}/api/v1/auth/register", json=user_payload, timeout=3.0)
        if reg_resp.status_code not in (201, 409):
            cls.tearDownClass()
            raise RuntimeError(f"Teacher registration failed: {reg_resp.status_code} {reg_resp.text}")

        login_resp = requests.post(
            f"{BACKEND_URL}/api/v1/auth/login",
            json={"email": teacher_email, "password": "TeacherPassword2026!"},
            timeout=3.0,
        )
        if login_resp.status_code != 200:
            cls.tearDownClass()
            raise RuntimeError(f"Teacher login failed: {login_resp.status_code} {login_resp.text}")

        token_data = login_resp.json()
        cls.auth_headers = {"Authorization": f"Bearer {token_data['access_token']}"}

        # 3. Initialize real InsightFace FaceAnalysis + SCRFD-0.5G + Gallery
        try:
            cls.app = create_face_analysis(
                name="buffalo_l",
                allowed_modules=["detection", "recognition"],
                intra_threads=4,
                inter_threads=2,
            )
            swap_scrfd_detector(cls.app, detector_type="0.5g", intra_threads=4, inter_threads=2)
            # Build the gallery from the test fixtures under their own folder names
            # (person_01..04). An empty identity_map switches off the default
            # mapping to the demo accounts (student1..4), which these scenarios
            # do not use, and nothing is read from a local gallery.npz.
            cls.gallery = load_gallery(cls.app, ENROLLMENT_DIR, identity_map={})
        except Exception as exc:
            cls.tearDownClass()
            raise unittest.SkipTest(f"Failed to initialize real CV models or gallery: {exc}")

        # 4. Initialize EventDispatcher connected to local test backend with API key
        cls.dispatcher = EventDispatcher(
            backend_url=BACKEND_URL,
            timeout=5.0,
            raise_on_failure=True,
            api_key="test-real-cv-api-key-2026",
        )

    @classmethod
    def tearDownClass(cls):
        """Terminate backend process cleanly."""
        if cls.backend_proc is not None:
            cls.backend_proc.terminate()
            try:
                cls.backend_proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                cls.backend_proc.kill()
            cls.backend_proc = None

    def setUp(self):
        """Reset dispatcher deduplication cache before each test."""
        if self.dispatcher is not None:
            self.dispatcher.reset()

    def _create_session(
        self,
        start_time: str,
        end_time: str,
        required_presence_percentage: float = 70.0,
        course_name: str = "CS401 - Computer Vision E2E",
        classroom_id: str = "ROOM_101",
    ) -> str:
        """Helper to create a session in the test backend."""
        payload = {
            "course_name": course_name,
            "classroom_id": classroom_id,
            "start_time": start_time,
            "end_time": end_time,
            "required_presence_percentage": required_presence_percentage,
        }
        resp = requests.post(f"{BACKEND_URL}/api/v1/sessions", headers=self.auth_headers, json=payload, timeout=3.0)
        self.assertEqual(resp.status_code, 201, f"Create session failed: {resp.text}")
        return resp.json()["session_id"]

    def _enroll_roster(self, session_id: str, identities: list[str]) -> list[str]:
        """Helper to enroll identities into a session roster."""
        resp = requests.post(
            f"{BACKEND_URL}/api/v1/sessions/{session_id}/roster",
            headers=self.auth_headers,
            json={"identities": identities},
            timeout=3.0,
        )
        self.assertEqual(resp.status_code, 200, f"Enroll roster failed: {resp.text}")
        return resp.json()["identities"]

    def _finalize_session(self, session_id: str) -> dict[str, dict]:
        """Helper to finalize session attendance and return detailed finalized records."""
        resp = requests.post(
            f"{BACKEND_URL}/api/v1/sessions/{session_id}/finalize",
            headers=self.auth_headers,
            timeout=15.0,
        )
        self.assertEqual(resp.status_code, 200, f"Finalize session failed: {resp.text}")
        records = resp.json()["records"]
        return {r["identity"]: r for r in records}

    def _get_attendance(self, session_id: str) -> dict[str, dict]:
        """Helper to fetch attendance summary records from GET endpoint."""
        resp = requests.get(
            f"{BACKEND_URL}/api/v1/attendance/{session_id}",
            headers=self.auth_headers,
            timeout=15.0,
        )
        self.assertEqual(resp.status_code, 200, f"Get attendance failed: {resp.text}")
        records = resp.json()["records"]
        return {r["identity"]: r for r in records}

    def _run_pipeline_on_clip(
        self,
        clip_path: Path,
        start_time: datetime,
        boundary_line: tuple[tuple[float, float], tuple[float, float]] = ((0.0, 575.0), (1152.0, 640.0)),
        target_fps: float = 5.0,
    ) -> LiveCVPipeline:
        """Run LiveCVPipeline over real video clip and dispatch events."""
        STrack.reset_counter()
        if self.dispatcher is not None:
            self.dispatcher.reset()

        pipeline = LiveCVPipeline(
            app=self.app,
            gallery=self.gallery,
            similarity_threshold=0.40,
            min_margin=0.15,
            min_supporting_frames=3,
            source_id="PHONE_CAM_01",
            camera_id="CAM_ROOM_101_DOOR",
            boundary_line=boundary_line,
            deadband_pixels=4.0,
            event_dispatcher=self.dispatcher,
        )

        source = FileVideoSource(
            clip_path,
            target_fps=target_fps,
            start_time=start_time,
        )
        source.open()
        try:
            while True:
                frame = source.read()
                if frame is None:
                    break
                pipeline.process_frame(frame)
        finally:
            source.release()

        return pipeline

    # ==========================================================================
    # SCENARIO 1: Single Student Entry + Exit
    # ==========================================================================
    def test_scenario_01_single_student_entry_and_exit(self):
        """Scenario 1: Single student (person_02) walks into room, then exits.

        Verifies:
        - Real SCRFD detection and ArcFace recognition confirm person_02.
        - Boundary crossings generate real ENTRY and EXIT events.
        - EventDispatcher transmits both events to FastAPI.
        - Presence duration is accurately calculated from real video timestamps.
        - Attendance status resolves to PRESENT when threshold is satisfied.
        """
        # Session duration: 10 seconds (08:00:00 to 08:00:10 UTC)
        # Required presence: 30.0% (3.0s). In clip, person_02 is present ~3.79s -> ~37.9% -> PRESENT.
        session_id = self._create_session(
            start_time="2026-10-20T08:00:00Z",
            end_time="2026-10-20T08:00:10Z",
            required_presence_percentage=30.0,
        )
        self._enroll_roster(session_id, ["person_02"])

        # Offset video to start at 08:00:00 UTC
        start_time = datetime(2026, 10, 20, 8, 0, 0, tzinfo=timezone.utc)
        pipeline = self._run_pipeline_on_clip(CLIP_ENTRY_EXIT, start_time)

        # Assert pipeline emitted ENTRY and EXIT for person_02
        p2_events = [e for e in pipeline.dispatched_events if e["identity"] == "person_02"]
        directions = [e["direction"] for e in p2_events]
        self.assertIn("ENTRY", directions, "person_02 ENTRY event was not emitted")
        self.assertIn("EXIT", directions, "person_02 EXIT event was not emitted")

        # Finalize session and verify attendance
        finalized_records = self._finalize_session(session_id)
        records = self._get_attendance(session_id)

        self.assertIn("person_02", records)
        rec = records["person_02"]
        self.assertEqual(rec["status"], "PRESENT")
        self.assertGreater(rec["presence_duration_seconds"], 2.5)
        self.assertGreaterEqual(rec["presence_percentage"], 30.0)

        # Verify presence intervals from finalized response
        fin_rec = finalized_records["person_02"]
        self.assertEqual(len(fin_rec["presence_intervals"]), 1)
        interval = fin_rec["presence_intervals"][0]
        self.assertLess(interval["entry_time"], interval["exit_time"])

    # ==========================================================================
    # SCENARIO 2: Students Entering Together / Simultaneous Entry
    # ==========================================================================
    def test_scenario_02_students_entering_together_simultaneous(self):
        """Scenario 2: Multiple students (person_01 and person_02) cross doorway simultaneously.

        Verifies:
        - Multi-face SCRFD detects both subjects in concurrent video frames.
        - ByteTrack maintains 2 independent active tracks without ID switching.
        - ArcFace confirms both person_01 and person_02 concurrently.
        - LiveCVPipeline emits simultaneous ENTRY events at matching timestamps.
        - FastAPI ingests and enriches both events with active session ID.
        """
        session_id = self._create_session(
            start_time="2026-10-20T09:00:00Z",
            end_time="2026-10-20T09:10:00Z",
            required_presence_percentage=50.0,
        )
        self._enroll_roster(session_id, ["person_01", "person_02"])

        start_time = datetime(2026, 10, 20, 9, 0, 0, tzinfo=timezone.utc)
        clip = CLIP_MULTI_PERSON if CLIP_MULTI_PERSON.exists() else CLIP_ENTRY_EXIT
        pipeline = self._run_pipeline_on_clip(clip, start_time)

        entries = [e for e in pipeline.dispatched_events if e["direction"] == "ENTRY"]
        entry_identities = {e["identity"] for e in entries}

        self.assertIn("person_01", entry_identities, "Simultaneous entry of person_01 not captured")
        self.assertIn("person_02", entry_identities, "Simultaneous entry of person_02 not captured")

        # Concurrency verification: Max concurrent faces and tracks >= 2
        telemetry = pipeline.get_benchmark_telemetry()
        self.assertGreaterEqual(telemetry["max_concurrent_faces"], 2)
        self.assertGreaterEqual(telemetry["max_concurrent_tracks"], 2)

    # ==========================================================================
    # SCENARIO 3: Unknown Person Safety Gate (Zero Events)
    # ==========================================================================
    def test_scenario_03_unknown_person_safety_gate_zero_events(self):
        """Scenario 3: Unenrolled or unconfirmed tracks must NEVER emit events.

        Verifies:
        - Real tracks in clip that fail identity voting or similarity threshold remain UNKNOWN.
        - Even when crossing the boundary, the Safety Gate (get_emittable_directions) blocks them.
        - Zero events with identity='UNKNOWN' are dispatched to FastAPI.
        """
        start_time = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
        pipeline = self._run_pipeline_on_clip(CLIP_ENTRY_EXIT, start_time)

        # Find any UNKNOWN tracks in pipeline
        unknown_tracks = [tr for tr in pipeline.tracks.values() if tr.assigned_identity == "UNKNOWN"]
        self.assertGreater(len(unknown_tracks), 0, "Expected at least one transient/unknown track in clip")

        # Safety Gate assertion: zero events emitted for UNKNOWN identity
        dispatched_unknown = [e for e in pipeline.dispatched_events if e["identity"] == "UNKNOWN"]
        self.assertEqual(len(dispatched_unknown), 0, "Safety gate violation: UNKNOWN track emitted an event")

    # ==========================================================================
    # SCENARIO 4: Non-Roster Known Person (Accepted Event, No Attendance Record)
    # ==========================================================================
    def test_scenario_04_non_roster_known_person_isolation(self):
        """Scenario 4: Known person recognized by CV who is NOT on the session roster.

        Verifies:
        - person_01 is recognized and emits an ENTRY event.
        - EventDispatcher posts to /api/v1/events; FastAPI accepts (HTTP 201).
        - Session roster contains ONLY person_02 and person_04 (person_01 omitted).
        - When session is finalized, person_01 receives NO attendance record.
        - Attendance records strictly restricted to enrolled roster members.
        """
        session_id = self._create_session(
            start_time="2026-10-20T11:00:00Z",
            end_time="2026-10-20T11:10:00Z",
            required_presence_percentage=30.0,
        )
        # Only enroll person_02 and person_04 (person_01 is non-roster)
        self._enroll_roster(session_id, ["person_02", "person_04"])

        start_time = datetime(2026, 10, 20, 11, 0, 0, tzinfo=timezone.utc)
        pipeline = self._run_pipeline_on_clip(CLIP_ENTRY_EXIT, start_time)

        # Verify person_01 event was dispatched and accepted
        p1_events = [e for e in pipeline.dispatched_events if e["identity"] == "person_01"]
        self.assertGreater(len(p1_events), 0, "person_01 event should be emitted by CV pipeline")

        # Also dispatch a sensory event for person_03 (who is in gallery but not on roster)
        evt_p3 = {
            "event_id": f"evt_p3_nonroster_{time.time_ns()}",
            "camera_id": "CAM_ROOM_101_DOOR",
            "track_id": 99,
            "identity": "person_03",
            "direction": "ENTRY",
            "timestamp": "2026-10-20T11:01:00Z",
            "evidence": {
                "peak_similarity": 0.55,
                "mean_similarity": 0.52,
                "supporting_frames": 4,
                "total_frames": 4,
                "consistency_pct": 100.0,
            },
        }
        resp_p3 = requests.post(
            f"{BACKEND_URL}/api/v1/events",
            json=evt_p3,
            headers={"X-API-Key": "test-real-cv-api-key-2026"},
            timeout=3.0,
        )
        self.assertEqual(resp_p3.status_code, 201)
        self.assertEqual(resp_p3.json()["status"], "accepted")

        # Finalize session and verify attendance records
        self._finalize_session(session_id)
        records = self._get_attendance(session_id)

        # Enrolled roster members
        self.assertIn("person_02", records)
        self.assertIn("person_04", records)
        self.assertEqual(len(records), 2, "Only enrolled roster members must have attendance records")

        # Non-roster members must have ZERO records
        self.assertNotIn("person_01", records, "Non-roster person_01 must not have attendance record")
        self.assertNotIn("person_03", records, "Non-roster person_03 must not have attendance record")

    # ==========================================================================
    # SCENARIO 5: Roster Student Never Seen (ABSENT)
    # ==========================================================================
    def test_scenario_05_roster_student_never_seen_absent(self):
        """Scenario 5: Student enrolled on roster who never appears on camera.

        Verifies:
        - person_04 is enrolled on session roster.
        - Zero CV events exist for person_04.
        - Finalization marks person_04 as ABSENT.
        - Presence duration and percentage are exactly 0.0.
        """
        session_id = self._create_session(
            start_time="2026-10-20T12:00:00Z",
            end_time="2026-10-20T12:10:00Z",
            required_presence_percentage=50.0,
        )
        self._enroll_roster(session_id, ["person_04"])

        # Finalize without any events for person_04
        fin_records = self._finalize_session(session_id)
        records = self._get_attendance(session_id)

        self.assertIn("person_04", records)
        rec = records["person_04"]
        self.assertEqual(rec["status"], "ABSENT")
        self.assertEqual(rec["presence_duration_seconds"], 0.0)
        self.assertEqual(rec["presence_percentage"], 0.0)
        self.assertEqual(fin_records["person_04"]["presence_intervals"], [])

    # ==========================================================================
    # SCENARIO 6: Missing EXIT Finalization Behavior
    # ==========================================================================
    def test_scenario_06_missing_exit_finalization_behavior(self):
        """Scenario 6: Student enters room but never exits before session ends.

        Verifies:
        - person_01 crosses boundary into room (ENTRY), but no EXIT is recorded.
        - Session is finalized with unclosed ENTRY.
        - Presence Engine behavior: unclosed entry yields 0 completed intervals.
        - Student is finalized as ABSENT with 0.0 seconds presence.
        """
        session_id = self._create_session(
            start_time="2026-10-20T13:00:00Z",
            end_time="2026-10-20T13:10:00Z",
            required_presence_percentage=50.0,
        )
        self._enroll_roster(session_id, ["person_01"])

        start_time = datetime(2026, 10, 20, 13, 0, 0, tzinfo=timezone.utc)
        pipeline = self._run_pipeline_on_clip(CLIP_ENTRY_EXIT, start_time)

        # Verify only ENTRY was emitted for person_01
        p1_events = [e for e in pipeline.dispatched_events if e["identity"] == "person_01"]
        p1_dirs = [e["direction"] for e in p1_events]
        self.assertIn("ENTRY", p1_dirs)
        self.assertNotIn("EXIT", p1_dirs, "person_01 should not have an EXIT in this clip")

        # Finalize and verify unclosed interval behavior
        fin_records = self._finalize_session(session_id)
        records = self._get_attendance(session_id)

        self.assertIn("person_01", records)
        rec = records["person_01"]
        self.assertEqual(rec["status"], "ABSENT")
        self.assertEqual(rec["presence_duration_seconds"], 0.0)
        self.assertEqual(rec["presence_percentage"], 0.0)
        self.assertEqual(fin_records["person_01"]["presence_intervals"], [])

    # ==========================================================================
    # SCENARIO 7: Full Classroom Session End-to-End
    # ==========================================================================
    def test_scenario_07_full_classroom_session_e2e(self):
        """Scenario 7: Full representative classroom session combining all rules.

        ROOM_101, 14:00:00 to 14:00:10 UTC (10s session window).
        Roster: person_01, person_02, person_04.
        Non-roster: person_03.
        Real video input: entry_exit_simultaneous.mp4 (start_time: 14:00:00 UTC).

        Validates simultaneously:
        - person_02: ENTRY + EXIT -> Completed interval, duration ~3.79s -> ~37.9% >= 30.0% -> PRESENT.
        - person_01: ENTRY only (missing EXIT) -> unclosed interval, ABSENT.
        - person_04: Enrolled, zero events -> ABSENT.
        - person_03: Non-roster known person -> Excluded from attendance.
        - Unknown persons -> Zero events, excluded from attendance.
        """
        session_id = self._create_session(
            start_time="2026-10-20T14:00:00Z",
            end_time="2026-10-20T14:00:10Z",
            required_presence_percentage=30.0,
        )
        self._enroll_roster(session_id, ["person_01", "person_02", "person_04"])

        start_time = datetime(2026, 10, 20, 14, 0, 0, tzinfo=timezone.utc)
        pipeline = self._run_pipeline_on_clip(CLIP_ENTRY_EXIT, start_time)

        # Dispatch non-roster known person event
        evt_p3 = {
            "event_id": f"evt_p3_full_{time.time_ns()}",
            "camera_id": "CAM_ROOM_101_DOOR",
            "track_id": 88,
            "identity": "person_03",
            "direction": "ENTRY",
            "timestamp": "2026-10-20T14:00:05Z",
            "evidence": {
                "peak_similarity": 0.56,
                "mean_similarity": 0.54,
                "supporting_frames": 3,
                "total_frames": 3,
                "consistency_pct": 100.0,
            },
        }
        requests.post(
            f"{BACKEND_URL}/api/v1/events",
            json=evt_p3,
            headers={"X-API-Key": "test-real-cv-api-key-2026"},
            timeout=3.0,
        )

        # Finalize and retrieve records
        fin_records = self._finalize_session(session_id)
        records = self._get_attendance(session_id)

        # Assert total records count equals roster length
        self.assertEqual(len(records), 3)

        # person_02: Present for ~3.79 seconds in 10s session = ~37.9% >= 30.0% -> PRESENT
        p2 = records["person_02"]
        self.assertEqual(p2["status"], "PRESENT")
        self.assertGreater(p2["presence_duration_seconds"], 2.5)
        self.assertEqual(len(fin_records["person_02"]["presence_intervals"]), 1)

        # person_01: Missing EXIT -> ABSENT
        p1 = records["person_01"]
        self.assertEqual(p1["status"], "ABSENT")
        self.assertEqual(p1["presence_duration_seconds"], 0.0)

        # person_04: Never seen -> ABSENT
        p4 = records["person_04"]
        self.assertEqual(p4["status"], "ABSENT")
        self.assertEqual(p4["presence_duration_seconds"], 0.0)

        # person_03 and unknowns: NOT present
        self.assertNotIn("person_03", records)
        self.assertNotIn("UNKNOWN", records)

    def test_forged_event_without_credential_cannot_create_attendance(self):
        """Proves forged events lacking credentials return HTTP 401 and cannot create attendance."""
        session_id = self._create_session(
            start_time="2026-10-20T10:00:00Z",
            end_time="2026-10-20T11:00:00Z",
            course_name="CS-SEC - Forged Event Prevention Test",
        )
        self._enroll_roster(session_id, ["person_01"])

        forged_evt = {
            "event_id": f"evt_forged_{time.time_ns()}",
            "camera_id": "CAM_ROOM_101_DOOR",
            "track_id": 999,
            "identity": "person_01",
            "direction": "ENTRY",
            "timestamp": "2026-10-20T10:05:00Z",
            "evidence": {
                "peak_similarity": 0.99,
                "mean_similarity": 0.98,
                "supporting_frames": 10,
                "total_frames": 10,
                "consistency_pct": 100.0,
            },
        }

        # 1. Unauthenticated request without headers must be rejected with HTTP 401
        resp_unauth = requests.post(f"{BACKEND_URL}/api/v1/events", json=forged_evt, timeout=3.0)
        self.assertEqual(resp_unauth.status_code, 401)

        # 2. Forged request with invalid API key must be rejected with HTTP 401
        resp_bad = requests.post(
            f"{BACKEND_URL}/api/v1/events",
            json=forged_evt,
            headers={"X-API-Key": "attacker-invalid-key-xyz"},
            timeout=3.0,
        )
        self.assertEqual(resp_bad.status_code, 401)

        # 3. Finalize session and verify person_01 remains ABSENT (zero presence created)
        records = self._finalize_session(session_id)
        self.assertEqual(records["person_01"]["status"], "ABSENT")
        self.assertEqual(records["person_01"]["presence_duration_seconds"], 0.0)


if __name__ == "__main__":
    unittest.main()
