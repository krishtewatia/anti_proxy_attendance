from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterator
import numpy as np


class VideoSourceType(str, Enum):
    """Supported video source modalities."""

    FILE = "FILE"
    RTSP = "RTSP"
    PHONE = "PHONE"
    WEBRTC = "WEBRTC"


@dataclass(frozen=True)
class VideoFrame:
    """Standardized video frame contract delivered to the Vision Pipeline.

    Decouples CV downstream consumers (detection, tracking, recognition, attendance)
    from the origin modality (Phone, CCTV, RTSP, or local video file).
    """

    frame: np.ndarray
    timestamp: datetime
    source_id: str
    frame_index: int
    source_type: VideoSourceType

    @property
    def width(self) -> int:
        """Frame width in pixels."""
        return int(self.frame.shape[1]) if self.frame is not None and self.frame.ndim >= 2 else 0

    @property
    def height(self) -> int:
        """Frame height in pixels."""
        return int(self.frame.shape[0]) if self.frame is not None and self.frame.ndim >= 2 else 0

    @property
    def shape(self) -> tuple[int, ...]:
        """NumPy array shape (height, width, channels)."""
        return self.frame.shape if self.frame is not None else ()


class VideoSource(ABC):
    """Abstract base class for all video input adapters.

    All video input sources (Phone/WebRTC, CCTV/RTSP, local MP4 file) must implement
    this interface to supply frames seamlessly into the unified vision pipeline.
    """

    def __init__(
        self,
        source_id: str,
        source_type: VideoSourceType,
        target_fps: float | None = None,
    ) -> None:
        self.source_id = source_id
        self.source_type = source_type
        self.target_fps = target_fps
        self._is_opened: bool = False
        self._emitted_frame_count: int = 0

    @property
    def is_opened(self) -> bool:
        """Whether the video source is currently open and ready to emit frames."""
        return self._is_opened

    @property
    def emitted_frame_count(self) -> int:
        """Total number of frames emitted by this source since opening."""
        return self._emitted_frame_count

    @abstractmethod
    def open(self) -> None:
        """Establish connection or open video stream/file.

        Raises:
            RuntimeError / FileNotFoundError if opening fails.
        """
        ...

    @abstractmethod
    def read(self) -> VideoFrame | None:
        """Read the next available frame from the video source.

        Returns:
            VideoFrame if a frame was successfully retrieved,
            None if end-of-stream (EOF) or disconnected.
        """
        ...

    @abstractmethod
    def release(self) -> None:
        """Release underlying system resources (camera, file handle, socket)."""
        ...

    def stream(self) -> Iterator[VideoFrame]:
        """Generator yielding frames sequentially until the source terminates."""
        if not self._is_opened:
            self.open()

        try:
            while self._is_opened:
                frame = self.read()
                if frame is None:
                    break
                yield frame
        finally:
            self.release()

    def __iter__(self) -> Iterator[VideoFrame]:
        return self.stream()

    def __enter__(self) -> VideoSource:
        if not self._is_opened:
            self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()
