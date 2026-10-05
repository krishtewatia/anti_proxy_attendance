from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Optional
import cv2

from camera.base import VideoFrame, VideoSource, VideoSourceType

logger = logging.getLogger(__name__)


class WebcamVideoSource(VideoSource):
    """Real-time local webcam source adapter (USB-connected phone or laptop built-in webcam).

    Directly captures frames using OpenCV VideoCapture.
    Supports auto-discovery of available camera index and safe idempotent release.
    """

    def __init__(
        self,
        device_index: int | str | None = 0,
        source_id: str = "LOCAL_WEBCAM",
        target_fps: Optional[float] = 10.0,
        width: int = 640,
        height: int = 480,
    ) -> None:
        super().__init__(
            source_id=source_id,
            source_type=VideoSourceType.WEBCAM,
            target_fps=target_fps,
        )
        self.device_index = device_index
        self.requested_width = width
        self.requested_height = height

        self._cap: Optional[cv2.VideoCapture] = None
        self._frame_count: int = 0
        self._actual_width: int = 0
        self._actual_height: int = 0
        self._selected_index: int = 0
        self._backend_used: str = "DirectShow"

    @property
    def is_opened(self) -> bool:
        """Return True if underlying OpenCV capture is currently open."""
        return bool(self._is_opened and self._cap is not None and self._cap.isOpened())

    def open(self) -> None:
        """Open the local webcam device and verify that frames can be read."""
        import sys
        import time

        logger.info(
            "Opening local webcam device_index=%s (requested %dx%d)",
            self.device_index,
            self.requested_width,
            self.requested_height,
        )

        # Determine indices to try
        indices_to_try: list[int] = []
        if self.device_index is None or str(self.device_index).lower() == "auto":
            indices_to_try = [0, 1, 2, 3]
        else:
            try:
                configured_idx = int(self.device_index)
                indices_to_try = [configured_idx]
                # Also add fallback indices 0..3 if configured index fails
                for idx in [0, 1, 2, 3]:
                    if idx not in indices_to_try:
                        indices_to_try.append(idx)
            except ValueError:
                indices_to_try = [0, 1, 2, 3]

        backends_to_try: list[tuple[str, Any]] = []
        if sys.platform == "win32":
            backends_to_try = [
                ("DirectShow", cv2.CAP_DSHOW),
                ("MSMF", cv2.CAP_MSMF),
                ("Default", None),
            ]
        else:
            backends_to_try = [("Default", None)]

        cap = None
        chosen_index = 0
        chosen_backend = "DirectShow"

        for idx in indices_to_try:
            for name, backend_flag in backends_to_try:
                try:
                    if backend_flag is not None:
                        test_cap = cv2.VideoCapture(idx, backend_flag)
                    else:
                        test_cap = cv2.VideoCapture(idx)

                    if test_cap and test_cap.isOpened():
                        # Attempt to set requested resolution
                        if self.requested_width and self.requested_height:
                            test_cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.requested_width)
                            test_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.requested_height)

                        # Verify frames are actually arriving
                        grabbed_ok = False
                        for _ in range(5):
                            ret, test_frame = test_cap.read()
                            if ret and test_frame is not None and test_frame.size > 0:
                                grabbed_ok = True
                                break
                            time.sleep(0.08)

                        # If requested resolution caused failure, fallback to native default resolution
                        if not grabbed_ok:
                            test_cap.release()
                            if backend_flag is not None:
                                test_cap = cv2.VideoCapture(idx, backend_flag)
                            else:
                                test_cap = cv2.VideoCapture(idx)
                            if test_cap and test_cap.isOpened():
                                for _ in range(5):
                                    ret, test_frame = test_cap.read()
                                    if ret and test_frame is not None and test_frame.size > 0:
                                        grabbed_ok = True
                                        logger.info("Fell back to native camera resolution on device %d", idx)
                                        break
                                    time.sleep(0.08)

                        if grabbed_ok:
                            cap = test_cap
                            chosen_index = idx
                            chosen_backend = name
                            logger.info(
                                "Successfully opened camera index %d using %s backend",
                                idx,
                                name,
                            )
                            break
                        else:
                            test_cap.release()
                except Exception:
                    continue

            if cap is not None and cap.isOpened():
                break

        if cap is None or not cap.isOpened():
            raise RuntimeError(
                f"Could not open camera (probed indices: {indices_to_try}). "
                "Camera may be disconnected or in use by another application."
            )

        self._selected_index = chosen_index
        self._backend_used = chosen_backend
        self._actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or self.requested_width)
        self._actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or self.requested_height)
        self._cap = cap
        self._is_opened = True
        self._frame_count = 0

        logger.info(
            "Webcam ACTIVE: Device index %d | Backend: %s | Captured Resolution: %dx%d",
            self._selected_index,
            self._backend_used,
            self._actual_width,
            self._actual_height,
        )

    def read(self) -> VideoFrame | None:
        """Capture next frame from webcam."""
        if not self._is_opened or self._cap is None:
            return None

        ret, frame = self._cap.read()
        if not ret or frame is None:
            logger.warning("Failed to grab frame from webcam %s", self._selected_index)
            return None

        self._frame_count += 1
        now = datetime.now(timezone.utc)

        return VideoFrame(
            frame=frame,
            timestamp=now,
            source_id=self.source_id,
            frame_index=self._frame_count,
            source_type=VideoSourceType.WEBCAM,
        )

    def release(self) -> None:
        """Release underlying camera capture device."""
        self.close()

    def close(self) -> None:
        """Release the webcam device safely and idempotently."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self._is_opened = False
        logger.info("Webcam device %s released.", self._selected_index)
