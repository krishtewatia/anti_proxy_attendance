"""Unit and Integration Tests for Step 2D.5: CV Lifecycle -> EventDispatcher Integration.

Validates:
1. Spatial Boundary Geometry (classify_point_side with hysteresis deadband).
2. Trajectory Direction State Transitions (SIDE_A -> SIDE_B = ENTRY, SIDE_B -> SIDE_A = EXIT).
3. Event Gating Safety Rule:
   - UNKNOWN tracks must NEVER generate attendance events.
   - Unconfirmed identities must NEVER generate attendance events.
   - Confirmed known identities crossing boundary produce exactly 1 compliant sensory event.
   - Deduplication prevents multiple event emissions for the same direction.
4. LiveCVPipeline -> EventDispatcher transmission matching VisionEventCreate schema.
"""

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

import numpy as np

# Ensure vision-service root is in sys.path
SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from camera.base import VideoFrame, VideoSourceType
from events.event_dispatcher import EventDispatcher
from pipeline.live_cv_pipeline import (
    LiveCVPipeline,
    TrackEvidence,
    classify_point_side,
)


class TestBoundaryGeometry(unittest.TestCase):
    """Test 2D line-crossing spatial geometry with deadband hysteresis."""

    def test_horizontal_boundary_classification(self):
        """Horizontal line at Y=360 with deadband +/- 4px."""
        p1 = (0.0, 360.0)
        p2 = (640.0, 360.0)
        deadband = 4.0

        # Approach zone (SIDE_A, above line)
        self.assertEqual(classify_point_side(320.0, 200.0, p1, p2, deadband), "SIDE_A")
        self.assertEqual(classify_point_side(320.0, 355.0, p1, p2, deadband), "SIDE_A")

        # Deadband zone (ON_LINE)
        self.assertEqual(classify_point_side(320.0, 358.0, p1, p2, deadband), "ON_LINE")
        self.assertEqual(classify_point_side(320.0, 360.0, p1, p2, deadband), "ON_LINE")
        self.assertEqual(classify_point_side(320.0, 363.0, p1, p2, deadband), "ON_LINE")

        # Entered zone (SIDE_B, below line)
        self.assertEqual(classify_point_side(320.0, 365.0, p1, p2, deadband), "SIDE_B")
        self.assertEqual(classify_point_side(320.0, 500.0, p1, p2, deadband), "SIDE_B")

    def test_vertical_boundary_classification(self):
        """Vertical line at X=500 with deadband +/- 5px."""
        p1 = (500.0, 0.0)
        p2 = (500.0, 720.0)
        deadband = 5.0

        self.assertEqual(classify_point_side(400.0, 360.0, p1, p2, deadband), "SIDE_A")
        self.assertEqual(classify_point_side(498.0, 360.0, p1, p2, deadband), "ON_LINE")
        self.assertEqual(classify_point_side(600.0, 360.0, p1, p2, deadband), "SIDE_B")


