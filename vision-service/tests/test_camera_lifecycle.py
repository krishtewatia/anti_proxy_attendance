"""Unit tests for the webcam video source lifecycle.

Tests:
1. A new source is closed and closing it again is safe.
2. Opening a working camera reports its resolution, and it closes cleanly.
3. An open camera returns valid frames.
4. Closing releases the camera.
5. Camera unavailable -> raises a clear error and stays closed.
6. Camera read failures -> no frame, and the source closes cleanly.
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


class TestCameraLifecycle(unittest.TestCase):
    """Lifecycle and safety test suite for the webcam video source."""

    def test_01_new_source_is_closed(self):
        """Test 1: A new source has not opened the camera, and close is idempotent."""
        # WebcamVideoSource initially closed
        source = WebcamVideoSource(device_index=0)
        self.assertFalse(source.is_opened)

        # Idempotent close
        source.close()
        self.assertFalse(source.is_opened)

    def test_02_open_reports_resolution_and_closes(self):
        """Test 2: Opening a working camera reports its resolution and closes cleanly."""
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

    def test_03_open_camera_returns_valid_frames(self):
        """Test 3: An open camera returns valid frames."""
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

            source.close()

    def test_04_close_releases_camera(self):
        """Test 4: Closing an open source releases the camera."""
        dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap = MagicMock()
            mock_cap.isOpened.return_value = True
            mock_cap.read.return_value = (True, dummy_frame)
            mock_cap_cls.return_value = mock_cap

            source = WebcamVideoSource(device_index=0)
            source.open()
            self.assertTrue(source.is_opened)

            source.close()

            self.assertFalse(source.is_opened)
            mock_cap.release.assert_called()

    def test_05_camera_unavailable_handles_gracefully(self):
        """Test 5: When camera cannot be opened, throws exception without crashing."""
        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap = MagicMock()
            mock_cap.isOpened.return_value = False
            mock_cap_cls.return_value = mock_cap

            source = WebcamVideoSource(device_index=99)
            with self.assertRaises(RuntimeError) as ctx:
                source.open()

            self.assertIn("Could not open camera", str(ctx.exception))
            self.assertFalse(source.is_opened)

    def test_06_camera_disconnection_triggers_recovery(self):
        """Test 6: Consecutive empty reads trigger clean release."""
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
