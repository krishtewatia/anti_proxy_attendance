from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from camera.base import VideoSource, VideoSourceType
from camera.file_source import FileVideoSource
from camera.phone_source import PhoneVideoSource
from camera.rtsp_source import RTSPVideoSource
from camera.webcam_source import WebcamVideoSource


def create_video_source(
    source_type: VideoSourceType | str,
    source_uri: Optional[str | Path] = None,
    source_id: Optional[str] = None,
    target_fps: Optional[float] = 5.0,
    **kwargs: Any,
) -> VideoSource:
    """Factory helper to construct the appropriate VideoSource adapter.

    Args:
        source_type: Modality ("FILE", "RTSP", "PHONE", "WEBRTC").
        source_uri: Path to video file (if FILE) or RTSP URL (if RTSP).
        source_id: Identifier for camera or stream (e.g. "CAM_DOOR_01", "PHONE_01").
        target_fps: Desired sampling rate in FPS (default: 5.0).
        **kwargs: Additional source-specific options (e.g., loop, max_buffer_size).

    Returns:
        Configured VideoSource ready for open().

    Raises:
        ValueError: If source_type is unrecognized or required params are missing.
    """
    normalized_type = str(source_type).upper()

    if normalized_type == VideoSourceType.FILE.value:
        if not source_uri:
            raise ValueError("source_uri (file path) is required for FILE video sources.")
        return FileVideoSource(
            video_path=source_uri,
            source_id=source_id,
            target_fps=target_fps,
            **kwargs,
        )

    elif normalized_type == VideoSourceType.RTSP.value:
        if not source_uri:
            raise ValueError("source_uri (rtsp://...) is required for RTSP video sources.")
        return RTSPVideoSource(
            rtsp_url=str(source_uri),
            source_id=source_id or "RTSP_CAM_01",
            target_fps=target_fps,
            **kwargs,
        )

    elif normalized_type == VideoSourceType.PHONE.value:
        return PhoneVideoSource(
            source_id=source_id or "PHONE_CAM_01",
            source_type=VideoSourceType.PHONE,
            target_fps=target_fps,
            **kwargs,
        )

    elif normalized_type == VideoSourceType.WEBRTC.value:
        return PhoneVideoSource(
            source_id=source_id or "PHONE_CAM_01",
            source_type=VideoSourceType.WEBRTC,
            target_fps=target_fps,
            **kwargs,
        )

    elif normalized_type == VideoSourceType.WEBCAM.value:
        dev_idx = kwargs.pop("device_index", 0)
        if source_uri is not None and str(source_uri).isdigit():
            dev_idx = int(source_uri)
        return WebcamVideoSource(
            device_index=dev_idx,
            source_id=source_id or "LOCAL_WEBCAM",
            target_fps=target_fps,
            **kwargs,
        )

    else:
        supported = [t.value for t in VideoSourceType]
        raise ValueError(
            f"Unsupported video source type: '{source_type}'. Supported types: {supported}"
        )
