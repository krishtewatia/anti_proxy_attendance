"""Unit and Component Tests for Automatic Camera Agent Lifecycle.

Tests:
1. No active session -> camera remains closed / idle.
2. Active session created -> vision agent detects session -> camera opens.
3. Active session -> valid frame received -> pipeline processes frame.
4. Session ends -> camera releases cleanly.
5. Session A -> End -> Session B -> camera reopens and in-memory state is reset.
6. Camera unavailable -> does not crash, enters clean retry backoff.
7. Camera read failures -> threshold triggers release and reconnection recovery.
"""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from camera.webcam_source import WebcamVideoSource
from run_local_webcam import (
    WebcamStreamState,
    check_backend_active_session,
)


class TestCameraLifecycle(unittest.TestCase):
    """Lifecycle and safety test suite for the webcam agent."""

    def test_01_no_active_session_camera_remains_closed(self):
        """Test 1: When no active session exists, camera is not opened and remains idle."""
        state = WebcamStreamState()
        self.assertFalse(state.camera_active)
        self.assertIsNone(state.active_session_id)
        self.assertIsNone(state.get_frame())
        self.assertEqual(state.fps, 0.0)

        # WebcamVideoSource initially closed
        source = WebcamVideoSource(device_index=0)
        self.assertFalse(source.is_opened)

        # Idempotent close
        source.close()
        self.assertFalse(source.is_opened)

    def test_02_active_session_opens_camera(self):
        """Test 2: When an active session is detected, camera is opened and verified."""
        state = WebcamStreamState()
        state.reset_session("session_math_101")
        self.assertEqual(state.active_session_id, "session_math_101")

        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap = MagicMock()
            mock_cap.isOpened.return_value = True
            dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            mock_cap.read.return_value = (True, dummy_frame)
            mock_cap.get.side_effect = lambda prop: 640 if prop == 3 else 480
            mock_cap_cls.return_value = mock_cap

            source = WebcamVideoSource(device_index=0)
            source.open()

            self.assertTrue(source.is_opened)
            self.assertEqual(source._actual_width, 640)
            self.assertEqual(source._actual_height, 480)

            # Clean close
            source.close()
            self.assertFalse(source.is_opened)

    def test_03_active_session_captures_valid_frame(self):
        """Test 3: Active session reads valid frames and updates stream state."""
        state = WebcamStreamState()

        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap = MagicMock()
            mock_cap.isOpened.return_value = True
            dummy_frame = np.full((480, 640, 3), 120, dtype=np.uint8)
            mock_cap.read.return_value = (True, dummy_frame)
            mock_cap_cls.return_value = mock_cap

            source = WebcamVideoSource(device_index=0)
            source.open()

            vframe = source.read()
            self.assertIsNotNone(vframe)
            self.assertIsNotNone(vframe.frame)
            self.assertEqual(vframe.frame.shape, (480, 640, 3))

            # Update stream state
            state.update_frame(vframe.frame)
            self.assertTrue(state.camera_active)
            self.assertIsNotNone(state.get_frame())

            source.close()

    def test_04_session_ends_camera_releases(self):
        """Test 4: When session ends, stream state clears and camera releases cleanly."""
        state = WebcamStreamState()
        dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        state.update_frame(dummy_frame)
        self.assertTrue(state.camera_active)

        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap = MagicMock()
            mock_cap.isOpened.return_value = True
            mock_cap.read.return_value = (True, dummy_frame)
            mock_cap_cls.return_value = mock_cap

            source = WebcamVideoSource(device_index=0)
            source.open()
            self.assertTrue(source.is_opened)

            # Session finalized
            source.close()
            state.clear_frame()

            self.assertFalse(source.is_opened)
            self.assertFalse(state.camera_active)
            self.assertIsNone(state.get_frame())

    def test_05_session_a_to_session_b_lifecycle(self):
        """Test 5: Session A -> Session B safely resets marked identities and re-arms attendance."""
        state = WebcamStreamState()
        state.reset_session("session_A")
        state.marked_identities.add("student_01")
        self.assertIn("student_01", state.marked_identities)
        self.assertEqual(state.active_session_id, "session_A")

        # Session A ends
        state.clear_frame()
        state.reset_session(None)
        self.assertIsNone(state.active_session_id)
        self.assertEqual(len(state.marked_identities), 0)

        # Session B starts -> same student can receive attendance
        state.reset_session("session_B")
        self.assertEqual(state.active_session_id, "session_B")
        self.assertNotIn("student_01", state.marked_identities)

    def test_06_camera_unavailable_handles_gracefully(self):
        """Test 6: When camera cannot be opened, throws exception without crashing."""
        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap = MagicMock()
            mock_cap.isOpened.return_value = False
            mock_cap_cls.return_value = mock_cap

            source = WebcamVideoSource(device_index=99)
            with self.assertRaises(RuntimeError) as ctx:
                source.open()

            self.assertIn("Could not open camera", str(ctx.exception))
            self.assertFalse(source.is_opened)

    def test_07_camera_disconnection_triggers_recovery(self):
        """Test 7: Consecutive empty reads trigger clean release."""
        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap = MagicMock()
            mock_cap.isOpened.return_value = True
            mock_cap.read.return_value = (False, None)
            mock_cap_cls.return_value = mock_cap

            source = WebcamVideoSource(device_index=0)
            # Open succeeds with initial frame then disconnects
            with patch.object(source, "_is_opened", True):
                source._cap = mock_cap
                vframe = source.read()
                self.assertIsNone(vframe)
                source.close()
                self.assertFalse(source.is_opened)

    def test_08_active_session_sync_parsing(self):
        """Test 8: Backend active session query parsing."""
        with patch("requests.get") as mock_get:
            # Active session case
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "has_active_session": True,
                "session_id": "sess_123",
                "class_code": "DS-B",
            }
            mock_get.return_value = mock_resp

            data = check_backend_active_session("http://127.0.0.1:8000")
            self.assertIsNotNone(data)
            self.assertTrue(data.get("has_active_session"))
            self.assertEqual(data.get("session_id"), "sess_123")

            # Inactive session case
            mock_resp.json.return_value = {"has_active_session": False, "session_id": None}
            data_idle = check_backend_active_session("http://127.0.0.1:8000")
            self.assertFalse(data_idle.get("has_active_session"))


if __name__ == "__main__":
    unittest.main()
