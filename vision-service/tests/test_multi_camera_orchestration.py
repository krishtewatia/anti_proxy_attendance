"""Test suite for Multi-Camera Orchestration, Directional Roles (ENTRY/EXIT/BOTH), and Telemetry."""

from datetime import datetime, timezone
import os
from pathlib import Path
import time
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from camera.base import VideoFrame, VideoSourceType
from camera.rtsp_source import RTSPVideoSource
from camera_worker import CameraConfig, CameraWorker, MultiCameraRunner
from events.event_dispatcher import EventDispatcher
from pipeline.live_cv_pipeline import LiveCVPipeline


def _create_mock_face_app(emb_person: np.ndarray):
    mock_app = MagicMock()
    det_mock = MagicMock()
    rec_mock = MagicMock()

    def mock_rec_get(frame, face):
        face.embedding = emb_person.copy()

    rec_mock.get.side_effect = mock_rec_get
    mock_app.models = {
        "detection": det_mock,
        "recognition": rec_mock,
    }
    mock_app.det_model = det_mock
    return mock_app


class TestCameraRoleDirectionalEnforcement(unittest.TestCase):
    """Test directional filtering in LiveCVPipeline for ENTRY-only and EXIT-only cameras."""

    def setUp(self):
        np.random.seed(42)
        self.emb_person = np.random.randn(512).astype(np.float32)
        self.emb_person /= np.linalg.norm(self.emb_person)
        self.gallery = {"student_01": self.emb_person}
        self.mock_app = _create_mock_face_app(self.emb_person)

    def _simulate_entry(self, pipeline):
        """Simulate a confirmed face crossing from SIDE_A (cy=330) to SIDE_B (cy=380) producing ENTRY."""
        # Frame 1: cy = 330 (SIDE_A)
        self.mock_app.models["detection"].detect.return_value = (
            np.array([[200.0, 280.0, 300.0, 380.0, 0.95]], dtype=np.float32),
            None,
        )
        pipeline.process_frame(VideoFrame(
            frame=np.zeros((720, 640, 3), dtype=np.uint8),
            timestamp=datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc),
            frame_index=1,
            source_id="CAM_TEST",
            source_type=VideoSourceType.FILE,
        ))

        # Frame 2: cy = 345 (SIDE_A, 2nd vote -> Confirmed)
        self.mock_app.models["detection"].detect.return_value = (
            np.array([[200.0, 295.0, 300.0, 395.0, 0.95]], dtype=np.float32),
            None,
        )
        pipeline.process_frame(VideoFrame(
            frame=np.zeros((720, 640, 3), dtype=np.uint8),
            timestamp=datetime(2026, 10, 1, 9, 0, 1, tzinfo=timezone.utc),
            frame_index=2,
            source_id="CAM_TEST",
            source_type=VideoSourceType.FILE,
        ))

        # Frame 3: cy = 360 (deadband)
        self.mock_app.models["detection"].detect.return_value = (
            np.array([[200.0, 310.0, 300.0, 410.0, 0.95]], dtype=np.float32),
            None,
        )
        pipeline.process_frame(VideoFrame(
            frame=np.zeros((720, 640, 3), dtype=np.uint8),
            timestamp=datetime(2026, 10, 1, 9, 0, 2, tzinfo=timezone.utc),
            frame_index=3,
            source_id="CAM_TEST",
            source_type=VideoSourceType.FILE,
        ))

        # Frame 4: cy = 380 (SIDE_B -> ENTRY)
        self.mock_app.models["detection"].detect.return_value = (
            np.array([[200.0, 330.0, 300.0, 430.0, 0.95]], dtype=np.float32),
            None,
        )
        return pipeline.process_frame(VideoFrame(
            frame=np.zeros((720, 640, 3), dtype=np.uint8),
            timestamp=datetime(2026, 10, 1, 9, 0, 3, tzinfo=timezone.utc),
            frame_index=4,
            source_id="CAM_TEST",
            source_type=VideoSourceType.FILE,
        ))

    def _simulate_exit(self, pipeline):
        """Simulate the confirmed face crossing back from SIDE_B to SIDE_A (cy=340) producing EXIT."""
        self.mock_app.models["detection"].detect.return_value = (
            np.array([[200.0, 290.0, 300.0, 390.0, 0.95]], dtype=np.float32),
            None,
        )
        return pipeline.process_frame(VideoFrame(
            frame=np.zeros((720, 640, 3), dtype=np.uint8),
            timestamp=datetime(2026, 10, 1, 9, 0, 4, tzinfo=timezone.utc),
            frame_index=5,
            source_id="CAM_TEST",
            source_type=VideoSourceType.FILE,
        ))

    def test_entry_only_camera_allows_entry_and_blocks_exit(self):
        """ENTRY-only camera must dispatch ENTRY events but drop EXIT events."""
        mock_dispatcher = MagicMock(spec=EventDispatcher)
        mock_dispatcher.send_event.return_value = {"status": "accepted"}

        pipeline = LiveCVPipeline(
            app=self.mock_app,
            gallery=self.gallery,
            min_supporting_frames=2,
            camera_role="ENTRY",
            camera_id="CAM_ENTRY_ONLY",
            boundary_line=((0.0, 360.0), (640.0, 360.0)),
            deadband_pixels=4.0,
            event_dispatcher=mock_dispatcher,
            enable_kinematic_anti_spoof=False,
        )

        # 1. Simulate ENTRY
        self._simulate_entry(pipeline)
        self.assertEqual(mock_dispatcher.send_event.call_count, 1)
        dispatched_event = mock_dispatcher.send_event.call_args[0][0]
        self.assertEqual(dispatched_event["direction"], "ENTRY")
        self.assertEqual(dispatched_event["identity"], "student_01")

        mock_dispatcher.reset_mock()

        # 2. Simulate reverse crossing (EXIT)
        self._simulate_exit(pipeline)

        # EXIT event must be DROPPED because camera role is ENTRY
        mock_dispatcher.send_event.assert_not_called()

    def test_exit_only_camera_allows_exit_and_blocks_entry(self):
        """EXIT-only camera must drop ENTRY events and only dispatch EXIT events."""
        mock_dispatcher = MagicMock(spec=EventDispatcher)
        mock_dispatcher.send_event.return_value = {"status": "accepted"}

        pipeline = LiveCVPipeline(
            app=self.mock_app,
            gallery=self.gallery,
            min_supporting_frames=2,
            camera_role="EXIT",
            camera_id="CAM_EXIT_ONLY",
            boundary_line=((0.0, 360.0), (640.0, 360.0)),
            deadband_pixels=4.0,
            event_dispatcher=mock_dispatcher,
            enable_kinematic_anti_spoof=False,
        )

        # 1. Simulate crossing from top (SIDE_A) to bottom (SIDE_B) -> produces ENTRY
        self._simulate_entry(pipeline)

        # ENTRY event must be DROPPED because camera role is EXIT
        mock_dispatcher.send_event.assert_not_called()

        # 2. Simulate crossing back to SIDE_A -> produces EXIT
        self._simulate_exit(pipeline)

        # EXIT event must be DISPATCHED
        self.assertEqual(mock_dispatcher.send_event.call_count, 1)
        dispatched_event = mock_dispatcher.send_event.call_args[0][0]
        self.assertEqual(dispatched_event["direction"], "EXIT")

    def test_both_camera_allows_both_directions(self):
        """Bidirectional BOTH camera permits both ENTRY and EXIT events."""
        mock_dispatcher = MagicMock(spec=EventDispatcher)
        mock_dispatcher.send_event.return_value = {"status": "accepted"}

        pipeline = LiveCVPipeline(
            app=self.mock_app,
            gallery=self.gallery,
            min_supporting_frames=2,
            camera_role="BOTH",
            camera_id="CAM_BOTH_DOOR",
            boundary_line=((0.0, 360.0), (640.0, 360.0)),
            deadband_pixels=4.0,
            event_dispatcher=mock_dispatcher,
            enable_kinematic_anti_spoof=False,
        )

        # ENTRY crossing
        self._simulate_entry(pipeline)
        self.assertEqual(mock_dispatcher.send_event.call_count, 1)
        self.assertEqual(mock_dispatcher.send_event.call_args[0][0]["direction"], "ENTRY")

        mock_dispatcher.reset_mock()

        # EXIT crossing
        self._simulate_exit(pipeline)
        self.assertEqual(mock_dispatcher.send_event.call_count, 1)
        self.assertEqual(mock_dispatcher.send_event.call_args[0][0]["direction"], "EXIT")


