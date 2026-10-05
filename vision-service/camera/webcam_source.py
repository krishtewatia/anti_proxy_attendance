from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Optional
import cv2

from camera.base import VideoFrame, VideoSource, VideoSourceType

logger = logging.getLogger(__name__)


class WebcamVideoSource(VideoSource):
    """Real-time local webcam source adapter (USB-connected phone or laptop built-in webcam).

    Directly captures frames using OpenCV VideoCapture.
    """

    def __init__(
        self,
        device_index: int = 0,
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
        self.device_index = int(device_index)
        self.requested_width = width
        self.requested_height = height

        self._cap: Optional[cv2.VideoCapture] = None
        self._frame_count: int = 0
        self._actual_width: int = 0
        self._actual_height: int = 0

    def open(self) -> None:
        """Open the local webcam device and verify that frames can be read."""
        import sys
        import time

        logger.info(
            "Opening local webcam device_index=%d (requested %dx%d)",
            self.device_index,
            self.requested_width,
            self.requested_height,
        )

        cap = None
        backends_to_try = []
        if sys.platform == "win32":
            backends_to_try = [
                ("DirectShow", cv2.CAP_DSHOW),
                ("MSMF", cv2.CAP_MSMF),
                ("Default", None),
            ]
        else:
            backends_to_try = [("Default", None)]

        last_error_backend = None
        for name, backend_flag in backends_to_try:
            try:
                if backend_flag is not None:
                    test_cap = cv2.VideoCapture(self.device_index, backend_flag)
                else:
                    test_cap = cv2.VideoCapture(self.device_index)

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
                            test_cap = cv2.VideoCapture(self.device_index, backend_flag)
                        else:
                            test_cap = cv2.VideoCapture(self.device_index)
                        if test_cap and test_cap.isOpened():
                            for _ in range(5):
                                ret, test_frame = test_cap.read()
                                if ret and test_frame is not None and test_frame.size > 0:
                                    grabbed_ok = True
                                    logger.info("Fell back to native camera resolution")
                                    break
                                time.sleep(0.08)

                    if grabbed_ok:
                        cap = test_cap
                        logger.info(
                            "Successfully opened camera %d using %s backend",
                            self.device_index,
                            name,
                        )
                        break
                    else:
                        logger.warning(
                            "Camera %d opened via %s but failed to read frames",
                            self.device_index,
                            name,
                        )
                        test_cap.release()
            except Exception:
                continue

        if cap is None or not cap.isOpened():
            raise RuntimeError(
                f"\nCould not open camera at device index {self.device_index}.\n\n"
                "Possible causes:\n"
                "  - Camera is already being used by another application (Teams, Zoom, Meet, OBS, Camera app).\n"
                "  - Windows camera permission is disabled (Settings > Privacy & Security > Camera).\n"
                "  - Invalid camera index (run: python vision-service/list_cameras.py).\n"
                "  - USB webcam / phone is disconnected or phone webcam software is not running.\n"
                "  - Camera driver is unavailable."
            )

        self._actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or self.requested_width)
        self._actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or self.requested_height)
        self._cap = cap
        self._is_opened = True
        self._frame_count = 0

        logger.info(
            "Webcam ACTIVE: Device index %d | Captured Resolution: %dx%d",
            self.device_index,
            self._actual_width,
            self._actual_height,
        )

    def read(self) -> VideoFrame | None:
        """Capture next frame from webcam."""
        if not self._is_opened or self._cap is None:
            return None

        ret, frame = self._cap.read()
        if not ret or frame is None:
            logger.warning("Failed to grab frame from webcam %d", self.device_index)
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
        """Release the webcam device."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._is_opened = False
        logger.info("Webcam device %d released.", self.device_index)
