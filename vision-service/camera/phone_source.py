from __future__ import annotations

from datetime import datetime, timezone
import queue
import threading
from typing import Optional
import numpy as np

from camera.base import VideoFrame, VideoSource, VideoSourceType


class PhoneVideoSource(VideoSource):
    """Push-style video source: frames are handed in by the caller as they arrive.

    Accepts frames pushed by any in-process producer (tests, recorded replays, or a
    transports and buffers them in a thread-safe queue with a drop-oldest policy
    to ensure zero-latency real-time vision processing.
    """

    def __init__(
        self,
        source_id: str = "PHONE_CAM_01",
        source_type: VideoSourceType = VideoSourceType.PHONE,
        max_buffer_size: int = 30,
        read_timeout: float = 0.5,
        target_fps: Optional[float] = None,
    ) -> None:
        super().__init__(
            source_id=source_id,
            source_type=source_type,
            target_fps=target_fps,
        )
        self.max_buffer_size = max_buffer_size
        self.read_timeout = read_timeout

        self._queue: queue.Queue[VideoFrame] = queue.Queue(maxsize=max_buffer_size)
        self._lock = threading.Lock()
        self._dropped_frames: int = 0
        self._total_pushed_frames: int = 0

    @property
    def dropped_frames(self) -> int:
        """Count of stale frames dropped due to buffer saturation."""
        return self._dropped_frames

    @property
    def buffer_size(self) -> int:
        """Current number of frames queued waiting for processing."""
        return self._queue.qsize()

    def open(self) -> None:
        """Initialize frame queue and mark source as active."""
        with self._lock:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            self._is_opened = True
            self._status = "CONNECTED"

    def push_frame(
        self,
        frame: np.ndarray,
        timestamp: Optional[datetime] = None,
    ) -> bool:
        """Push a newly received camera frame.

        If the buffer is full, drops the oldest frame in FIFO order to prevent
        pipeline latency accumulation.

        Returns:
            True if queued successfully, False if source is closed.
        """
        if not self._is_opened:
            return False

        if frame is None or not isinstance(frame, np.ndarray):
            raise ValueError("Frame must be a valid numpy.ndarray.")

        ts = timestamp or datetime.now(timezone.utc)

        with self._lock:
            self._total_pushed_frames += 1
            frame_idx = self._total_pushed_frames - 1

            video_frame = VideoFrame(
                frame=frame,
                timestamp=ts,
                source_id=self.source_id,
                frame_index=frame_idx,
                source_type=self.source_type,
            )

            # Drop oldest frame if buffer is saturated
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                    self._dropped_frames += 1
                except queue.Empty:
                    pass

            try:
                self._queue.put_nowait(video_frame)
                return True
            except queue.Full:
                self._dropped_frames += 1
                return False

    def read(
        self,
        block: bool = True,
        timeout: Optional[float] = None,
    ) -> VideoFrame | None:
        """Fetch the next live frame from the buffer.

        Args:
            block: Whether to wait if the buffer is currently empty.
            timeout: Optional override for default read_timeout.
        """
        if not self._is_opened:
            return None

        wait_time = self.read_timeout if timeout is None else timeout
        try:
            if not block or wait_time <= 0:
                video_frame = self._queue.get_nowait()
            else:
                video_frame = self._queue.get(timeout=wait_time)

            self._emitted_frame_count += 1
            return video_frame
        except queue.Empty:
            return None

    async def read_async(self, timeout: Optional[float] = None) -> VideoFrame | None:
        """Asynchronously fetch next frame without blocking the asyncio loop."""
        import asyncio

        return await asyncio.to_thread(self.read, True, timeout)

    def release(self) -> None:
        """Stop accepting frames and flush the buffer."""
        with self._lock:
            self._is_opened = False
            self._status = "DISCONNECTED"
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
