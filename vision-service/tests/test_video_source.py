"""Unit tests for the unified Video Source Abstraction (Step 2D.1)."""

import os
from datetime import datetime, timezone
from pathlib import Path
import queue
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

# Ensure vision-service root is in sys.path
SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from camera import (
    FileVideoSource,
    PhoneVideoSource,
    RTSPVideoSource,
    VideoFrame,
    VideoSource,
    VideoSourceType,
    WebRTCVideoSource,
    create_video_source,
)


# Real video clips are biometric fixtures kept outside the repository.
VIDEO_FIXTURES_DIR = (
    Path(os.environ.get("VISION_FIXTURES_DIR") or "vision-fixtures-not-configured") / "video_test"
)


def require_clip(test: unittest.TestCase, path: Path) -> None:
    """Skip a test that needs a real clip when the fixtures are not available."""
    if not Path(path).exists():
        test.skipTest("Video fixtures not available: set VISION_FIXTURES_DIR (see README)")


class TestVideoFrameContract(unittest.TestCase):
    """Test the immutable VideoFrame data contract delivered to vision pipelines."""

    def test_video_frame_properties(self):
        dummy_image = np.zeros((480, 640, 3), dtype=np.uint8)
        now = datetime.now(timezone.utc)

        vf = VideoFrame(
            frame=dummy_image,
            timestamp=now,
            source_id="CAM_TEST_01",
            frame_index=0,
            source_type=VideoSourceType.PHONE,
        )

        self.assertEqual(vf.width, 640)
        self.assertEqual(vf.height, 480)
        self.assertEqual(vf.shape, (480, 640, 3))
        self.assertEqual(vf.source_id, "CAM_TEST_01")
        self.assertEqual(vf.source_type, VideoSourceType.PHONE)
        self.assertEqual(vf.frame_index, 0)
        self.assertEqual(vf.timestamp, now)

    def test_video_frame_immutability(self):
        dummy_image = np.zeros((100, 100, 3), dtype=np.uint8)
        vf = VideoFrame(
            frame=dummy_image,
            timestamp=datetime.now(timezone.utc),
            source_id="CAM_TEST",
            frame_index=1,
            source_type=VideoSourceType.FILE,
        )

        with self.assertRaises(AttributeError):
            vf.frame_index = 2  # Frozen dataclass prevents mutation


class TestFileVideoSource(unittest.TestCase):
    """Test FileVideoSource adapter using local test video files."""

    def setUp(self):
        self.video_path = VIDEO_FIXTURES_DIR / "person_1_vid.mp4"
        if not self.video_path.exists():
            # Fallback to any available video in video_test
            candidates = list((VIDEO_FIXTURES_DIR).glob("*.mp4"))
            if candidates:
                self.video_path = candidates[0]

    def test_open_extracts_metadata(self):
        require_clip(self, self.video_path)
        source = FileVideoSource(self.video_path, target_fps=5.0)
        source.open()
        try:
            self.assertTrue(source.is_opened)
            self.assertGreater(source.source_fps, 0)
            self.assertGreater(source.total_frames, 0)
            self.assertGreater(source.duration_seconds, 0)
            self.assertEqual(source.source_type, VideoSourceType.FILE)
        finally:
            source.release()
            self.assertFalse(source.is_opened)

    def test_read_samples_frames_with_monotonic_timestamps(self):
        require_clip(self, self.video_path)
        source = FileVideoSource(self.video_path, target_fps=5.0)
        source.open()
        try:
            frames: list[VideoFrame] = []
            for _ in range(5):
                f = source.read()
                if f is None:
                    break
                frames.append(f)

            self.assertGreaterEqual(len(frames), 2)
            for i, f in enumerate(frames):
                self.assertEqual(f.frame_index, i)
                self.assertEqual(f.source_type, VideoSourceType.FILE)
                self.assertIsInstance(f.frame, np.ndarray)
                if i > 0:
                    self.assertGreater(f.timestamp, frames[i - 1].timestamp)
        finally:
            source.release()

    def test_context_manager_and_streaming(self):
        require_clip(self, self.video_path)
        with FileVideoSource(self.video_path, target_fps=5.0) as source:
            self.assertTrue(source.is_opened)
            frames_read = 0
            for frame in source.stream():
                frames_read += 1
                if frames_read >= 3:
                    break
            self.assertEqual(frames_read, 3)

        self.assertFalse(source.is_opened)

    def test_missing_file_raises_error(self):
        source = FileVideoSource(SERVICE_ROOT / "non_existent.mp4")
        with self.assertRaises(FileNotFoundError):
            source.open()

    def test_read_without_open_raises_runtime_error(self):
        source = FileVideoSource(self.video_path)
        with self.assertRaises(RuntimeError):
            source.read()


