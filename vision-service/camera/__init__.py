"""Unified Video Ingestion & Camera Input Abstraction."""

from camera.base import VideoFrame, VideoSource, VideoSourceType
from camera.factory import create_video_source
from camera.file_source import FileVideoSource
from camera.phone_source import PhoneVideoSource, WebRTCVideoSource
from camera.rtsp_source import RTSPVideoSource
from camera.webrtc_receiver import WebRTCReceiver, WebRTCSignalingServer

__all__ = [
    "VideoFrame",
    "VideoSource",
    "VideoSourceType",
    "FileVideoSource",
    "PhoneVideoSource",
    "WebRTCVideoSource",
    "RTSPVideoSource",
    "WebRTCReceiver",
    "WebRTCSignalingServer",
    "create_video_source",
]
