"""Comprehensive unit and integration tests for RTSP Robustness, Reconnect, Buffer, and Health."""

from datetime import datetime, timezone
import logging
import time
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from camera.base import VideoSourceType
from camera.rtsp_source import RTSPVideoSource, mask_rtsp_url


class TestRTSPURLMasking(unittest.TestCase):
    """Test safe masking of RTSP credentials."""

    def test_mask_rtsp_credentials(self):
        url_with_pass = "rtsp://admin:SecretPass999@192.168.1.100:554/live/stream1"
        masked = mask_rtsp_url(url_with_pass)
        self.assertNotIn("SecretPass999", masked)
        self.assertIn("*****", masked)
        self.assertEqual(masked, "rtsp://admin:*****@192.168.1.100:554/live/stream1")

    def test_mask_rtsp_no_credentials(self):
        url_clean = "rtsp://192.168.1.100:554/stream"
        masked = mask_rtsp_url(url_clean)
        self.assertEqual(masked, url_clean)

    def test_mask_none_or_empty(self):
        self.assertIsNone(mask_rtsp_url(None))
        self.assertEqual(mask_rtsp_url(""), "")


class TestRTSPBufferAndTelemetry(unittest.TestCase):
    """Test latest-frame-wins bounded queue and health telemetry."""

    @patch("cv2.VideoCapture")
    def test_latest_frame_wins_and_dropped_frames(self, mock_cv_capture):
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True

        # Generate frames with unique pixel markers
        f1 = np.full((100, 100, 3), 1, dtype=np.uint8)
        f2 = np.full((100, 100, 3), 2, dtype=np.uint8)
        f3 = np.full((100, 100, 3), 3, dtype=np.uint8)
        f4 = np.full((100, 100, 3), 4, dtype=np.uint8)

        # Cap returns f1, f2, f3, f4, then keeps returning f4
        frames_iter = iter([f1, f2, f3, f4])
        mock_cap.read.side_effect = lambda: (True, next(frames_iter, f4))
        mock_cv_capture.return_value = mock_cap

        source = RTSPVideoSource(
            rtsp_url="rtsp://admin:test@127.0.0.1:8554/live",
            source_id="CAM_CCTV_BUFFER_TEST",
            queue_size=2,
            target_fps=100.0,
            use_async_reader=True,
        )
        source.open()
        try:
            self.assertEqual(source.status, "CONNECTED")
            # Allow reader thread to ingest several frames while consumer sleeps
            time.sleep(0.05)

            # Consumer reads: should receive latest frame and dropped_frames > 0
            vframe = source.read()
            self.assertIsNotNone(vframe)
            self.assertGreater(source.dropped_frames, 0)
            self.assertIsNotNone(source.last_seen)
            self.assertGreaterEqual(source.fps, 0.0)

            # Verify health summary structure
            health = source.health_summary()
            self.assertEqual(health["source_id"], "CAM_CCTV_BUFFER_TEST")
            self.assertEqual(health["status"], "CONNECTED")
            self.assertIn("fps", health)
            self.assertIn("dropped_frames", health)
        finally:
            source.release()
            self.assertEqual(source.status, "DISCONNECTED")


class TestRTSPReconnectAndRecovery(unittest.TestCase):
    """Test stream disconnection, degraded state, and automatic reconnection."""

    @patch("cv2.VideoCapture")
    def test_transient_failure_reconnects_with_backoff(self, mock_cv_capture):
        """Simulate a camera stream that drops out and recovers."""
        f_good = np.ones((100, 100, 3), dtype=np.uint8)

        # Mock capture 1: succeeds 2 frames then fails
        mock_cap_initial = MagicMock()
        mock_cap_initial.isOpened.return_value = True
        mock_cap_initial.read.side_effect = [(True, f_good), (True, f_good), (False, None)]

        # Mock capture 2: recovery connection
        mock_cap_recovered = MagicMock()
        mock_cap_recovered.isOpened.return_value = True
        mock_cap_recovered.read.return_value = (True, f_good)

        mock_cv_capture.side_effect = [mock_cap_initial, mock_cap_recovered]

        source = RTSPVideoSource(
            rtsp_url="rtsp://10.0.0.1:554/cam",
            source_id="CAM_RECONNECT_TEST",
            reconnect_interval_sec=0.05,
            backoff_factor=1.2,
            max_reconnect_attempts=3,
            use_async_reader=True,
        )
        source.open()
        try:
            # First read succeeds
            f1 = source.read()
            self.assertIsNotNone(f1)
            self.assertEqual(source.status, "CONNECTED")

            # Wait for failure and reconnect to trigger in reader thread
            time.sleep(0.15)

            # Source should have recovered and state returned to CONNECTED
            f_after = source.read()
            self.assertIsNotNone(f_after)
            self.assertEqual(source.status, "CONNECTED")
            self.assertGreater(source.health_summary()["reconnect_attempts"], 0)
        finally:
            source.release()
            self.assertEqual(source.status, "DISCONNECTED")

    @patch("cv2.VideoCapture")
    def test_permanent_failure_transitions_to_disconnected(self, mock_cv_capture):
        """Simulate permanent failure where reconnection limit is exhausted."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        # Immediately fails reading
        mock_cap.read.return_value = (False, None)
        mock_cv_capture.return_value = mock_cap

        source = RTSPVideoSource(
            rtsp_url="rtsp://10.0.0.1:554/cam",
            source_id="CAM_FAIL_TEST",
            reconnect_interval_sec=0.02,
            max_reconnect_attempts=2,
            read_timeout_sec=0.1,
            use_async_reader=True,
        )
        source.open()
        try:
            # Wait for max attempts to fail
            time.sleep(0.15)
            # Read should time out and return None, state should be DISCONNECTED
            res = source.read()
            self.assertIsNone(res)
            self.assertEqual(source.status, "DISCONNECTED")
        finally:
            source.release()


if __name__ == "__main__":
    unittest.main()
