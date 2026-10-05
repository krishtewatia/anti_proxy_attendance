from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import cv2

from camera.base import VideoFrame, VideoSource, VideoSourceType


class FileVideoSource(VideoSource):
    """Video source adapter for recorded local video files (.mp4, .avi, etc.).

    Provides deterministic frame extraction, target FPS downsampling, and
    timestamp calculation matching the benchmark test suite.
    """

    def __init__(
        self,
        video_path: str | Path,
        source_id: Optional[str] = None,
        target_fps: Optional[float] = 5.0,
        start_time: Optional[datetime] = None,
        loop: bool = False,
    ) -> None:
        self.video_path = Path(video_path).resolve()
        sid = source_id or self.video_path.stem
        super().__init__(source_id=sid, source_type=VideoSourceType.FILE, target_fps=target_fps)

        self.start_time = start_time
        self.loop = loop

        self._cap: Optional[cv2.VideoCapture] = None
        self._source_fps: float = 0.0
        self._total_frames: int = 0
        self._width: int = 0
        self._height: int = 0
        self._duration_seconds: float = 0.0

        self._read_count: int = 0
        self._next_sample_frame: float = 0.0
        self._step_interval: float = 1.0

    @property
    def source_fps(self) -> float:
        """Original video source framerate."""
        return self._source_fps

    @property
    def total_frames(self) -> int:
        """Total frame count in the source file."""
        return self._total_frames

    @property
    def duration_seconds(self) -> float:
        """Duration of the video file in seconds."""
        return self._duration_seconds

    def open(self) -> None:
        """Open the video file and extract container metadata."""
        if not self.video_path.exists():
            raise FileNotFoundError(f"Video file not found: {self.video_path}")

        self._cap = cv2.VideoCapture(str(self.video_path))
        if not self._cap.isOpened():
            raise RuntimeError(f"Failed to open video file: {self.video_path}")

        self._source_fps = float(self._cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self._width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        self._height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        self._total_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

        if self._source_fps > 0:
            self._duration_seconds = self._total_frames / self._source_fps
        else:
            self._duration_seconds = 0.0

        if self.target_fps is not None and self.target_fps > 0 and self._source_fps > 0:
            self._step_interval = self._source_fps / self.target_fps
        else:
            self._step_interval = 1.0

        if self.start_time is None:
            self.start_time = datetime.now(timezone.utc)

        self._read_count = 0
        self._next_sample_frame = 0.0
        self._is_opened = True

    def read(self) -> VideoFrame | None:
        """Read the next sampled frame matching target_fps."""
        if not self._is_opened or self._cap is None:
            raise RuntimeError("FileVideoSource is not open. Call open() first.")

        while True:
            success, raw_frame = self._cap.read()

            if not success:
                if self.loop:
                    # Rewind to the beginning
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self._read_count = 0
                    self._next_sample_frame = 0.0
                    success, raw_frame = self._cap.read()
                    if not success:
                        return None
                else:
                    return None

            current_frame_idx = self._read_count
            self._read_count += 1

            # Check if this frame hits the target sampling checkpoint
            if current_frame_idx >= int(round(self._next_sample_frame)):
                self._next_sample_frame += self._step_interval

                if self._source_fps > 0:
                    elapsed_seconds = current_frame_idx / self._source_fps
                else:
                    elapsed_seconds = current_frame_idx * (1.0 / (self.target_fps or 5.0))

                frame_timestamp = self.start_time + timedelta(seconds=elapsed_seconds)
                emitted_idx = self._emitted_frame_count
                self._emitted_frame_count += 1

                return VideoFrame(
                    frame=raw_frame,
                    timestamp=frame_timestamp,
                    source_id=self.source_id,
                    frame_index=emitted_idx,
                    source_type=self.source_type,
                )

    def release(self) -> None:
        """Close video capture handle."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._is_opened = False
