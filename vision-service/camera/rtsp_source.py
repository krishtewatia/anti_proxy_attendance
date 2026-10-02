from __future__ import annotations

from datetime import datetime, timezone
import logging
import time
from typing import Optional
import cv2
import numpy as np

from camera.base import VideoFrame, VideoSource, VideoSourceType

logger = logging.getLogger(__name__)


class RTSPVideoSource(VideoSource):
    """Video source adapter for IP / CCTV cameras streaming via RTSP.

    Features:
    - Real-time timestamping for live physical security camera streams.
    - Automatic reconnection support upon network jitter or stream dropouts.
    - Optional framerate subsampling to prevent CPU/GPU overload.
    """

    def __init__(
        self,
        rtsp_url: str,
        source_id: str = "CCTV_CAM_DOOR_01",
        target_fps: Optional[float] = 5.0,
        reconnect_interval_sec: float = 2.0,
        max_reconnect_attempts: int = 3,
    ) -> None:
        super().__init__(
            source_id=source_id,
            source_type=VideoSourceType.RTSP,
            target_fps=target_fps,
        )
        self.rtsp_url = rtsp_url
        self.reconnect_interval_sec = reconnect_interval_sec
        self.max_reconnect_attempts = max_reconnect_attempts

        self._cap: Optional[cv2.VideoCapture] = None
        self._last_sample_time: float = 0.0
        self._min_sample_interval: float = 1.0 / target_fps if (target_fps and target_fps > 0) else 0.0

    def open(self) -> None:
        """Establish RTSP stream connection."""
        self._connect_stream()
        self._is_opened = True

    def _connect_stream(self) -> None:
        """Attempt connection to RTSP URL."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

        logger.info("Connecting to RTSP stream: %s (source_id=%s)", self.rtsp_url, self.source_id)
        self._cap = cv2.VideoCapture(self.rtsp_url)

        if not self._cap.isOpened():
            raise ConnectionError(f"Failed to connect to RTSP stream: {self.rtsp_url}")

    def read(self) -> VideoFrame | None:
        """Read the next frame from the live RTSP stream."""
        if not self._is_opened or self._cap is None:
            raise RuntimeError("RTSPVideoSource is not open. Call open() first.")

        attempts = 0
        while attempts <= self.max_reconnect_attempts:
            success, raw_frame = self._cap.read()

            if not success:
                logger.warning(
                    "RTSP read failed for %s. Attempting reconnection (%d/%d)...",
                    self.source_id,
                    attempts + 1,
                    self.max_reconnect_attempts,
                )
                time.sleep(self.reconnect_interval_sec)
                try:
                    self._connect_stream()
                    attempts += 1
                    continue
                except ConnectionError:
                    attempts += 1
                    continue

            now_perf = time.monotonic()
            if self._min_sample_interval > 0:
                elapsed = now_perf - self._last_sample_time
                if elapsed < self._min_sample_interval:
                    continue  # Skip frame to maintain target FPS

            self._last_sample_time = now_perf
            emitted_idx = self._emitted_frame_count
            self._emitted_frame_count += 1

            return VideoFrame(
                frame=raw_frame,
                timestamp=datetime.now(timezone.utc),
                source_id=self.source_id,
                frame_index=emitted_idx,
                source_type=self.source_type,
            )

        return None

    def release(self) -> None:
        """Disconnect and release RTSP socket."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._is_opened = False
