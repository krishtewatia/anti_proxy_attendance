from __future__ import annotations

from datetime import datetime, timezone
import logging
import queue
import re
import threading
import time
from typing import Any, Optional
import urllib.parse
import cv2
import numpy as np

from camera.base import VideoFrame, VideoSource, VideoSourceType

logger = logging.getLogger(__name__)


def mask_rtsp_url(url: str | None) -> str | None:
    """Mask password credentials in an RTSP URL for safe logging."""
    if url is None:
        return None
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.password is not None:
            username = parsed.username or ""
            port_part = f":{parsed.port}" if parsed.port is not None else ""
            masked_netloc = f"{username}:*****@{parsed.hostname}{port_part}"
            return urllib.parse.urlunsplit(
                (
                    parsed.scheme,
                    masked_netloc,
                    parsed.path,
                    parsed.query,
                    parsed.fragment,
                )
            )
        return url
    except Exception:
        return re.sub(r":([^/@:]+)@", ":*****@", url)


class RTSPVideoSource(VideoSource):
    """Hardened video source adapter for IP / CCTV cameras streaming via RTSP.

    Features:
    - Dedicated reader thread with bounded queue (latest-frame-wins drop-oldest buffer).
    - Eliminates OpenCV internal socket buffer lag.
    - Connect and read timeouts.
    - Automatic exponential backoff reconnection upon network dropouts.
    - Live health telemetry: states (CONNECTED, DEGRADED, DISCONNECTED), measured FPS, drops.
    - Safe credential masking in all logs.
    - Clean resource disposal on shutdown.
    """

    def __init__(
        self,
        rtsp_url: str,
        source_id: str = "CCTV_CAM_DOOR_01",
        target_fps: Optional[float] = 5.0,
        reconnect_interval_sec: float = 0.5,
        max_reconnect_attempts: int = 5,
        backoff_factor: float = 1.5,
        max_backoff_sec: float = 5.0,
        read_timeout_sec: float = 2.0,
        queue_size: int = 2,
        use_async_reader: bool = True,
    ) -> None:
        super().__init__(
            source_id=source_id,
            source_type=VideoSourceType.RTSP,
            target_fps=target_fps,
        )
        self.rtsp_url = rtsp_url
        self.reconnect_interval_sec = reconnect_interval_sec
        self.max_reconnect_attempts = max_reconnect_attempts
        self.backoff_factor = backoff_factor
        self.max_backoff_sec = max_backoff_sec
        self.read_timeout_sec = read_timeout_sec
        self.queue_size = queue_size
        self.use_async_reader = use_async_reader

        self._cap: Optional[cv2.VideoCapture] = None
        self._last_sample_time: float = 0.0
        self._min_sample_interval: float = (
            1.0 / target_fps if (target_fps and target_fps > 0) else 0.0
        )

        # Concurrency & buffering
        self._frame_queue: queue.Queue[tuple[np.ndarray, datetime]] = queue.Queue(
            maxsize=queue_size
        )
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Telemetry & health
        self._dropped_frames: int = 0
        self._last_frame_time: Optional[datetime] = None
        self._fps_window: list[float] = []
        self._current_fps: float = 0.0
        self._reconnect_attempts_count: int = 0

    @property
    def fps(self) -> float:
        """Measured rolling ingestion framerate."""
        return round(self._current_fps, 2)

    @property
    def dropped_frames(self) -> int:
        """Total frame drops caused by buffer overflow or network lag."""
        return self._dropped_frames

    @property
    def last_seen(self) -> Optional[datetime]:
        """Timestamp of the most recently received frame."""
        return self._last_frame_time

    def health_summary(self) -> dict[str, Any]:
        """Snapshot of current camera health telemetry."""
        return {
            "source_id": self.source_id,
            "status": self.status,
            "fps": self.fps,
            "dropped_frames": self.dropped_frames,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "reconnect_attempts": self._reconnect_attempts_count,
        }

    def open(self) -> None:
        """Establish RTSP stream connection and launch background reader thread."""
        self._stop_event.clear()
        self._dropped_frames = 0
        self._fps_window.clear()
        self._connect_stream()
        self._is_opened = True
        self._status = "CONNECTED"

        if self.use_async_reader:
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                name=f"rtsp_reader_{self.source_id}",
                daemon=True,
            )
            self._reader_thread.start()

    def _connect_stream(self) -> None:
        """Attempt connection to RTSP URL with credential-masked logging."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

        masked_url = mask_rtsp_url(self.rtsp_url)
        logger.info("Connecting to RTSP stream: %s (source_id=%s)", masked_url, self.source_id)
        self._cap = cv2.VideoCapture(self.rtsp_url)

        if not self._cap.isOpened():
            self._status = "DISCONNECTED"
            raise ConnectionError(f"Failed to connect to RTSP stream: {masked_url}")

    def _reader_loop(self) -> None:
        """Background thread continually reading frames into latest-frame-wins buffer."""
        consecutive_failures = 0

        while not self._stop_event.is_set():
            if self._cap is None or not self._cap.isOpened():
                if consecutive_failures >= self.max_reconnect_attempts:
                    self._status = "DISCONNECTED"
                    logger.error(
                        "Max reconnect attempts (%d) reached for %s. Source disconnected.",
                        self.max_reconnect_attempts,
                        self.source_id,
                    )
                    break

                self._status = "DEGRADED"
                self._reconnect_attempts_count += 1
                backoff = min(
                    self.reconnect_interval_sec * (self.backoff_factor**consecutive_failures),
                    self.max_backoff_sec,
                )
                logger.warning(
                    "Reconnecting to RTSP %s in %.2fs (attempt %d/%d)...",
                    self.source_id,
                    backoff,
                    consecutive_failures + 1,
                    self.max_reconnect_attempts,
                )
                if self._stop_event.wait(timeout=backoff):
                    break

                try:
                    self._connect_stream()
                except ConnectionError:
                    consecutive_failures += 1
                    self._status = "DEGRADED"
                    continue

            # Stream is open, attempt to read next frame
            try:
                success, raw_frame = self._cap.read()
            except Exception as exc:
                logger.warning("RTSP read exception on %s: %s", self.source_id, exc)
                success, raw_frame = False, None

            if not success or raw_frame is None:
                consecutive_failures += 1
                self._status = "DEGRADED"
                logger.warning(
                    "RTSP read failure on %s (attempt %d/%d)",
                    self.source_id,
                    consecutive_failures,
                    self.max_reconnect_attempts,
                )
                if self._cap is not None:
                    self._cap.release()
                    self._cap = None
                continue

            # Successful frame retrieval
            consecutive_failures = 0
            now_dt = datetime.now(timezone.utc)
            now_perf = time.monotonic()
            self._status = "CONNECTED"
            self._last_frame_time = now_dt

            # Update rolling FPS
            self._fps_window.append(now_perf)
            cutoff = now_perf - 3.0
            while self._fps_window and self._fps_window[0] < cutoff:
                self._fps_window.pop(0)
            if len(self._fps_window) > 1:
                span = self._fps_window[-1] - self._fps_window[0]
                self._current_fps = (len(self._fps_window) - 1) / span if span > 0 else 0.0
            else:
                self._current_fps = 1.0

            # Bounded queue: drop oldest frame if full (latest-frame-wins)
            while not self._frame_queue.empty():
                try:
                    self._frame_queue.get_nowait()
                    self._dropped_frames += 1
                except queue.Empty:
                    break

            try:
                self._frame_queue.put_nowait((raw_frame, now_dt))
            except queue.Full:
                self._dropped_frames += 1

            # Prevent CPU spin in test mocks or fast captures
            time.sleep(0.002)

    def read(self) -> VideoFrame | None:
        """Read the freshest available frame from the video buffer."""
        if not self._is_opened:
            raise RuntimeError("RTSPVideoSource is not open. Call open() first.")

        if not self.use_async_reader:
            return self._read_sync()

        while not self._stop_event.is_set():
            try:
                raw_frame, frame_time = self._frame_queue.get(timeout=self.read_timeout_sec)
            except queue.Empty:
                if self._status == "DISCONNECTED" or not (
                    self._reader_thread and self._reader_thread.is_alive()
                ):
                    self._status = "DISCONNECTED"
                    return None
                # Read timed out, mark degraded
                self._status = "DEGRADED"
                return None

            now_perf = time.monotonic()
            if self._min_sample_interval > 0:
                elapsed = now_perf - self._last_sample_time
                if elapsed < self._min_sample_interval:
                    continue  # Subsample to maintain target FPS

            self._last_sample_time = now_perf
            emitted_idx = self._emitted_frame_count
            self._emitted_frame_count += 1

            return VideoFrame(
                frame=raw_frame,
                timestamp=frame_time,
                source_id=self.source_id,
                frame_index=emitted_idx,
                source_type=self.source_type,
            )

        return None

    def _read_sync(self) -> VideoFrame | None:
        """Fallback synchronous reader without thread buffering."""
        if self._cap is None:
            return None

        attempts = 0
        while attempts <= self.max_reconnect_attempts:
            success, raw_frame = self._cap.read()
            if not success or raw_frame is None:
                self._status = "DEGRADED"
                time.sleep(self.reconnect_interval_sec)
                try:
                    self._connect_stream()
                    self._status = "CONNECTED"
                    attempts += 1
                    continue
                except ConnectionError:
                    self._status = "DEGRADED"
                    attempts += 1
                    continue

            self._status = "CONNECTED"
            now_perf = time.monotonic()
            if self._min_sample_interval > 0:
                elapsed = now_perf - self._last_sample_time
                if elapsed < self._min_sample_interval:
                    continue

            self._last_sample_time = now_perf
            emitted_idx = self._emitted_frame_count
            self._emitted_frame_count += 1
            now_dt = datetime.now(timezone.utc)
            self._last_frame_time = now_dt

            return VideoFrame(
                frame=raw_frame,
                timestamp=now_dt,
                source_id=self.source_id,
                frame_index=emitted_idx,
                source_type=self.source_type,
            )

        self._status = "DISCONNECTED"
        return None

    def release(self) -> None:
        """Cleanly stop background reader and release RTSP connection."""
        self._is_opened = False
        self._stop_event.set()

        if self._reader_thread is not None and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2.0)
            self._reader_thread = None

        if self._cap is not None:
            self._cap.release()
            self._cap = None

        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break

        self._status = "DISCONNECTED"