class TestPhoneVideoSource(unittest.TestCase):
    """Test PhoneVideoSource / WebRTCVideoSource live streaming adapter."""

    def test_push_and_read_frame(self):
        source = PhoneVideoSource(source_id="PHONE_ROOM_101", read_timeout=0.1)
        source.open()
        try:
            self.assertTrue(source.is_opened)
            self.assertEqual(source.source_type, VideoSourceType.PHONE)

            test_frame = np.ones((240, 320, 3), dtype=np.uint8) * 128
            ts = datetime.now(timezone.utc)
            success = source.push_frame(test_frame, timestamp=ts)
            self.assertTrue(success)

            vf = source.read()
            self.assertIsNotNone(vf)
            self.assertEqual(vf.source_id, "PHONE_ROOM_101")
            self.assertEqual(vf.frame_index, 0)
            self.assertEqual(vf.timestamp, ts)
            self.assertEqual(vf.width, 320)
            self.assertEqual(vf.height, 240)
            np.testing.assert_array_equal(vf.frame, test_frame)
        finally:
            source.release()

    def test_drop_oldest_on_buffer_saturation(self):
        """Ensures stale frames are dropped when consumer is slower than incoming stream."""
        max_buffer = 3
        source = PhoneVideoSource(max_buffer_size=max_buffer, read_timeout=0.05)
        source.open()
        try:
            # Push 5 frames into buffer of size 3
            for i in range(5):
                frame = np.ones((10, 10, 3), dtype=np.uint8) * i
                source.push_frame(frame)

            self.assertEqual(source.dropped_frames, 2)
            self.assertEqual(source.buffer_size, 3)

            # The next frame read should be frame index 2 (frames 0 and 1 dropped)
            vf = source.read()
            self.assertIsNotNone(vf)
            self.assertEqual(vf.frame_index, 2)
            self.assertEqual(vf.frame[0, 0, 0], 2)
        finally:
            source.release()

    def test_empty_buffer_returns_none_on_timeout(self):
        source = PhoneVideoSource(read_timeout=0.05)
        source.open()
        try:
            vf = source.read()
            self.assertIsNone(vf)
        finally:
            source.release()

    def test_webrtc_alias_interchangeable(self):
        """WebRTCVideoSource is fully compatible alias for PhoneVideoSource."""
        source = WebRTCVideoSource(source_id="WEBRTC_FEED")
        self.assertIsInstance(source, PhoneVideoSource)

    def test_concurrent_producer_consumer(self):
        """Verify thread-safety when phone client streams while CV pipeline processes."""
        source = PhoneVideoSource(max_buffer_size=20, read_timeout=0.2)
        source.open()

        produced_count = 15
        consumed_frames: list[VideoFrame] = []

        def producer():
            for i in range(produced_count):
                source.push_frame(np.zeros((50, 50, 3), dtype=np.uint8))
                time.sleep(0.01)

        def consumer():
            while len(consumed_frames) < produced_count:
                frame = source.read()
                if frame is not None:
                    consumed_frames.append(frame)
                else:
                    break

        p_thread = threading.Thread(target=producer)
        c_thread = threading.Thread(target=consumer)

        p_thread.start()
        c_thread.start()

        p_thread.join(timeout=2.0)
        c_thread.join(timeout=2.0)
        source.release()

        self.assertEqual(len(consumed_frames), produced_count)


