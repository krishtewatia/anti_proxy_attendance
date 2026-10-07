"""Unit test for ONE_TIME_ATTENDANCE mode in LiveCVPipeline."""

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock
import numpy as np

SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from camera.base import VideoFrame, VideoSourceType
from pipeline.live_cv_pipeline import LiveCVPipeline, TrackEvidence


class TestOneTimeAttendance(unittest.TestCase):
    def setUp(self):
        self.mock_app = MagicMock()
        self.mock_det = MagicMock()
        self.mock_det.detect.return_value = (np.empty((0, 5), dtype=np.float32), None)
        self.mock_app.det_model = self.mock_det
        self.mock_dispatcher = MagicMock()
        self.gallery = {
            "student_alex": np.random.randn(512).astype(np.float32),
            "student_blake": np.random.randn(512).astype(np.float32),
        }
        # Normalize gallery
        for k in self.gallery:
            self.gallery[k] /= np.linalg.norm(self.gallery[k])

        self.mock_rec = MagicMock()
        def mock_rec_get(frame, face):
            face.embedding = self.gallery["student_alex"]
        self.mock_rec.get.side_effect = mock_rec_get
        self.mock_app.models = {"detection": self.mock_det, "recognition": self.mock_rec}

        self.pipeline = LiveCVPipeline(
            app=self.mock_app,
            gallery=self.gallery,
            event_dispatcher=self.mock_dispatcher,
            camera_id="WEBCAM_01",
            mode="ONE_TIME_ATTENDANCE",
            min_supporting_frames=2,
        )

    def test_one_time_attendance_marking_and_deduplication(self):
        """Student is marked present on first confirmation, ignored on subsequent appearances."""
        # 1. Simulate track for student_alex confirmed
        track = TrackEvidence(
            track_id=1,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            total_frames=3,
            supporting_frames=2,
            assigned_identity="student_alex",
            assigned_confidence=0.85,
            is_confirmed=True,
            recognition_attempts=3,
        )
        self.pipeline.tracks[1] = track

        # Mock frame
        frame = VideoFrame(
            frame=np.zeros((480, 640, 3), dtype=np.uint8),
            timestamp=datetime.now(timezone.utc),
            source_id="WEBCAM_01",
            frame_index=1,
            source_type=VideoSourceType.WEBCAM,
        )

        box = np.array([[100.0, 100.0, 200.0, 200.0, 0.95]], dtype=np.float32)
        self.mock_det.detect.return_value = (box, None)
        # Mock tracker returning online track matching track_id 1
        mock_online_track = MagicMock()
        mock_online_track.track_id = 1
        mock_online_track.tlbr = [100.0, 100.0, 200.0, 200.0]
        self.pipeline.tracker = MagicMock()
        self.pipeline.tracker.update.return_value = [mock_online_track]

        # Process frame 1 -> Should mark PRESENT and dispatch 1 event
        res1 = self.pipeline.process_frame(frame)
        self.assertEqual(len(res1.emitted_events), 1)
        self.assertEqual(res1.emitted_events[0]["identity"], "student_alex")
        self.assertIn("student_alex", self.pipeline.session_marked_students)
        self.assertEqual(self.mock_dispatcher.send_event.call_count, 1)

        # Process frame 2 -> Same student, already marked present -> Should NOT dispatch duplicate event
        res2 = self.pipeline.process_frame(frame)
        self.assertEqual(len(res2.emitted_events), 0)
        self.assertEqual(self.mock_dispatcher.send_event.call_count, 1)

    def test_unknown_face_never_marked_present(self):
        """Unknown faces should never be marked present or emit attendance events."""
        track = TrackEvidence(
            track_id=2,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            total_frames=5,
            supporting_frames=0,
            assigned_identity="UNKNOWN",
            assigned_confidence=0.20,
            is_confirmed=True,
            recognition_attempts=5,
        )
        self.pipeline.tracks[2] = track

        frame = VideoFrame(
            frame=np.zeros((480, 640, 3), dtype=np.uint8),
            timestamp=datetime.now(timezone.utc),
            source_id="WEBCAM_01",
            frame_index=2,
            source_type=VideoSourceType.WEBCAM,
        )

        box = np.array([[100.0, 100.0, 200.0, 200.0, 0.95]], dtype=np.float32)
        self.mock_det.detect.return_value = (box, None)
        mock_online_track = MagicMock()
        mock_online_track.track_id = 2
        mock_online_track.tlbr = [100.0, 100.0, 200.0, 200.0]
        self.pipeline.tracker = MagicMock()
        self.pipeline.tracker.update.return_value = [mock_online_track]

        res = self.pipeline.process_frame(frame)
        self.assertEqual(len(res.emitted_events), 0)
        self.assertNotIn("UNKNOWN", self.pipeline.session_marked_students)
        self.assertEqual(self.mock_dispatcher.send_event.call_count, 0)


if __name__ == "__main__":
    unittest.main()
