"""Unit and benchmark tests for kinematic anti-spoofing and liveness mitigations."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import numpy as np
import pytest

from camera.base import VideoFrame, VideoSourceType
from evaluation.liveness_feasibility import (
    benchmark_kinematic_check,
    run_liveness_feasibility_analysis,
)
from events.event_dispatcher import EventDispatcher
from pipeline.live_cv_pipeline import LiveCVPipeline, TrackEvidence


class TestKinematicAntiSpoofTrackLogic(unittest.TestCase):
    """Test TrackEvidence kinematic calculations for stationary and instant transits."""

    def setUp(self):
        self.t0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
        self.p1 = (0.0, 360.0)
        self.p2 = (640.0, 360.0)
        self.deadband = 4.0

    def test_normal_pedestrian_crossing_passes(self):
        """A normal pedestrian walking through a doorway moves with sufficient displacement and duration."""
        track = TrackEvidence(track_id=1, first_seen=self.t0, last_seen=self.t0)
        # Approach on SIDE_A at t0
        track.update_boundary_position(
            bbox=(200.0, 250.0, 300.0, 350.0),  # cy = 300
            boundary_p1=self.p1,
            boundary_p2=self.p2,
            deadband=self.deadband,
            entry_side="SIDE_A",
            timestamp=self.t0,
        )

        # Cross to SIDE_B after 0.6 seconds, moving 120 pixels in Y
        t1 = self.t0 + timedelta(seconds=0.6)
        track.last_seen = t1
        direction = track.update_boundary_position(
            bbox=(200.0, 370.0, 300.0, 470.0),  # cy = 420 (displacement = 120 px)
            boundary_p1=self.p1,
            boundary_p2=self.p2,
            deadband=self.deadband,
            entry_side="SIDE_A",
            timestamp=t1,
        )

        self.assertEqual(direction, "ENTRY")
        self.assertEqual(track.kinematic_status, "NORMAL")
        self.assertEqual(track.kinematic_anomalies, [])
        self.assertGreaterEqual(track.crossing_displacement_px, 15.0)
        self.assertGreaterEqual(track.transit_duration_sec, 0.20)

    def test_stationary_photo_jiggle_flagged(self):
        """A stationary photo or screen held almost still (displacement < 15 px) is flagged."""
        track = TrackEvidence(track_id=2, first_seen=self.t0, last_seen=self.t0)
        # First seen right near the boundary line (cy = 354, line is 360, deadband is 4 -> on line)
        track.update_boundary_position(
            bbox=(200.0, 300.0, 300.0, 408.0),  # cy = 354 (Side A)
            boundary_p1=self.p1,
            boundary_p2=self.p2,
            deadband=self.deadband,
            entry_side="SIDE_A",
            timestamp=self.t0,
        )

        # Micro-movement of only 11 pixels across the line
        t1 = self.t0 + timedelta(seconds=0.5)
        track.last_seen = t1
        direction = track.update_boundary_position(
            bbox=(200.0, 311.0, 300.0, 419.0),  # cy = 365 (Side B, displacement = 11 px)
            boundary_p1=self.p1,
            boundary_p2=self.p2,
            deadband=self.deadband,
            entry_side="SIDE_A",
            timestamp=t1,
            min_track_displacement_px=15.0,
        )

        self.assertEqual(direction, "ENTRY")
        self.assertEqual(track.kinematic_status, "FLAGGED_STATIONARY")
        self.assertIn("INSUFFICIENT_DISPLACEMENT", track.kinematic_anomalies)
        self.assertLess(track.crossing_displacement_px, 15.0)

    def test_instant_phone_swipe_flagged(self):
        """A fast swipe or detection teleportation crossing in < 0.20 seconds is flagged."""
        track = TrackEvidence(track_id=3, first_seen=self.t0, last_seen=self.t0)
        track.update_boundary_position(
            bbox=(200.0, 200.0, 300.0, 300.0),  # cy = 250
            boundary_p1=self.p1,
            boundary_p2=self.p2,
            deadband=self.deadband,
            entry_side="SIDE_A",
            timestamp=self.t0,
        )

        # Crosses in only 0.08 seconds (teleportation / fast phone wave)
        t_fast = self.t0 + timedelta(seconds=0.08)
        track.last_seen = t_fast
        direction = track.update_boundary_position(
            bbox=(200.0, 380.0, 300.0, 480.0),  # cy = 430
            boundary_p1=self.p1,
            boundary_p2=self.p2,
            deadband=self.deadband,
            entry_side="SIDE_A",
            timestamp=t_fast,
            min_transit_duration_sec=0.20,
        )

        self.assertEqual(direction, "ENTRY")
        self.assertEqual(track.kinematic_status, "FLAGGED_INSTANT")
        self.assertIn("INSTANT_TRANSIT", track.kinematic_anomalies)
        self.assertLess(track.transit_duration_sec, 0.20)

    def test_stationary_hover_flagged(self):
        """A stationary image lingering in front of the camera for > 8s before crossing is flagged."""
        track = TrackEvidence(track_id=4, first_seen=self.t0, last_seen=self.t0)
        track.update_boundary_position(
            bbox=(200.0, 300.0, 300.0, 400.0),  # cy = 350
            boundary_p1=self.p1,
            boundary_p2=self.p2,
            deadband=self.deadband,
            entry_side="SIDE_A",
            timestamp=self.t0,
        )

        # Lingers for 12 seconds with barely 16 pixels movement
        t_slow = self.t0 + timedelta(seconds=12.0)
        track.last_seen = t_slow
        direction = track.update_boundary_position(
            bbox=(200.0, 316.0, 300.0, 416.0),  # cy = 366 (disp = 16 px, threshold * 1.5 = 22.5)
            boundary_p1=self.p1,
            boundary_p2=self.p2,
            deadband=self.deadband,
            entry_side="SIDE_A",
            timestamp=t_slow,
            max_stationary_duration_sec=8.0,
        )

        self.assertEqual(direction, "ENTRY")
        self.assertIn("STATIONARY_HOVER", track.kinematic_anomalies)


class TestPipelineKinematicPolicies(unittest.TestCase):
    """Test LiveCVPipeline behavior under FLAG vs REJECT policies."""

    def _setup_pipeline(self, policy: str = "FLAG", enable_anti_spoof: bool = True):
        mock_dispatcher = MagicMock(spec=EventDispatcher)
        mock_dispatcher.send_event.return_value = {"event_id": "evt_123", "status": "accepted"}

        mock_app = MagicMock()
        det_mock = MagicMock()
        rec_mock = MagicMock()

        emb_person = np.ones(512, dtype=np.float32) / np.sqrt(512)
        gallery = {"person_01": emb_person}

        def mock_rec_get(frame, face):
            face.embedding = emb_person.copy()

        rec_mock.get.side_effect = mock_rec_get
        mock_app.models = {"detection": det_mock, "recognition": rec_mock}
        mock_app.det_model = det_mock

        pipeline = LiveCVPipeline(
            app=mock_app,
            gallery=gallery,
            similarity_threshold=0.40,
            min_margin=0.10,
            min_supporting_frames=1,  # 1 vote confirms for easy test setup
            boundary_line=((0.0, 360.0), (640.0, 360.0)),
            deadband_pixels=4.0,
            event_dispatcher=mock_dispatcher,
            enable_kinematic_anti_spoof=enable_anti_spoof,
            kinematic_spoof_policy=policy,
            min_track_displacement_px=30.0,
            min_transit_duration_sec=0.20,
        )
        return pipeline, det_mock, mock_dispatcher

    def test_pipeline_flag_policy_emits_with_anomaly_metadata(self):
        """Under FLAG policy, an anomalous transit emits the event with FLAGGED status."""
        pipeline, det_mock, dispatcher = self._setup_pipeline(policy="FLAG")
        test_img = np.zeros((720, 640, 3), dtype=np.uint8)

        # Frame 1: cy = 352 (Side A)
        box1 = np.array([[200.0, 302.0, 300.0, 402.0, 0.95]], dtype=np.float32)
        det_mock.detect.return_value = (box1, None)
        f1 = VideoFrame(frame=test_img, timestamp=datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc), frame_index=1, source_id="CAM_1", source_type=VideoSourceType.WEBRTC)
        pipeline.process_frame(f1)

        # Frame 2: cy = 368 (Side B, displacement = 16px < min 30px)
        box2 = np.array([[200.0, 318.0, 300.0, 418.0, 0.95]], dtype=np.float32)
        det_mock.detect.return_value = (box2, None)
        f2 = VideoFrame(frame=test_img, timestamp=datetime(2026, 10, 20, 10, 0, 1, tzinfo=timezone.utc), frame_index=2, source_id="CAM_1", source_type=VideoSourceType.WEBRTC)
        res2 = pipeline.process_frame(f2)

        # Should emit 1 event with kinematic_status FLAGGED_STATIONARY
        self.assertEqual(len(res2.emitted_events), 1)
        evt = res2.emitted_events[0]
        self.assertEqual(evt["direction"], "ENTRY")
        self.assertEqual(evt["kinematic_status"], "FLAGGED_STATIONARY")
        self.assertIn("INSUFFICIENT_DISPLACEMENT", evt["kinematic_anomalies"])
        dispatcher.send_event.assert_called_once()

    def test_pipeline_reject_policy_drops_anomalous_transit(self):
        """Under REJECT policy, an anomalous transit event is dropped and not dispatched."""
        pipeline, det_mock, dispatcher = self._setup_pipeline(policy="REJECT")
        test_img = np.zeros((720, 640, 3), dtype=np.uint8)

        # Frame 1: cy = 352
        box1 = np.array([[200.0, 302.0, 300.0, 402.0, 0.95]], dtype=np.float32)
        det_mock.detect.return_value = (box1, None)
        f1 = VideoFrame(frame=test_img, timestamp=datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc), frame_index=1, source_id="CAM_1", source_type=VideoSourceType.WEBRTC)
        pipeline.process_frame(f1)

        # Frame 2: cy = 368 (insufficient displacement)
        box2 = np.array([[200.0, 318.0, 300.0, 418.0, 0.95]], dtype=np.float32)
        det_mock.detect.return_value = (box2, None)
        f2 = VideoFrame(frame=test_img, timestamp=datetime(2026, 10, 20, 10, 0, 1, tzinfo=timezone.utc), frame_index=2, source_id="CAM_1", source_type=VideoSourceType.WEBRTC)
        res2 = pipeline.process_frame(f2)

        # In REJECT mode: Event is suppressed!
        self.assertEqual(len(res2.emitted_events), 0)
        dispatcher.send_event.assert_not_called()

    def test_pipeline_disabled_anti_spoof_allows_all(self):
        """When enable_kinematic_anti_spoof is False, zero-displacement crossings emit normally."""
        pipeline, det_mock, dispatcher = self._setup_pipeline(policy="REJECT", enable_anti_spoof=False)
        test_img = np.zeros((720, 640, 3), dtype=np.uint8)

        # Frame 1: cy = 352
        box1 = np.array([[200.0, 302.0, 300.0, 402.0, 0.95]], dtype=np.float32)
        det_mock.detect.return_value = (box1, None)
        f1 = VideoFrame(frame=test_img, timestamp=datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc), frame_index=1, source_id="CAM_1", source_type=VideoSourceType.WEBRTC)
        pipeline.process_frame(f1)

        # Frame 2: cy = 368
        box2 = np.array([[200.0, 318.0, 300.0, 418.0, 0.95]], dtype=np.float32)
        det_mock.detect.return_value = (box2, None)
        f2 = VideoFrame(frame=test_img, timestamp=datetime(2026, 10, 20, 10, 0, 1, tzinfo=timezone.utc), frame_index=2, source_id="CAM_1", source_type=VideoSourceType.WEBRTC)
        res2 = pipeline.process_frame(f2)

        # Emits despite anomaly because check is disabled
        self.assertEqual(len(res2.emitted_events), 1)
        dispatcher.send_event.assert_called_once()


class TestLivenessFeasibilityBenchmark(unittest.TestCase):
    """Test feasibility analysis runner and benchmark latency bounds."""

    def test_kinematic_latency_sub_millisecond(self):
        """Kinematic check executes in < 0.05 ms."""
        lat = benchmark_kinematic_check(iterations=500)
        self.assertLess(lat, 0.05)

    def test_feasibility_analysis_verdicts(self):
        """Feasibility analysis correctly categorizes candidates based on FPS budget."""
        options = run_liveness_feasibility_analysis()
        self.assertEqual(len(options), 4)

        kinematic = next(o for o in options if "Kinematic" in o.name)
        self.assertTrue(kinematic.meets_fps_budget)
        self.assertEqual(kinematic.feasibility_verdict, "ADOPT (Local MVP)")

        minifasnet = next(o for o in options if "MiniFASNet" in o.name)
        self.assertFalse(minifasnet.meets_fps_budget)
        self.assertEqual(minifasnet.feasibility_verdict, "POSTPONE")

        mobilenet = next(o for o in options if "MobileNetV3" in o.name)
        self.assertFalse(mobilenet.meets_fps_budget)
        self.assertEqual(mobilenet.feasibility_verdict, "POSTPONE")
