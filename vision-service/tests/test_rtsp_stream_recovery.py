"""Automated Test Proving RTSP Stream Ingestion and Recovery After Stream Interruption.

Verifies Task 5:
- Script/test proving vision service consumes RTSP stream and recovers after
  the stream is stopped and restarted.
"""

from datetime import datetime, timezone
import time
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from camera.base import VideoSourceType
from camera.rtsp_source import RTSPVideoSource


class TestRTSPStreamKillAndRestartRecovery(unittest.TestCase):
    """Test simulating stream kill and subsequent restart."""

    @patch("cv2.VideoCapture")
    def test_stream_interruption_and_clean_recovery(self, mock_cv_capture):
        """Simulate camera stream active -> server dies -> reconnects -> server revived -> recovers."""
        f_sample = np.ones((480, 640, 3), dtype=np.uint8)

        # 1. Initial live stream capture: emits 3 frames, then connection dies
        mock_cap_active = MagicMock()
        mock_cap_active.isOpened.return_value = True
        mock_cap_active.read.side_effect = [
            (True, f_sample),
            (True, f_sample),
            (True, f_sample),
            (False, None),  # Server is killed!
        ]

        # 2. Temporary downtime: reconnection attempts fail (isOpened returns False)
        mock_cap_dead = MagicMock()
        mock_cap_dead.isOpened.return_value = False

        # 3. Stream revived: server restarted and emits frames again
        mock_cap_revived = MagicMock()
        mock_cap_revived.isOpened.return_value = True
        mock_cap_revived.read.return_value = (True, f_sample)

        # Succession of VideoCapture instances during lifecycle
        mock_cv_capture.side_effect = [
            mock_cap_active,    # Initial connect
            mock_cap_dead,      # Attempt 1 while dead
            mock_cap_revived,   # Attempt 2 when revived!
        ]

        source = RTSPVideoSource(
            rtsp_url="rtsp://admin:dev_pass@localhost:8554/cam_doorway",
            source_id="CAM_CCTV_SIMULATED",
            reconnect_interval_sec=0.04,
            backoff_factor=1.2,
            max_reconnect_attempts=5,
            read_timeout_sec=0.5,
            use_async_reader=True,
        )

        source.open()
        try:
            # 1. Initial stream is CONNECTED and reading frames
            f1 = source.read()
            self.assertIsNotNone(f1)
            self.assertEqual(source.status, "CONNECTED")
            self.assertEqual(f1.width, 640)
            self.assertEqual(f1.height, 480)

            # 2. Consume until stream dies
            time.sleep(0.05)
            # When stream dies, status transitions to DEGRADED
            time.sleep(0.08)
            self.assertIn(source.status, ("DEGRADED", "CONNECTED"))

            # 3. Stream revived: wait for auto-reconnect backoff loop to pick up mock_cap_revived
            time.sleep(0.15)

            # Consumer resumes reading: must succeed with fresh frame and return to CONNECTED
            f_revived = source.read()
            self.assertIsNotNone(f_revived)
            self.assertEqual(source.status, "CONNECTED")
            self.assertGreater(source.health_summary()["reconnect_attempts"], 0)

        finally:
            source.release()
            self.assertEqual(source.status, "DISCONNECTED")


if __name__ == "__main__":
    unittest.main()