class TestRTSPVideoSource(unittest.TestCase):
    """Test RTSPVideoSource CCTV / IP camera adapter."""

    @patch("cv2.VideoCapture")
    def test_rtsp_connection_and_reading(self, mock_cv_capture):
        mock_cap_instance = MagicMock()
        mock_cap_instance.isOpened.return_value = True
        dummy_frame = np.ones((720, 1280, 3), dtype=np.uint8)
        mock_cap_instance.read.return_value = (True, dummy_frame)
        mock_cv_capture.return_value = mock_cap_instance

        source = RTSPVideoSource(
            rtsp_url="rtsp://192.168.1.100:554/live",
            source_id="CCTV_GATE_01",
        )
        source.open()
        try:
            self.assertTrue(source.is_opened)
            self.assertEqual(source.source_type, VideoSourceType.RTSP)

            frame = source.read()
            self.assertIsNotNone(frame)
            self.assertEqual(frame.source_id, "CCTV_GATE_01")
            self.assertEqual(frame.width, 1280)
            self.assertEqual(frame.height, 720)
        finally:
            source.release()
            mock_cap_instance.release.assert_called_once()

    @patch("cv2.VideoCapture")
    def test_rtsp_connection_failure_raises(self, mock_cv_capture):
        mock_cap_instance = MagicMock()
        mock_cap_instance.isOpened.return_value = False
        mock_cv_capture.return_value = mock_cap_instance

        source = RTSPVideoSource("rtsp://invalid-camera/live")
        with self.assertRaises(ConnectionError):
            source.open()


class TestFactoryAndPolymorphism(unittest.TestCase):
    """Test the factory helper and cross-source interchangeability."""

    def setUp(self):
        self.video_path = VIDEO_FIXTURES_DIR / "person_1_vid.mp4"

    def test_factory_creates_file_source(self):
        src = create_video_source("FILE", source_uri=self.video_path)
        self.assertIsInstance(src, FileVideoSource)
        self.assertEqual(src.source_type, VideoSourceType.FILE)

    def test_factory_creates_phone_source(self):
        src = create_video_source("PHONE", source_id="PHONE_DEMO")
        self.assertIsInstance(src, PhoneVideoSource)
        self.assertEqual(src.source_type, VideoSourceType.PHONE)

    def test_factory_creates_rtsp_source(self):
        src = create_video_source("RTSP", source_uri="rtsp://localhost:8554/live")
        self.assertIsInstance(src, RTSPVideoSource)
        self.assertEqual(src.source_type, VideoSourceType.RTSP)

    def test_factory_invalid_type_raises(self):
        with self.assertRaises(ValueError):
            create_video_source("UNKNOWN_FORMAT")

    def test_unified_cv_consumer_pipeline_polymorphism(self):
        require_clip(self, self.video_path)
        """Demonstrate that downstream CV pipeline code functions identically

        regardless of whether frames arrive from Phone/WebRTC or Recorded File.
        """

        def mock_vision_pipeline(source: VideoSource, max_frames: int = 3) -> list[dict]:
            """Simulates a downstream CV consumer (detector, tracker, recognizer)."""
            detections = []
            with source as src:
                for vf in src.stream():
                    # Downstream only needs frame, timestamp, and source_id!
                    detections.append({
                        "source_id": vf.source_id,
                        "source_type": vf.source_type.value,
                        "frame_index": vf.frame_index,
                        "resolution": (vf.width, vf.height),
                        "timestamp_iso": vf.timestamp.isoformat(),
                    })
                    if len(detections) >= max_frames:
                        break
            return detections

        # 1. Feed from Recorded File
        file_source = FileVideoSource(self.video_path, source_id="FILE_INPUT", target_fps=5.0)
        file_results = mock_vision_pipeline(file_source, max_frames=2)

        self.assertEqual(len(file_results), 2)
        self.assertEqual(file_results[0]["source_id"], "FILE_INPUT")
        self.assertEqual(file_results[0]["source_type"], "FILE")

        # 2. Feed from Phone Camera
        phone_source = PhoneVideoSource(source_id="PHONE_INPUT", read_timeout=0.1)
        phone_source.open()
        for i in range(2):
            phone_source.push_frame(np.zeros((480, 640, 3), dtype=np.uint8))
        phone_results = mock_vision_pipeline(phone_source, max_frames=2)

        self.assertEqual(len(phone_results), 2)
        self.assertEqual(phone_results[0]["source_id"], "PHONE_INPUT")
        self.assertEqual(phone_results[0]["source_type"], "PHONE")
        self.assertEqual(phone_results[0]["resolution"], (640, 480))


if __name__ == "__main__":
    unittest.main()