class TestTrackBoundaryStateAndSafetyGate(unittest.TestCase):
    """Test direction state transitions and event gating safety rules on TrackEvidence."""

    def setUp(self):
        self.t0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
        self.p1 = (0.0, 360.0)
        self.p2 = (640.0, 360.0)
        self.deadband = 4.0

    def test_unconfirmed_track_crossing_does_not_emit(self):
        """Safety Rule: An unconfirmed track crossing boundary MUST NOT emit an event."""
        evidence = TrackEvidence(track_id=1, first_seen=self.t0, last_seen=self.t0)

        # Frame 1: on SIDE_A (cy = 200)
        bbox1 = (100.0, 150.0, 200.0, 250.0)  # cy = 200
        dir1 = evidence.update_boundary_position(bbox1, self.p1, self.p2, self.deadband)
        self.assertIsNone(dir1)
        self.assertEqual(evidence.initial_side, "SIDE_A")
        self.assertEqual(evidence.current_side, "SIDE_A")

        # Frame 2: crosses to SIDE_B (cy = 450)
        bbox2 = (100.0, 400.0, 200.0, 500.0)  # cy = 450
        dir2 = evidence.update_boundary_position(bbox2, self.p1, self.p2, self.deadband)
        self.assertEqual(dir2, "ENTRY")
        self.assertEqual(evidence.pending_directions, ["ENTRY"])

        # Track is NOT confirmed -> Gate must return empty!
        self.assertFalse(evidence.is_confirmed)
        self.assertEqual(evidence.get_emittable_directions(), [])

    def test_unknown_identity_crossing_does_not_emit(self):
        """Safety Rule: UNKNOWN tracks MUST NEVER generate attendance events."""
        evidence = TrackEvidence(track_id=2, first_seen=self.t0, last_seen=self.t0)

        # Crosses boundary
        evidence.update_boundary_position((100.0, 150.0, 200.0, 250.0), self.p1, self.p2, self.deadband)
        evidence.update_boundary_position((100.0, 400.0, 200.0, 500.0), self.p1, self.p2, self.deadband)
        self.assertEqual(evidence.pending_directions, ["ENTRY"])

        # Finalized as UNKNOWN after max attempts
        evidence.add_observation(
            identity="UNKNOWN",
            score=0.20,
            bbox=(100.0, 400.0, 200.0, 500.0),
            timestamp=self.t0,
            min_supporting_frames=3,
            max_unknown_attempts=3,
        )
        evidence.add_observation(
            identity="UNKNOWN",
            score=0.21,
            bbox=(100.0, 400.0, 200.0, 500.0),
            timestamp=self.t0,
            min_supporting_frames=3,
            max_unknown_attempts=3,
        )
        evidence.add_observation(
            identity="UNKNOWN",
            score=0.19,
            bbox=(100.0, 400.0, 200.0, 500.0),
            timestamp=self.t0,
            min_supporting_frames=3,
            max_unknown_attempts=3,
        )

        self.assertTrue(evidence.is_confirmed)
        self.assertEqual(evidence.assigned_identity, "UNKNOWN")

        # Gate must reject UNKNOWN track
        self.assertEqual(evidence.get_emittable_directions(), [])

    def test_confirmed_known_track_crossing_emits_entry_and_exit(self):
        """Known enrolled track crossing emits ENTRY, and later EXIT upon returning."""
        evidence = TrackEvidence(track_id=3, first_seen=self.t0, last_seen=self.t0)

        # 3 votes for person_01 (Confirmed!)
        for i in range(3):
            evidence.add_observation(
                identity="person_01",
                score=0.65,
                bbox=(100.0, 150.0, 200.0, 250.0),
                timestamp=self.t0,
                min_supporting_frames=3,
            )
        self.assertTrue(evidence.is_confirmed)
        self.assertEqual(evidence.assigned_identity, "person_01")

        # 1. Approach on SIDE_A
        evidence.update_boundary_position((100.0, 150.0, 200.0, 250.0), self.p1, self.p2, self.deadband)
        self.assertEqual(evidence.get_emittable_directions(), [])

        # 2. Cross to SIDE_B (ENTRY)
        dir_in = evidence.update_boundary_position((100.0, 400.0, 200.0, 500.0), self.p1, self.p2, self.deadband)
        self.assertEqual(dir_in, "ENTRY")

        # Safety gate evaluates: Confirmed + Known -> EMIT!
        emittable = evidence.get_emittable_directions()
        self.assertEqual(emittable, ["ENTRY"])

        # Mark as emitted (as dispatcher would)
        evidence.mark_emitted("ENTRY")

        # 3. Subsequent frames in SIDE_B must NOT emit duplicates
        evidence.update_boundary_position((100.0, 420.0, 200.0, 520.0), self.p1, self.p2, self.deadband)
        self.assertEqual(evidence.get_emittable_directions(), [])

        # 4. Move back to SIDE_A (EXIT)
        dir_out = evidence.update_boundary_position((100.0, 180.0, 200.0, 280.0), self.p1, self.p2, self.deadband)
        self.assertEqual(dir_out, "EXIT")

        # Gate evaluates EXIT
        emittable_exit = evidence.get_emittable_directions()
        self.assertEqual(emittable_exit, ["EXIT"])
        evidence.mark_emitted("EXIT")

        # No duplicate EXIT
        self.assertEqual(evidence.get_emittable_directions(), [])


