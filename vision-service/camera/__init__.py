"""Unified Video Ingestion & Camera Input Abstraction."""

from camera.base import VideoFrame, VideoSource, VideoSourceType
from camera.factory import create_video_source
from camera.file_source import FileVideoSource
from camera.phone_source import PhoneVideoSource
from camera.rtsp_source import RTSPVideoSource
from camera.webcam_source import WebcamVideoSource

__all__ = [
    "VideoFrame",
    "VideoSource",
    "VideoSourceType",
    "FileVideoSource",
    "PhoneVideoSource",
    "RTSPVideoSource",
    "WebcamVideoSource",
    "create_video_source",
]
