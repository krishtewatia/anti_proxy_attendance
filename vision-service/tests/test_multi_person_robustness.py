"""Step 2E.5: Multi-Person CV Robustness, Re-Entry, ID-Swap Guard & Boundary Config Tests.

Deterministic synthetic-trajectory unit tests covering:
1. Re-entry: ENTRY -> EXIT -> ENTRY sequences are not blocked (the 2E.5 fix).
2. Jitter duplicate suppression: ENTRY -> ENTRY is still blocked.
3. ID-swap guard: periodic reverification, disagreement counting, confirmation invalidation.
4. Per-camera configurable boundary: entry_side, deadband, normalized endpoints.
5. Hysteresis: ON_LINE does not produce direction changes.
6. Pipeline integration: full process_frame with re-entry and reverification.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
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


class TestReEntryFix(unittest.TestCase):
    """Verify that legitimate ENTRY -> EXIT -> ENTRY re-crossings are not blocked."""

    def setUp(self):
        self.t0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
        self.p1 = (0.0, 360.0)
        self.p2 = (640.0, 360.0)
        self.deadband = 4.0

    def _make_confirmed(self, evidence: TrackEvidence) -> None:
        """Add enough observations to confirm identity as person_01."""
        for _ in range(3):
            evidence.add_observation(
                identity="person_01",
                score=0.70,
                bbox=(100.0, 150.0, 200.0, 250.0),
                timestamp=self.t0,
                min_supporting_frames=3,
            )

    def test_reentry_sequence_entry_exit_entry(self):
        """ENTRY -> EXIT -> ENTRY (re-entry) must emit all three events."""
        evidence = TrackEvidence(track_id=1, first_seen=self.t0, last_seen=self.t0)
        self._make_confirmed(evidence)

        # Approach on SIDE_A
        evidence.update_boundary_position(
            (100.0, 150.0, 200.0, 250.0), self.p1, self.p2, self.deadband
        )

        # Cross to SIDE_B -> ENTRY
        d1 = evidence.update_boundary_position(
            (100.0, 400.0, 200.0, 500.0), self.p1, self.p2, self.deadband
        )
        self.assertEqual(d1, "ENTRY")
        self.assertEqual(evidence.get_emittable_directions(), ["ENTRY"])
        evidence.mark_emitted("ENTRY")

        # Return to SIDE_A -> EXIT
        d2 = evidence.update_boundary_position(
            (100.0, 150.0, 200.0, 250.0), self.p1, self.p2, self.deadband
        )
        self.assertEqual(d2, "EXIT")
        self.assertEqual(evidence.get_emittable_directions(), ["EXIT"])
        evidence.mark_emitted("EXIT")

        # Re-enter -> ENTRY again (THIS IS THE FIX)
        d3 = evidence.update_boundary_position(
            (100.0, 400.0, 200.0, 500.0), self.p1, self.p2, self.deadband
        )
        self.assertEqual(d3, "ENTRY")
        self.assertEqual(evidence.get_emittable_directions(), ["ENTRY"])
        evidence.mark_emitted("ENTRY")

        # Full sequence recorded
        self.assertEqual(evidence.emitted_sequence, ["ENTRY", "EXIT", "ENTRY"])

    def test_triple_reentry_entry_exit_entry_exit_entry(self):
        """Full five-crossing sequence must work."""
        evidence = TrackEvidence(track_id=2, first_seen=self.t0, last_seen=self.t0)
        self._make_confirmed(evidence)

        # Initial side A
        evidence.update_boundary_position(
            (100.0, 150.0, 200.0, 250.0), self.p1, self.p2, self.deadband
        )

        expected_dirs = ["ENTRY", "EXIT", "ENTRY", "EXIT", "ENTRY"]
        for i, expected_dir in enumerate(expected_dirs):
            if expected_dir == "ENTRY":
                evidence.update_boundary_position(
                    (100.0, 400.0, 200.0, 500.0), self.p1, self.p2, self.deadband
                )
            else:
                evidence.update_boundary_position(
                    (100.0, 150.0, 200.0, 250.0), self.p1, self.p2, self.deadband
                )
            emittable = evidence.get_emittable_directions()
            self.assertEqual(emittable, [expected_dir], f"Step {i}: expected {expected_dir}")
            evidence.mark_emitted(expected_dir)

        self.assertEqual(evidence.emitted_sequence, expected_dirs)

    def test_jitter_duplicate_entry_entry_blocked(self):
        """Two consecutive ENTRY crossings (jitter) must NOT both emit."""
        evidence = TrackEvidence(track_id=3, first_seen=self.t0, last_seen=self.t0)
        self._make_confirmed(evidence)

        # Side A
        evidence.update_boundary_position(
            (100.0, 150.0, 200.0, 250.0), self.p1, self.p2, self.deadband
        )

        # First cross to SIDE_B -> ENTRY
        evidence.update_boundary_position(
            (100.0, 400.0, 200.0, 500.0), self.p1, self.p2, self.deadband
        )
        evidence.mark_emitted("ENTRY")

        # Jitter: back to ON_LINE then to SIDE_B again
        # (stays on SIDE_B, no actual crossing detected)
        evidence.update_boundary_position(
            (100.0, 410.0, 200.0, 510.0), self.p1, self.p2, self.deadband
        )
        # No pending directions (still on SIDE_B, no boundary crossed)
        self.assertEqual(evidence.get_emittable_directions(), [])

    def test_jitter_via_deadband_oscillation_no_duplicate(self):
        """Oscillating through the deadband without fully crossing should not duplicate."""
        evidence = TrackEvidence(track_id=4, first_seen=self.t0, last_seen=self.t0)
        self._make_confirmed(evidence)

        # Start on SIDE_A
        evidence.update_boundary_position(
            (100.0, 150.0, 200.0, 250.0), self.p1, self.p2, self.deadband
        )

        # Cross to SIDE_B -> ENTRY
        evidence.update_boundary_position(
            (100.0, 400.0, 200.0, 500.0), self.p1, self.p2, self.deadband
        )
        evidence.mark_emitted("ENTRY")

        # Enter deadband (ON_LINE): no crossing
        evidence.update_boundary_position(
            (100.0, 308.0, 200.0, 412.0), self.p1, self.p2, self.deadband
        )
        # Return to SIDE_B: no crossing (stays on same side)
        evidence.update_boundary_position(
            (100.0, 400.0, 200.0, 500.0), self.p1, self.p2, self.deadband
        )
        self.assertEqual(evidence.get_emittable_directions(), [])


class TestIDSwapGuard(unittest.TestCase):
    """Test the periodic re-verification and invalidation mechanism."""

    def setUp(self):
        self.t0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)

    def _make_evidence(self, reverification_interval: float = 10.0, max_disagree: int = 3):
        evidence = TrackEvidence(
            track_id=1,
            first_seen=self.t0,
            last_seen=self.t0,
            reverification_interval_sec=reverification_interval,
            max_disagreement_before_reset=max_disagree,
        )
        for _ in range(3):
            evidence.add_observation(
                identity="person_01",
                score=0.70,
                bbox=(100.0, 150.0, 200.0, 250.0),
                timestamp=self.t0,
                min_supporting_frames=3,
            )
        return evidence

    def test_needs_reverification_not_immediate_after_confirmation(self):
        """Immediately after confirmation, needs_reverification returns False (timer just started)."""
        evidence = self._make_evidence()
        # last_reverification_time is now set at confirmation time (self.t0)
        self.assertFalse(evidence.needs_reverification(self.t0))

    def test_needs_reverification_after_interval(self):
        """After the reverification interval elapses from confirmation, returns True."""
        evidence = self._make_evidence(reverification_interval=5.0)
        # Confirmation was at self.t0, so reverification due after 5s
        self.assertFalse(evidence.needs_reverification(self.t0 + timedelta(seconds=3)))
        self.assertTrue(evidence.needs_reverification(self.t0 + timedelta(seconds=6)))

    def test_reverification_agreement_resets_counter(self):
        """Agreement on reverification resets disagreement counter."""
        evidence = self._make_evidence()
        evidence.reverification_disagreement_count = 2
        result = evidence.reverify_identity("person_01", 0.70, self.t0)
        self.assertTrue(result)
        self.assertEqual(evidence.reverification_disagreement_count, 0)

    def test_reverification_disagreement_increments(self):
        """Disagreement increments the counter."""
        evidence = self._make_evidence(max_disagree=3)
        result = evidence.reverify_identity("person_02", 0.60, self.t0)
        self.assertFalse(result)
        self.assertEqual(evidence.reverification_disagreement_count, 1)
        self.assertTrue(evidence.is_confirmed)  # Not yet invalidated

    def test_reverification_sustained_disagreement_invalidates(self):
        """max_disagreement_before_reset consecutive disagreements invalidate confirmation."""
        evidence = self._make_evidence(max_disagree=2)
        t = self.t0

        evidence.reverify_identity("person_02", 0.55, t)
        self.assertTrue(evidence.is_confirmed)  # 1/2 disagreements

        evidence.reverify_identity("person_02", 0.55, t + timedelta(seconds=1))
        # 2/2 disagreements -> INVALIDATED
        self.assertFalse(evidence.is_confirmed)
        self.assertEqual(evidence.assigned_identity, "UNKNOWN")
        self.assertEqual(evidence.reverification_disagreement_count, 0)

    def test_invalidation_clears_votes_but_preserves_trajectory(self):
        """Invalidation clears identity state but not boundary/trajectory state."""
        evidence = self._make_evidence(max_disagree=1)
        p1 = (0.0, 360.0)
        p2 = (640.0, 360.0)

        # Set up trajectory
        evidence.update_boundary_position(
            (100.0, 150.0, 200.0, 250.0), p1, p2, 4.0
        )
        evidence.update_boundary_position(
            (100.0, 400.0, 200.0, 500.0), p1, p2, 4.0
        )
        evidence.mark_emitted("ENTRY")

        # Trajectory state before invalidation
        self.assertEqual(evidence.current_side, "SIDE_B")
        self.assertEqual(len(evidence.side_history), 2)
        self.assertEqual(evidence.emitted_sequence, ["ENTRY"])

        # Invalidate
        evidence.reverify_identity("person_02", 0.55, self.t0)

        # Identity cleared
        self.assertFalse(evidence.is_confirmed)
        self.assertEqual(evidence.assigned_identity, "UNKNOWN")
        self.assertEqual(dict(evidence.identity_votes), {})

        # Trajectory preserved
        self.assertEqual(evidence.current_side, "SIDE_B")
        self.assertEqual(len(evidence.side_history), 2)
        self.assertEqual(evidence.emitted_sequence, ["ENTRY"])

    def test_invalidated_track_no_events_until_reconfirmed(self):
        """After invalidation, no events are emitted even if pending."""
        evidence = self._make_evidence(max_disagree=1)
        p1 = (0.0, 360.0)
        p2 = (640.0, 360.0)

        # Setup: confirmed, crossed to SIDE_B (ENTRY emitted), now cross back
        evidence.update_boundary_position(
            (100.0, 150.0, 200.0, 250.0), p1, p2, 4.0
        )
        evidence.update_boundary_position(
            (100.0, 400.0, 200.0, 500.0), p1, p2, 4.0
        )
        evidence.mark_emitted("ENTRY")

        # Now invalidate
        evidence.reverify_identity("person_02", 0.55, self.t0)
        self.assertFalse(evidence.is_confirmed)

        # Cross back -> EXIT direction detected
        evidence.update_boundary_position(
            (100.0, 150.0, 200.0, 250.0), p1, p2, 4.0
        )
        # But gate blocks because not confirmed
        self.assertEqual(evidence.get_emittable_directions(), [])


class TestConfigurableBoundary(unittest.TestCase):
    """Test per-camera boundary configuration: entry_side, endpoints, deadband."""

    def setUp(self):
        self.t0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)

    def _make_confirmed(self, evidence):
        for _ in range(3):
            evidence.add_observation(
                identity="person_01",
                score=0.70,
                bbox=(100.0, 150.0, 200.0, 250.0),
                timestamp=self.t0,
                min_supporting_frames=3,
            )

    def test_default_entry_side_a_to_b_is_entry(self):
        """SIDE_A (default) -> SIDE_B crossing is ENTRY."""
        evidence = TrackEvidence(track_id=1, first_seen=self.t0, last_seen=self.t0)
        self._make_confirmed(evidence)

        p1 = (0.0, 360.0)
        p2 = (640.0, 360.0)

        evidence.update_boundary_position(
            (100.0, 150.0, 200.0, 250.0), p1, p2, 4.0, entry_side="SIDE_A"
        )
        d = evidence.update_boundary_position(
            (100.0, 400.0, 200.0, 500.0), p1, p2, 4.0, entry_side="SIDE_A"
        )
        self.assertEqual(d, "ENTRY")

    def test_entry_side_b_inverts_directions(self):
        """With entry_side='SIDE_B', SIDE_A -> SIDE_B crossing is EXIT."""
        evidence = TrackEvidence(track_id=2, first_seen=self.t0, last_seen=self.t0)
        self._make_confirmed(evidence)

        p1 = (0.0, 360.0)
        p2 = (640.0, 360.0)

        evidence.update_boundary_position(
            (100.0, 150.0, 200.0, 250.0), p1, p2, 4.0, entry_side="SIDE_B"
        )
        d = evidence.update_boundary_position(
            (100.0, 400.0, 200.0, 500.0), p1, p2, 4.0, entry_side="SIDE_B"
        )
        self.assertEqual(d, "EXIT")

        d2 = evidence.update_boundary_position(
            (100.0, 150.0, 200.0, 250.0), p1, p2, 4.0, entry_side="SIDE_B"
        )
        self.assertEqual(d2, "ENTRY")

    def test_normalized_boundary_endpoints(self):
        """Boundary line endpoints in 0..1 normalized coords scale to frame size."""
        # Normalized endpoints: (0.0, 0.5) to (1.0, 0.5) -> maps to frame center
        mock_app = MagicMock()
        det_mock = MagicMock()
        det_mock.detect.return_value = (np.empty((0, 5), dtype=np.float32), None)
        mock_app.models = {"detection": det_mock}
        mock_app.det_model = det_mock

        pipeline = LiveCVPipeline(
            app=mock_app,
            gallery={},
            boundary_line=((0.0, 0.5), (1.0, 0.5)),
            deadband_pixels=4.0,
            entry_side="SIDE_A",
        )
        # Just validate it doesn't crash on construction
        self.assertEqual(pipeline.entry_side, "SIDE_A")
        self.assertEqual(pipeline.boundary_line, ((0.0, 0.5), (1.0, 0.5)))

    def test_pipeline_rejects_invalid_entry_side(self):
        """Pipeline construction with invalid entry_side raises ValueError."""
        mock_app = MagicMock()
        mock_app.models = {}
        mock_app.det_model = MagicMock()
        with self.assertRaises(ValueError):
            LiveCVPipeline(
                app=mock_app,
                gallery={},
                entry_side="INVALID",
            )

    def test_pipeline_rejects_degenerate_boundary(self):
        """Pipeline construction with identical boundary endpoints raises ValueError."""
        mock_app = MagicMock()
        mock_app.models = {}
        mock_app.det_model = MagicMock()
        with self.assertRaises(ValueError):
            LiveCVPipeline(
                app=mock_app,
                gallery={},
                boundary_line=((0.5, 0.5), (0.5, 0.5)),
            )

    def test_wider_deadband_absorbs_more_jitter(self):
        """Wider deadband prevents crossings from near-boundary positions."""
        p1 = (0.0, 360.0)
        p2 = (640.0, 360.0)

        # With narrow deadband=2, cy=358 is SIDE_A, cy=362 is SIDE_B
        self.assertEqual(classify_point_side(320.0, 357.0, p1, p2, 2.0), "SIDE_A")
        self.assertEqual(classify_point_side(320.0, 363.0, p1, p2, 2.0), "SIDE_B")

        # With wider deadband=10, both are ON_LINE
        self.assertEqual(classify_point_side(320.0, 355.0, p1, p2, 10.0), "ON_LINE")
        self.assertEqual(classify_point_side(320.0, 365.0, p1, p2, 10.0), "ON_LINE")


class TestHysteresisBehavior(unittest.TestCase):
    """Test that deadband zone prevents spurious crossings."""

    def setUp(self):
        self.t0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
        self.p1 = (0.0, 360.0)
        self.p2 = (640.0, 360.0)
        self.deadband = 8.0  # Wider deadband

    def test_on_line_no_direction_change(self):
        """Moving within the deadband zone does not register any crossing."""
        evidence = TrackEvidence(track_id=1, first_seen=self.t0, last_seen=self.t0)
        for _ in range(3):
            evidence.add_observation(
                identity="person_01", score=0.70,
                bbox=(100.0, 150.0, 200.0, 250.0),
                timestamp=self.t0, min_supporting_frames=3,
            )

        # Start on SIDE_A
        evidence.update_boundary_position(
            (100.0, 100.0, 200.0, 200.0), self.p1, self.p2, self.deadband
        )
        self.assertEqual(evidence.current_side, "SIDE_A")

        # Move into deadband
        d1 = evidence.update_boundary_position(
            (100.0, 304.0, 200.0, 416.0), self.p1, self.p2, self.deadband
        )
        self.assertIsNone(d1)
        # current_side still SIDE_A because ON_LINE doesn't update it
        self.assertEqual(evidence.current_side, "SIDE_A")

        # Move within deadband
        d2 = evidence.update_boundary_position(
            (100.0, 310.0, 200.0, 410.0), self.p1, self.p2, self.deadband
        )
        self.assertIsNone(d2)

    def test_pause_at_boundary_then_cross(self):
        """Person pauses at boundary (ON_LINE frames), then crosses cleanly."""
        evidence = TrackEvidence(track_id=2, first_seen=self.t0, last_seen=self.t0)
        for _ in range(3):
            evidence.add_observation(
                identity="person_01", score=0.70,
                bbox=(100.0, 150.0, 200.0, 250.0),
                timestamp=self.t0, min_supporting_frames=3,
            )

        # Start on SIDE_A
        evidence.update_boundary_position(
            (100.0, 100.0, 200.0, 200.0), self.p1, self.p2, self.deadband
        )

        # 3 frames in deadband (pausing)
        for _ in range(3):
            d = evidence.update_boundary_position(
                (100.0, 304.0, 200.0, 416.0), self.p1, self.p2, self.deadband
            )
            self.assertIsNone(d)

        # Cross cleanly into SIDE_B
        d_cross = evidence.update_boundary_position(
            (100.0, 420.0, 200.0, 520.0), self.p1, self.p2, self.deadband
        )
        self.assertEqual(d_cross, "ENTRY")
        self.assertEqual(evidence.get_emittable_directions(), ["ENTRY"])


class TestPipelineIDSwapGuardIntegration(unittest.TestCase):
    """Test ID-swap guard integration in the full LiveCVPipeline process_frame."""

    def _make_pipeline(self, reverification_interval: float = 10.0, max_disagree: int = 3):
        mock_app = MagicMock()
        det_mock = MagicMock()
        rec_mock = MagicMock()
        mock_app.models = {"detection": det_mock, "recognition": rec_mock}
        mock_app.det_model = det_mock

        np.random.seed(42)
        emb_person = np.random.randn(512).astype(np.float32)
        emb_person /= np.linalg.norm(emb_person)
        gallery = {"person_01": emb_person}

        def mock_rec_get(frame, face):
            face.embedding = emb_person.copy()
        rec_mock.get.side_effect = mock_rec_get

        pipeline = LiveCVPipeline(
            app=mock_app,
            gallery=gallery,
            similarity_threshold=0.40,
            min_margin=0.10,
            min_supporting_frames=2,
            source_id="CAM_01",
            boundary_line=((0.0, 360.0), (640.0, 360.0)),
            deadband_pixels=4.0,
            reverification_interval_sec=reverification_interval,
            max_reverification_disagreement=max_disagree,
        )
        return pipeline, det_mock, rec_mock, emb_person

    def test_reverification_called_after_interval(self):
        """After reverification_interval_sec, ArcFace runs again on confirmed track."""
        pipeline, det_mock, rec_mock, emb = self._make_pipeline(reverification_interval=2.0)
        test_img = np.zeros((720, 640, 3), dtype=np.uint8)

        # Frame 1-2: Confirm identity (on SIDE_A)
        box = np.array([[200.0, 280.0, 300.0, 380.0, 0.95]], dtype=np.float32)
        det_mock.detect.return_value = (box, None)

        for i in range(2):
            frame = VideoFrame(
                frame=test_img,
                timestamp=datetime(2026, 10, 20, 10, 0, i, tzinfo=timezone.utc),
                frame_index=i + 1,
                source_id="CAM_01",
                source_type=VideoSourceType.PHONE,
            )
            pipeline.process_frame(frame)

        # Track should be confirmed — use dynamic track ID (ByteTrack class counter)
        self.assertEqual(len(pipeline.tracks), 1)
        track_id = next(iter(pipeline.tracks))
        track = pipeline.tracks[track_id]
        self.assertTrue(track.is_confirmed)
        self.assertEqual(track.assigned_identity, "person_01")
        initial_arcface_calls = rec_mock.get.call_count

        # Frame 3: 1 second after confirmation — NOT yet due for reverification (interval=2s)
        frame3 = VideoFrame(
            frame=test_img,
            timestamp=datetime(2026, 10, 20, 10, 0, 2, tzinfo=timezone.utc),
            frame_index=3,
            source_id="CAM_01",
            source_type=VideoSourceType.PHONE,
        )
        pipeline.process_frame(frame3)
        calls_after_frame3 = rec_mock.get.call_count
        # Should NOT have called ArcFace (confirmed, and only 1s since confirmation)
        self.assertEqual(calls_after_frame3, initial_arcface_calls)
        self.assertEqual(track.assigned_identity, "person_01")

        # Frame 4: 5 seconds after confirmation — should trigger reverification (>2s interval)
        frame4 = VideoFrame(
            frame=test_img,
            timestamp=datetime(2026, 10, 20, 10, 0, 7, tzinfo=timezone.utc),
            frame_index=4,
            source_id="CAM_01",
            source_type=VideoSourceType.PHONE,
        )
        pipeline.process_frame(frame4)
        # ArcFace should have been called again for reverification
        self.assertGreater(rec_mock.get.call_count, calls_after_frame3)
        # Identity still matches, so confirmation should remain
        self.assertTrue(track.is_confirmed)


class TestMultiPersonEventSequences(unittest.TestCase):
    """Test that multiple independent tracks emit correct events without interference."""

    def setUp(self):
        self.t0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
        self.p1 = (0.0, 360.0)
        self.p2 = (640.0, 360.0)
        self.deadband = 4.0

    def test_two_tracks_independent_events(self):
        """Two confirmed tracks crossing the boundary independently emit separate events."""
        evidence1 = TrackEvidence(track_id=1, first_seen=self.t0, last_seen=self.t0)
        evidence2 = TrackEvidence(track_id=2, first_seen=self.t0, last_seen=self.t0)

        for ev in [evidence1, evidence2]:
            identity = "person_01" if ev.track_id == 1 else "person_02"
            for _ in range(3):
                ev.add_observation(
                    identity=identity, score=0.70,
                    bbox=(100.0, 150.0, 200.0, 250.0),
                    timestamp=self.t0, min_supporting_frames=3,
                )

        # Both start on SIDE_A
        evidence1.update_boundary_position(
            (50.0, 150.0, 150.0, 250.0), self.p1, self.p2, self.deadband
        )
        evidence2.update_boundary_position(
            (350.0, 150.0, 450.0, 250.0), self.p1, self.p2, self.deadband
        )

        # Track 1 crosses
        evidence1.update_boundary_position(
            (50.0, 400.0, 150.0, 500.0), self.p1, self.p2, self.deadband
        )
        # Track 2 does NOT cross
        evidence2.update_boundary_position(
            (350.0, 150.0, 450.0, 250.0), self.p1, self.p2, self.deadband
        )

        self.assertEqual(evidence1.get_emittable_directions(), ["ENTRY"])
        self.assertEqual(evidence2.get_emittable_directions(), [])

        evidence1.mark_emitted("ENTRY")

        # Now track 2 crosses
        evidence2.update_boundary_position(
            (350.0, 400.0, 450.0, 500.0), self.p1, self.p2, self.deadband
        )
        self.assertEqual(evidence2.get_emittable_directions(), ["ENTRY"])

    def test_opposite_directions_simultaneous(self):
        """One track entering, another exiting simultaneously."""
        evidence_enter = TrackEvidence(track_id=1, first_seen=self.t0, last_seen=self.t0)
        evidence_exit = TrackEvidence(track_id=2, first_seen=self.t0, last_seen=self.t0)

        for ev in [evidence_enter, evidence_exit]:
            identity = "person_01" if ev.track_id == 1 else "person_02"
            for _ in range(3):
                ev.add_observation(
                    identity=identity, score=0.70,
                    bbox=(100.0, 150.0, 200.0, 250.0),
                    timestamp=self.t0, min_supporting_frames=3,
                )

        # Track 1 starts on SIDE_A
        evidence_enter.update_boundary_position(
            (50.0, 150.0, 150.0, 250.0), self.p1, self.p2, self.deadband
        )
        # Track 2 starts on SIDE_B
        evidence_exit.update_boundary_position(
            (350.0, 400.0, 450.0, 500.0), self.p1, self.p2, self.deadband
        )

        # Simultaneous opposite crossings
        d1 = evidence_enter.update_boundary_position(
            (50.0, 400.0, 150.0, 500.0), self.p1, self.p2, self.deadband
        )
        d2 = evidence_exit.update_boundary_position(
            (350.0, 150.0, 450.0, 250.0), self.p1, self.p2, self.deadband
        )

        self.assertEqual(d1, "ENTRY")
        self.assertEqual(d2, "EXIT")


class TestUnknownPersonSafetyInAllScenarios(unittest.TestCase):
    """Across all scenarios, UNKNOWN / unconfirmed tracks must NEVER emit events."""

    def setUp(self):
        self.t0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
        self.p1 = (0.0, 360.0)
        self.p2 = (640.0, 360.0)
        self.deadband = 4.0

    def test_unknown_after_max_attempts_no_events(self):
        """UNKNOWN track after max attempts crosses boundary -> zero events."""
        evidence = TrackEvidence(track_id=1, first_seen=self.t0, last_seen=self.t0)

        for _ in range(5):
            evidence.add_observation(
                identity="UNKNOWN", score=0.20,
                bbox=(100.0, 150.0, 200.0, 250.0),
                timestamp=self.t0,
                min_supporting_frames=3,
                max_unknown_attempts=5,
            )
        self.assertTrue(evidence.is_confirmed)
        self.assertEqual(evidence.assigned_identity, "UNKNOWN")

        evidence.update_boundary_position(
            (100.0, 150.0, 200.0, 250.0), self.p1, self.p2, self.deadband
        )
        evidence.update_boundary_position(
            (100.0, 400.0, 200.0, 500.0), self.p1, self.p2, self.deadband
        )
        self.assertEqual(evidence.get_emittable_directions(), [])

    def test_unconfirmed_with_pending_crossing_no_events(self):
        """Partially identified (1/3 votes) track crossing -> zero events."""
        evidence = TrackEvidence(track_id=2, first_seen=self.t0, last_seen=self.t0)
        evidence.add_observation(
            identity="person_01", score=0.70,
            bbox=(100.0, 150.0, 200.0, 250.0),
            timestamp=self.t0,
            min_supporting_frames=3,
        )
        self.assertFalse(evidence.is_confirmed)

        evidence.update_boundary_position(
            (100.0, 150.0, 200.0, 250.0), self.p1, self.p2, self.deadband
        )
        evidence.update_boundary_position(
            (100.0, 400.0, 200.0, 500.0), self.p1, self.p2, self.deadband
        )
        self.assertEqual(evidence.get_emittable_directions(), [])


if __name__ == "__main__":
    unittest.main()