class TestLiveCVPipelineEventIntegration(unittest.TestCase):
    """Test full LiveCVPipeline event generation and dispatching to EventDispatcher."""

    def test_pipeline_dispatches_sensory_event_on_boundary_crossing(self):
        """Pipeline generates compliant sensory payload and calls EventDispatcher.send_event."""
        mock_dispatcher = MagicMock(spec=EventDispatcher)
        mock_dispatcher.send_event.return_value = {"event_id": "evt_123", "status": "accepted"}

        # Mock detection and recognition models
        mock_app = MagicMock()
        det_mock = MagicMock()
        rec_mock = MagicMock()

        np.random.seed(42)
        emb_person = np.random.randn(512).astype(np.float32)
        emb_person /= np.linalg.norm(emb_person)
        gallery = {"person_01": emb_person}

        def mock_rec_get(frame, face):
            face.embedding = emb_person.copy()

        rec_mock.get.side_effect = mock_rec_get

        mock_app.models = {
            "detection": det_mock,
            "recognition": rec_mock,
        }
        mock_app.det_model = det_mock

        pipeline = LiveCVPipeline(
            app=mock_app,
            gallery=gallery,
            similarity_threshold=0.40,
            min_margin=0.10,
            min_supporting_frames=2,
            source_id="PHONE_CAM_01",
            boundary_line=((0.0, 360.0), (640.0, 360.0)),
            deadband_pixels=4.0,
            event_dispatcher=mock_dispatcher,
            camera_id="CAM_ROOM_101_DOOR",
        )

        test_img = np.zeros((720, 640, 3), dtype=np.uint8)

        # Frame 1: person on SIDE_A (cy = 330, line is at 360)
        box1 = np.array([[200.0, 280.0, 300.0, 380.0, 0.95]], dtype=np.float32)
        det_mock.detect.return_value = (box1, None)
        frame1 = VideoFrame(
            frame=test_img,
            timestamp=datetime(2026, 10, 20, 10, 5, 0, tzinfo=timezone.utc),
            frame_index=1,
            source_id="PHONE_CAM_01",
            source_type=VideoSourceType.PHONE,
        )
        res1 = pipeline.process_frame(frame1)
        self.assertEqual(len(res1.emitted_events), 0)

        # Frame 2: person still on SIDE_A (cy = 345) -> achieves 2 votes (Confirmed!)
        box2 = np.array([[200.0, 295.0, 300.0, 395.0, 0.95]], dtype=np.float32)
        det_mock.detect.return_value = (box2, None)
        frame2 = VideoFrame(
            frame=test_img,
            timestamp=datetime(2026, 10, 20, 10, 5, 1, tzinfo=timezone.utc),
            frame_index=2,
            source_id="PHONE_CAM_01",
            source_type=VideoSourceType.PHONE,
        )
        res2 = pipeline.process_frame(frame2)
        self.assertEqual(len(res2.emitted_events), 0)
        # ByteTrack track IDs are auto-incrementing class-level, so look up dynamically
        self.assertEqual(len(pipeline.tracks), 1)
        track_id = next(iter(pipeline.tracks))
        self.assertTrue(pipeline.tracks[track_id].is_confirmed)
        self.assertEqual(pipeline.tracks[track_id].assigned_identity, "person_01")

        # Frame 3: person in deadband zone (cy = 360)
        box3 = np.array([[200.0, 310.0, 300.0, 410.0, 0.95]], dtype=np.float32)
        det_mock.detect.return_value = (box3, None)
        frame3 = VideoFrame(
            frame=test_img,
            timestamp=datetime(2026, 10, 20, 10, 5, 2, tzinfo=timezone.utc),
            frame_index=3,
            source_id="PHONE_CAM_01",
            source_type=VideoSourceType.PHONE,
        )
        res3 = pipeline.process_frame(frame3)
        self.assertEqual(len(res3.emitted_events), 0)

        # Frame 4: person crosses cleanly into SIDE_B (cy = 380, below line at 360) -> ENTRY!
        box4 = np.array([[200.0, 330.0, 300.0, 430.0, 0.95]], dtype=np.float32)
        det_mock.detect.return_value = (box4, None)
        frame4 = VideoFrame(
            frame=test_img,
            timestamp=datetime(2026, 10, 20, 10, 5, 3, tzinfo=timezone.utc),
            frame_index=4,
            source_id="PHONE_CAM_01",
            source_type=VideoSourceType.PHONE,
        )
        res4 = pipeline.process_frame(frame4)

        # Verify event was emitted on frame 4
        self.assertEqual(len(res4.emitted_events), 1)
        evt = res4.emitted_events[0]
        self.assertEqual(evt["camera_id"], "CAM_ROOM_101_DOOR")
        self.assertEqual(evt["identity"], "person_01")
        self.assertEqual(evt["direction"], "ENTRY")
        self.assertEqual(evt["track_id"], track_id)

        # Verify sensory evidence format
        self.assertGreaterEqual(evt["evidence"]["peak_similarity"], 0.65)
        self.assertGreaterEqual(evt["evidence"]["supporting_frames"], 2)
        self.assertEqual(evt["evidence"]["consistency_pct"], 100.0)

        # Verify mock dispatcher was called
        mock_dispatcher.send_event.assert_called_once()
        sent_payload = mock_dispatcher.send_event.call_args[0][0]
        self.assertEqual(sent_payload["event_id"], evt["event_id"])
        self.assertEqual(sent_payload["direction"], "ENTRY")
        self.assertEqual(sent_payload["identity"], "person_01")

        # Frame 5: person remains in SIDE_B (cy = 395) -> NO duplicate event
        box5 = np.array([[200.0, 345.0, 300.0, 445.0, 0.95]], dtype=np.float32)
        det_mock.detect.return_value = (box5, None)
        frame5 = VideoFrame(
            frame=test_img,
            timestamp=datetime(2026, 10, 20, 10, 5, 4, tzinfo=timezone.utc),
            frame_index=5,
            source_id="PHONE_CAM_01",
            source_type=VideoSourceType.PHONE,
        )
        res5 = pipeline.process_frame(frame5)
        self.assertEqual(len(res5.emitted_events), 0)
        self.assertEqual(mock_dispatcher.send_event.call_count, 1)

    def test_swap_scrfd_detector_path_and_string_support(self):
        """Regression test: swap_scrfd_detector must accept Path objects as well as string identifiers."""
        from unittest.mock import patch
        from pipeline.live_cv_pipeline import swap_scrfd_detector

        mock_app = MagicMock()
        mock_app.models = {}

        # 1. String alias '0.5g'
        with patch("os.path.exists", return_value=True), \
             patch("insightface.model_zoo.get_model") as mock_get_model, \
             patch("pipeline.live_cv_pipeline.configure_scrfd_threads"):
            mock_model = MagicMock()
            mock_get_model.return_value = mock_model
            swap_scrfd_detector(mock_app, detector_type="0.5g")
            self.assertEqual(mock_app.det_model, mock_model)

        # 2. Path instance directly
        fake_path = Path("/custom/models/scrfd_500m.onnx")
        with patch("os.path.exists", return_value=True), \
             patch("insightface.model_zoo.get_model") as mock_get_model, \
             patch("pipeline.live_cv_pipeline.configure_scrfd_threads"):
            mock_model = MagicMock()
            mock_get_model.return_value = mock_model
            swap_scrfd_detector(mock_app, detector_type=fake_path)
            self.assertEqual(mock_app.det_model, mock_model)


if __name__ == "__main__":
    unittest.main()