class TestMultiCameraRunner(unittest.TestCase):
    """Test MultiCameraRunner configuration, heartbeat telemetry, and 1 vs 2 benchmark."""

    def setUp(self):
        np.random.seed(42)
        self.emb_person = np.random.randn(512).astype(np.float32)
        self.gallery = {"person_01": self.emb_person}
        self.mock_app = _create_mock_face_app(self.emb_person)

    def test_camera_config_from_dict_and_validation(self):
        data = {
            "camera_id": "CAM_ROOM_201_ENTRANCE",
            "classroom_id": "ROOM_201",
            "role": "ENTRY",
            "source_type": "RTSP",
            "source_uri": "rtsp://10.0.0.1:554/live",
            "boundary_line": [[0.0, 0.5], [1.0, 0.5]],
            "entry_side": "SIDE_A",
            "target_fps": 10.0,
            "enabled": True,
        }
        cfg = CameraConfig.from_dict(data)
        self.assertEqual(cfg.camera_id, "CAM_ROOM_201_ENTRANCE")
        self.assertEqual(cfg.role, "ENTRY")
        self.assertEqual(cfg.boundary_line, ((0.0, 0.5), (1.0, 0.5)))
        self.assertEqual(cfg.target_fps, 10.0)

    @patch("camera_worker.create_video_source")
    def test_worker_heartbeat_dispatch(self, mock_create_source):
        mock_source = MagicMock()
        mock_source.status = "CONNECTED"
        mock_source.fps = 15.0
        mock_source.dropped_frames = 0
        mock_source.read.return_value = None
        mock_create_source.return_value = mock_source

        mock_dispatcher = MagicMock(spec=EventDispatcher)

        config = CameraConfig(
            camera_id="CAM_HEARTBEAT_TEST",
            classroom_id="ROOM_101",
            role="BOTH",
            source_type="RTSP",
            source_uri="rtsp://localhost/test",
            heartbeat_interval_sec=0.05,
        )

        worker = CameraWorker(
            config=config,
            app=self.mock_app,
            gallery=self.gallery,
            dispatcher=mock_dispatcher,
        )

        worker.start()
        try:
            time.sleep(0.12)
            self.assertTrue(worker.is_alive())
            # Verify heartbeat was dispatched
            self.assertGreaterEqual(mock_dispatcher.send_camera_heartbeat.call_count, 1)
            hb_call = mock_dispatcher.send_camera_heartbeat.call_args[1]
            self.assertEqual(hb_call["camera_id"], "CAM_HEARTBEAT_TEST")
            self.assertEqual(hb_call["state"], "CONNECTED")
        finally:
            worker.stop()
            self.assertFalse(worker.is_alive())

    @patch("camera_worker.create_video_source")
    def test_multi_camera_runner_orchestration_and_benchmark(self, mock_create_source):
        """Test MultiCameraRunner runs 1 vs 2 cameras and measures benchmark metrics."""
        mock_source = MagicMock()
        mock_source.status = "CONNECTED"
        mock_source.fps = 20.0
        mock_source.dropped_frames = 0
        dummy_frame = VideoFrame(
            frame=np.zeros((100, 100, 3), dtype=np.uint8),
            timestamp=datetime.now(timezone.utc),
            source_id="CAM_TEST",
            frame_index=1,
            source_type=VideoSourceType.FILE,
        )
        mock_source.read.return_value = dummy_frame
        mock_create_source.return_value = mock_source

        cams = [
            {
                "camera_id": "CAM_BENCH_1",
                "classroom_id": "ROOM_101",
                "role": "ENTRY",
                "source_type": "FILE",
                "source_uri": "dummy1.mp4",
                "target_fps": 30.0,
            },
            {
                "camera_id": "CAM_BENCH_2",
                "classroom_id": "ROOM_101",
                "role": "EXIT",
                "source_type": "FILE",
                "source_uri": "dummy2.mp4",
                "target_fps": 30.0,
            },
        ]

        # Run benchmark
        benchmark_results = MultiCameraRunner.benchmark(
            camera_configs=cams,
            app=self.mock_app,
            gallery=self.gallery,
            duration_sec=0.2,
        )

        self.assertIn("1_cameras", benchmark_results)
        self.assertIn("2_cameras", benchmark_results)
        self.assertIn("cpu_percent", benchmark_results["1_cameras"])
        self.assertIn("aggregate_fps", benchmark_results["1_cameras"])
        self.assertIn("aggregate_fps", benchmark_results["2_cameras"])


if __name__ == "__main__":
    unittest.main()
