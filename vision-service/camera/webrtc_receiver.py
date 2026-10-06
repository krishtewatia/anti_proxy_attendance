from __future__ import annotations

import asyncio
import hmac
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import secrets
import threading
import time
from typing import Any, Optional, Set

from aiohttp import web
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError
import av
import numpy as np

from camera.phone_source import PhoneVideoSource
from camera.recognition_signing import sign_recognition

logger = logging.getLogger(__name__)


HTML_PHONE_CLIENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Mobile Attendance Scanner — CS-101</title>
    <style>
        :root {
            --bg: #090d16;
            --card-bg: rgba(22, 30, 49, 0.85);
            --card-border: rgba(99, 102, 241, 0.3);
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --primary: #6366f1;
            --primary-hover: #4f46e5;
            --success: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            -webkit-tap-highlight-color: transparent;
        }

        body {
            background-color: var(--bg);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 16px;
        }

        header {
            width: 100%;
            max-width: 520px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0 14px 0;
        }

        .title-group h1 {
            font-size: 1.15rem;
            font-weight: 700;
            background: linear-gradient(135deg, #a5b4fc, #818cf8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .title-group p {
            font-size: 0.75rem;
            color: var(--text-muted);
        }

        .session-badge {
            background: rgba(99, 102, 241, 0.15);
            border: 1px solid rgba(99, 102, 241, 0.35);
            border-radius: 8px;
            padding: 8px 12px;
            width: 100%;
            max-width: 520px;
            margin-bottom: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.8rem;
        }

        .session-badge strong {
            color: #c7d2fe;
        }

        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 10px;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
            background: rgba(148, 163, 184, 0.15);
            color: var(--text-muted);
            border: 1px solid rgba(148, 163, 184, 0.2);
            transition: all 0.2s ease;
        }

        .status-pill.connected {
            background: rgba(16, 185, 129, 0.15);
            color: #34d399;
            border-color: rgba(16, 185, 129, 0.3);
        }

        .status-pill.streaming {
            background: rgba(99, 102, 241, 0.2);
            color: #a5b4fc;
            border-color: rgba(99, 102, 241, 0.4);
        }

        .status-pill.error {
            background: rgba(239, 68, 68, 0.15);
            color: #f87171;
            border-color: rgba(239, 68, 68, 0.3);
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: currentColor;
        }

        .viewport-card {
            width: 100%;
            max-width: 520px;
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
            backdrop-filter: blur(12px);
            position: relative;
            aspect-ratio: 4 / 3;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        video {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
            background: #000;
        }

        .overlay-stats {
            position: absolute;
            top: 12px;
            left: 12px;
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(8px);
            padding: 6px 12px;
            border-radius: 8px;
            font-size: 0.72rem;
            color: var(--text-muted);
            border: 1px solid rgba(255, 255, 255, 0.1);
            display: flex;
            flex-direction: column;
            gap: 2px;
            pointer-events: none;
            z-index: 5;
        }

        .doorway-hud-line {
            position: absolute;
            left: 50%;
            top: 0;
            bottom: 0;
            width: 2px;
            background: linear-gradient(180deg, rgba(16,185,129,0.2) 0%, rgba(16,185,129,0.85) 50%, rgba(16,185,129,0.2) 100%);
            box-shadow: 0 0 10px rgba(16, 185, 129, 0.6);
            pointer-events: none;
            z-index: 4;
        }

        .doorway-hud-label {
            position: absolute;
            top: 8px;
            left: 50%;
            transform: translateX(8px);
            background: rgba(16, 185, 129, 0.2);
            border: 1px solid rgba(16, 185, 129, 0.5);
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 0.65rem;
            font-weight: 700;
            color: #34d399;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            pointer-events: none;
            z-index: 4;
            writing-mode: vertical-rl;
        }

        .controls-card {
            width: 100%;
            max-width: 520px;
            margin-top: 14px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        button {
            padding: 14px 18px;
            border-radius: 12px;
            font-size: 0.95rem;
            font-weight: 600;
            border: none;
            cursor: pointer;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }

        .btn-primary {
            background: linear-gradient(135deg, #6366f1, #4f46e5);
            color: white;
            box-shadow: 0 4px 14px rgba(99, 102, 241, 0.35);
        }

        .btn-primary:active {
            transform: scale(0.98);
        }

        .btn-row {
            display: flex;
            gap: 10px;
        }

        .btn-secondary {
            flex: 1;
            background: rgba(255, 255, 255, 0.08);
            color: var(--text-main);
            border: 1px solid rgba(255, 255, 255, 0.15);
        }

        .btn-danger {
            background: linear-gradient(135deg, #ef4444, #dc2626);
            color: white;
        }

        .quick-actions-card {
            width: 100%;
            max-width: 520px;
            margin-top: 14px;
            padding: 14px 16px;
            background: rgba(30, 41, 59, 0.6);
            border-radius: 14px;
            border: 1px solid rgba(255, 255, 255, 0.08);
        }

        .quick-actions-header {
            font-size: 0.82rem;
            font-weight: 700;
            color: #cbd5e1;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .actions-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }

        .btn-action {
            padding: 10px 8px;
            border-radius: 8px;
            font-size: 0.78rem;
            font-weight: 600;
            border: 1px solid transparent;
            cursor: pointer;
            transition: all 0.15s ease;
            text-align: center;
        }

        .btn-action.entry {
            background: rgba(16, 185, 129, 0.15);
            border-color: rgba(16, 185, 129, 0.35);
            color: #34d399;
        }

        .btn-action.entry:active {
            background: rgba(16, 185, 129, 0.35);
        }

        .btn-action.exit {
            background: rgba(245, 158, 11, 0.15);
            border-color: rgba(245, 158, 11, 0.35);
            color: #fbbf24;
        }

        .btn-action.exit:active {
            background: rgba(245, 158, 11, 0.35);
        }

        .toast-msg {
            margin-top: 10px;
            padding: 8px 12px;
            border-radius: 8px;
            font-size: 0.78rem;
            background: rgba(16, 185, 129, 0.2);
            border: 1px solid rgba(16, 185, 129, 0.4);
            color: #a7f3d0;
            display: none;
            text-align: center;
        }
    </style>
</head>
<body>
    <header>
        <div class="title-group">
            <h1>Mobile Attendance Scanner</h1>
            <p>Direct Monitoring for PC Localhost</p>
        </div>
        <div id="statusPill" class="status-pill">
            <span class="status-dot"></span>
            <span id="statusText">IDLE</span>
        </div>
    </header>

    <div class="session-badge">
        <div>
            <span>Course:</span> <strong>CS-101 Intro to Computer Science</strong>
        </div>
        <div>
            <span>Room:</span> <strong>ROOM_101</strong>
        </div>
    </div>

    <div class="viewport-card">
        <video id="localVideo" autoplay playsinline muted></video>
        <div class="doorway-hud-line"></div>
        <div class="doorway-hud-label">Transit Boundary Line</div>
        <div class="overlay-stats" id="statsOverlay">
            <div>Camera: <span id="statSource" style="color:#f8fafc">CAM_ROOM_101_DOOR</span></div>
            <div>Resolution: <span id="statResolution" style="color:#f8fafc">-</span></div>
            <div>Streamed: <span id="statFrames" style="color:#38bdf8">0</span> frames</div>
        </div>
    </div>

    <div class="controls-card">
        <button id="startBtn" class="btn-primary" onclick="startStreaming()">
            🔴 START LIVE ATTENDANCE SCANNER
        </button>
        <div class="btn-row">
            <button id="switchBtn" class="btn-secondary" onclick="switchCamera()">
                🔄 Switch Camera
            </button>
            <button id="stopBtn" class="btn-secondary btn-danger" onclick="stopStreaming()" disabled>
                ⏹️ Stop
            </button>
        </div>
    </div>

    <div class="quick-actions-card">
        <div class="quick-actions-header">
            <span>⚡ Instant Transit Triggers (Push to PC):</span>
            <span style="font-size:0.7rem; color:#94a3b8">1-Tap Test</span>
        </div>
        <div class="actions-grid">
            <button type="button" class="btn-action entry" onclick="sendTransit('person_01', 'ENTRY')">
                + Enter: Student 1
            </button>
            <button type="button" class="btn-action exit" onclick="sendTransit('person_01', 'EXIT')">
                − Exit: Student 1
            </button>
            <button type="button" class="btn-action entry" onclick="sendTransit('person_02', 'ENTRY')">
                + Enter: Student 2
            </button>
            <button type="button" class="btn-action exit" onclick="sendTransit('person_02', 'EXIT')">
                − Exit: Student 2
            </button>
            <button type="button" class="btn-action entry" onclick="sendTransit('person_03', 'ENTRY')">
                + Enter: Student 3
            </button>
            <button type="button" class="btn-action exit" onclick="sendTransit('person_03', 'EXIT')">
                − Exit: Student 3
            </button>
            <button type="button" class="btn-action entry" onclick="sendTransit('person_04', 'ENTRY')">
                + Enter: Student 4
            </button>
            <button type="button" class="btn-action exit" onclick="sendTransit('person_04', 'EXIT')">
                − Exit: Student 4
            </button>
        </div>
        <div id="toastMsg" class="toast-msg"></div>
    </div>

    <script>
        let peerConnection = null;
        let localStream = null;
        let currentFacingMode = 'environment';
        let frameCount = 0;
        let statsInterval = null;

        const videoElem = document.getElementById('localVideo');
        const startBtn = document.getElementById('startBtn');
        const stopBtn = document.getElementById('stopBtn');
        const switchBtn = document.getElementById('switchBtn');
        const statusPill = document.getElementById('statusPill');
        const statusText = document.getElementById('statusText');
        const statResolution = document.getElementById('statResolution');
        const statFrames = document.getElementById('statFrames');
        const toastMsg = document.getElementById('toastMsg');

        function setStatus(status, className) {
            statusText.innerText = status;
            statusPill.className = 'status-pill ' + (className || '');
        }

        function showToast(text, isError) {
            toastMsg.innerText = text;
            toastMsg.style.display = 'block';
            toastMsg.style.borderColor = isError ? 'rgba(239, 68, 68, 0.4)' : 'rgba(16, 185, 129, 0.4)';
            toastMsg.style.color = isError ? '#fca5a5' : '#a7f3d0';
            setTimeout(() => { toastMsg.style.display = 'none'; }, 3000);
        }

        async function sendTransit(identity, direction) {
            try {
                showToast(`Sending ${direction} event for ${identity}...`, false);
                const res = await fetch('/transit', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ identity, direction })
                });
                const data = await res.json();
                if (res.ok) {
                    showToast(`✓ ${identity} marked ${direction}! Updated on PC.`, false);
                } else {
                    showToast(`Error: ${data.message || data.error}`, true);
                }
            } catch (err) {
                showToast(`Failed: ${err.message}`, true);
            }
        }

        async function startStreaming() {
            try {
                setStatus('REQUESTING CAMERA...', '');
                startBtn.disabled = true;

                if (localStream) {
                    localStream.getTracks().forEach(t => t.stop());
                }

                localStream = await navigator.mediaDevices.getUserMedia({
                    audio: false,
                    video: {
                        facingMode: { ideal: currentFacingMode },
                        width: { ideal: 1280 },
                        height: { ideal: 720 },
                        frameRate: { ideal: 30 }
                    }
                });

                videoElem.srcObject = localStream;
                await videoElem.play();

                const videoTrack = localStream.getVideoTracks()[0];
                const settings = videoTrack.getSettings();
                statResolution.innerText = `${settings.width || 1280}x${settings.height || 720}`;

                setStatus('CONNECTING WEBRTC...', 'streaming');

                peerConnection = new RTCPeerConnection({
                    iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
                });

                peerConnection.onconnectionstatechange = () => {
                    const state = peerConnection.connectionState;
                    if (state === 'connected') {
                        setStatus('STREAMING LIVE TO CS-101', 'connected');
                    } else if (state === 'disconnected' || state === 'failed') {
                        setStatus('DISCONNECTED', 'error');
                    } else if (state === 'closed') {
                        setStatus('STOPPED', '');
                    }
                };

                localStream.getTracks().forEach(track => {
                    peerConnection.addTrack(track, localStream);
                });

                const offer = await peerConnection.createOffer();
                await peerConnection.setLocalDescription(offer);

                await new Promise(resolve => {
                    if (peerConnection.iceGatheringState === 'complete') {
                        resolve();
                    } else {
                        const checkState = () => {
                            if (peerConnection.iceGatheringState === 'complete') {
                                peerConnection.removeEventListener('icegatheringstatechange', checkState);
                                resolve();
                            }
                        };
                        peerConnection.addEventListener('icegatheringstatechange', checkState);
                    }
                });

                const offerUrl = '/offer' + (window.location.search || '');
                const response = await fetch(offerUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        sdp: peerConnection.localDescription.sdp,
                        type: peerConnection.localDescription.type
                    })
                });

                if (!response.ok) {
                    throw new Error(`Server returned HTTP ${response.status}`);
                }

                const answer = await response.json();
                await peerConnection.setRemoteDescription(new RTCSessionDescription(answer));

                stopBtn.disabled = false;
                startBtn.style.display = 'none';

                frameCount = 0;
                clearInterval(statsInterval);
                statsInterval = setInterval(() => {
                    if (peerConnection && peerConnection.connectionState === 'connected') {
                        frameCount += 15;
                        statFrames.innerText = frameCount;
                    }
                }, 1000);

            } catch (err) {
                console.error(err);
                setStatus('ERROR: ' + err.message, 'error');
                startBtn.disabled = false;
                startBtn.style.display = 'inline-flex';
                stopBtn.disabled = true;
            }
        }

        function stopStreaming() {
            clearInterval(statsInterval);
            if (peerConnection) {
                peerConnection.close();
                peerConnection = null;
            }
            if (localStream) {
                localStream.getTracks().forEach(t => t.stop());
                localStream = null;
            }
            videoElem.srcObject = null;
            setStatus('STOPPED', '');
            startBtn.disabled = false;
            startBtn.style.display = 'inline-flex';
            stopBtn.disabled = true;
        }

        async function switchCamera() {
            currentFacingMode = (currentFacingMode === 'environment') ? 'user' : 'environment';
            if (peerConnection) {
                stopStreaming();
                await startStreaming();
            }
        }
    </script>
</body>
</html>
"""


class WebRTCReceiver:
    """Decodes WebRTC video streams and forwards frames to PhoneVideoSource."""

    def __init__(
        self,
        video_source: PhoneVideoSource,
        source_id: str = "PHONE_CAM_01",
    ) -> None:
        self.video_source = video_source
        self.source_id = source_id

        self._pcs: Set[RTCPeerConnection] = set()
        self._tasks: Set[asyncio.Task] = set()
        self._received_frames: int = 0
        self._connection_state: str = "IDLE"
        self._lock = asyncio.Lock()

    @property
    def received_frames(self) -> int:
        """Total number of frames received and pushed from WebRTC tracks."""
        return self._received_frames

    @property
    def connection_state(self) -> str:
        """Current WebRTC peer connection state."""
        return self._connection_state

    async def handle_offer(self, offer_data: dict[str, str]) -> dict[str, str]:
        """Handle incoming WebRTC SDP offer, establish peer connection, and return SDP answer."""
        async with self._lock:
            # Clean up prior connections cleanly upon new connect/reconnect
            await self._cleanup_active_connections()

            pc = RTCPeerConnection()
            self._pcs.add(pc)
            self._connection_state = "CONNECTING"

            @pc.on("connectionstatechange")
            def on_connection_state_change():
                state = pc.connectionState
                self._connection_state = state.upper()
                logger.info("WebRTC Connection state: %s", state)
                if state in {"failed", "closed", "disconnected"}:
                    asyncio.create_task(self._close_pc(pc))

            @pc.on("track")
            def on_track(track: MediaStreamTrack):
                if track.kind == "video":
                    logger.info("Received video track from WebRTC client: %s", track.id)
                    task = asyncio.create_task(self._consume_track(track))
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)

            # Set remote description (SDP Offer)
            offer = RTCSessionDescription(sdp=offer_data["sdp"], type=offer_data["type"])
            await pc.setRemoteDescription(offer)

            # Create SDP Answer
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)

            return {
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type,
            }

    async def _consume_track(self, track: MediaStreamTrack) -> None:
        """Asynchronously receive and decode video frames from WebRTC track."""
        try:
            while True:
                frame: av.VideoFrame = await track.recv()
                self._received_frames += 1

                # Convert PyAV VideoFrame to OpenCV BGR numpy array
                bgr_array: np.ndarray = frame.to_ndarray(format="bgr24")
                now = datetime.now(timezone.utc)

                # Push to PhoneVideoSource (enforces drop-oldest bounded buffer)
                self.video_source.push_frame(bgr_array, timestamp=now)

                if self._received_frames % 50 == 0 or self._received_frames == 1:
                    logger.info(
                        "WebRTC Ingest: Received frame #%d (shape=%s, source_id=%s)",
                        self._received_frames,
                        bgr_array.shape,
                        self.source_id,
                    )
        except (MediaStreamError, asyncio.CancelledError):
            logger.info("WebRTC video track ended or was cancelled.")
        except Exception as exc:
            logger.warning("Error consuming WebRTC track: %s", exc)

    async def _close_pc(self, pc: RTCPeerConnection) -> None:
        """Safely close an individual peer connection."""
        if pc in self._pcs:
            self._pcs.discard(pc)
            try:
                await pc.close()
            except Exception as exc:
                logger.debug("Non-critical exception closing peer connection: %s", exc)

    async def _cleanup_active_connections(self) -> None:
        """Cancel lingering tasks and close peer connections."""
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()

        for pc in list(self._pcs):
            try:
                await pc.close()
            except Exception as exc:
                logger.debug(
                    "Non-critical exception closing peer connection during cleanup: %s", exc
                )
        self._pcs.clear()

    async def close(self) -> None:
        """Release all WebRTC resources."""
        await self._cleanup_active_connections()
        self._connection_state = "CLOSED"


GALLERY_REFRESH_SECONDS = 30.0


def make_cors_headers(origin: Optional[str] = None) -> dict[str, str]:
    """No CORS headers: the service is called only by the backend, never by a browser."""
    return {}


@web.middleware
async def service_auth_middleware(request: web.Request, handler):
    """Require the shared service key on every route except the liveness probe.

    Fail closed: if no key is configured, nothing but /health is served.
    """
    if request.path != "/health":
        expected = os.getenv("VISION_SERVICE_API_KEY", "").strip()
        presented = request.headers.get("X-API-Key", "").strip()
        if (
            not expected
            or not presented
            or not hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))
        ):
            logger.warning("Rejected unauthenticated request to %s", request.path)
            return web.json_response({"error": "unauthorized"}, status=401)

    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception:
        logger.exception("Error processing request %s", request.path)
        return web.json_response({"error": "internal error"}, status=500)


class WebRTCSignalingServer:
    """Lightweight HTTP & WebRTC Signaling server for phone camera ingest and browser frame inference."""

    def __init__(
        self,
        video_source: PhoneVideoSource,
        host: str = "0.0.0.0",
        port: int = 8088,
        access_token: Optional[str] = None,
        event_dispatcher: Optional[Any] = None,
        camera_id: str = "CAM_ROOM_101_DOOR",
    ) -> None:
        self.video_source = video_source
        self.host = host
        self.port = port
        self.access_token = (
            access_token if access_token is not None else os.getenv("WEBRTC_ACCESS_TOKEN")
        )
        self.event_dispatcher = event_dispatcher
        self.camera_id = camera_id
        self.receiver = WebRTCReceiver(video_source=video_source, source_id=video_source.source_id)

        self.latest_preview_jpeg: Optional[bytes] = None
        self.latest_cv_result: Optional[Any] = None
        self.pipeline_ref: Optional[Any] = None
        self._fallback_app: Optional[Any] = None
        self._fallback_gallery: Optional[dict[str, np.ndarray]] = None
        self.latest_frame_time: float = 0.0
        self.marked_identities: Set[str] = set()
        self.active_session_id: Optional[str] = None
        self.last_recognized_student: Optional[str] = None
        self.session_marked_identities: dict[str, Set[str]] = {}

        self.gallery: dict[str, np.ndarray] = {}
        self.student_names: dict[str, str] = {
            "student1": "Rahul Sharma",
            "student2": "Aman Kumar",
            "student3": "Priya Singh",
            "student4": "Krish Tewatia",
            "person_01": "Rahul Sharma",
            "person_02": "Aman Kumar",
            "person_03": "Priya Singh",
            "person_04": "Krish Tewatia",
        }
        self.student_ids: dict[str, str] = {
            "student1": "DS202601",
            "student2": "DS202602",
            "student3": "DS202603",
            "student4": "DS202604",
            "person_01": "DS202601",
            "person_02": "DS202602",
            "person_03": "DS202603",
            "person_04": "DS202604",
        }
        self._init_gallery()

        self._last_gallery_sync: float = 0.0

        # Internal API only. The phone WebRTC routes (/, /offer, /transit) and the
        # preview routes are no longer registered; the browser never talks to this
        # service, and every route below except /health requires the service key.
        self.app = web.Application(
            middlewares=[service_auth_middleware], client_max_size=32 * 1024 * 1024
        )
        self.app.router.add_post("/process-frame", self._handle_process_frame)
        self.app.router.add_post("/reset", self._handle_reset)
        self.app.router.add_post("/extract-embedding", self._handle_extract_embedding)
        self.app.router.add_post("/enroll-student", self._handle_enroll_student)
        self.app.router.add_post("/reload-gallery", self._handle_reload_gallery)
        self.app.router.add_get("/gallery", self._handle_get_gallery)
        self.app.router.add_get("/status", self._handle_status)
        self.app.router.add_get("/health", self._handle_health)

        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event = threading.Event()

    def _is_authorized(self, request: web.Request) -> bool:
        """Requests reaching a handler already passed service_auth_middleware."""
        return True

    async def _handle_index(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return web.Response(
                text="<h1>401 Unauthorized</h1><p>A valid camera access token is required to view this ingestion interface.</p>",
                status=401,
                content_type="text/html",
            )
        return web.Response(text=HTML_PHONE_CLIENT, content_type="text/html")

    async def _handle_offer(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return web.json_response(
                {"error": "Unauthorized: valid access token required"}, status=401
            )

        try:
            data = await request.json()
            if "sdp" not in data or "type" not in data:
                return web.json_response({"error": "Invalid offer payload"}, status=400)

            answer = await self.receiver.handle_offer(data)
            return web.json_response(answer)
        except Exception as exc:
            logger.exception("Failed to process WebRTC offer")
            return web.json_response({"error": str(exc)}, status=500)

    async def _handle_transit(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        try:
            data = await request.json()
            identity = data.get("identity")
            direction = str(data.get("direction", "ENTRY")).upper()
            if not identity:
                return web.json_response({"error": "Missing identity parameter"}, status=400)

            if self.event_dispatcher is not None:
                import random
                import time

                event_payload = {
                    "event_id": f"evt_mobile_{int(time.time() * 1000)}_{secrets.token_hex(4)}",
                    "camera_id": self.camera_id,
                    "track_id": random.randint(100, 999),
                    "identity": identity,
                    "direction": direction,
                    "timestamp": datetime.now(timezone.utc),
                    "evidence": {
                        "peak_similarity": 0.96,
                        "mean_similarity": 0.93,
                        "supporting_frames": 12,
                        "total_frames": 12,
                        "consistency_pct": 100.0,
                    },
                }
                success = self.event_dispatcher.dispatch(event_payload)
                return web.json_response(
                    {
                        "status": "dispatched" if success else "queued",
                        "event_id": event_payload["event_id"],
                        "identity": identity,
                        "direction": direction,
                        "camera_id": self.camera_id,
                        "message": f"Transit {direction} for {identity} sent to PC Localhost",
                    }
                )
            else:
                return web.json_response(
                    {
                        "status": "error",
                        "message": "Event dispatcher not connected to backend",
                    },
                    status=503,
                )
        except Exception as exc:
            logger.exception("Failed to process transit request: %s", exc)
            return web.json_response({"error": str(exc)}, status=500)

    async def _handle_cors_options(self, request: web.Request) -> web.Response:
        return web.Response(
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "*",
            }
        )

    async def _handle_reset(self, request: web.Request) -> web.Response:
        new_sess_id = None
        try:
            data = await request.json()
            new_sess_id = data.get("session_id")
        except Exception:
            pass
        self.marked_identities.clear()
        self.session_marked_identities.clear()
        self.active_session_id = new_sess_id
        self.last_recognized_student = None
        return web.json_response(
            {"status": "reset", "active_session_id": new_sess_id, "present_count": 0},
        )

    def _get_enrolled_gallery_path(self) -> Path:
        candidates = [
            Path("/app/data"),
            Path(__file__).resolve().parent.parent / "data",
        ]
        for c in candidates:
            if c.exists() or c.parent.exists():
                c.mkdir(parents=True, exist_ok=True)
                return c / "enrolled_gallery.json"
        return Path(__file__).resolve().parent / "enrolled_gallery.json"

    def _save_enrolled_gallery_file(self) -> None:
        """Embeddings are never written to disk; the backend is the only source."""
        return None

    def _load_enrolled_gallery_file(self) -> None:
        """Embeddings are never read from disk; the backend is the only source."""
        return None

    def _init_gallery(self) -> None:
        """The gallery starts empty.

        Embeddings are loaded only from the backend over its authenticated
        internal route (see _sync_from_backend), never from a file in the image,
        the working directory, or a data volume.
        """
        return None

    def _get_app(self) -> Any:
        if self.pipeline_ref and getattr(self.pipeline_ref, "app", None):
            return self.pipeline_ref.app
        if self._fallback_app is None:
            try:
                from pipeline.live_cv_pipeline import create_face_analysis

                self._fallback_app = create_face_analysis()
            except Exception as exc:
                logger.warning("Could not initialize fallback face analysis: %s", exc)
        return self._fallback_app

    def _get_gallery(self) -> dict[str, np.ndarray]:
        if not self.gallery:
            self._init_gallery()
        if self.pipeline_ref and hasattr(self.pipeline_ref, "gallery"):
            self.pipeline_ref.gallery.update(self.gallery)
            self.gallery.update(self.pipeline_ref.gallery)
        return self.gallery

    async def _sync_from_backend(self, backend_url: str) -> bool:
        import aiohttp

        url = f"{backend_url.rstrip('/')}/api/v1/attendance/vision-gallery"
        try:
            service_key = os.getenv("VISION_SERVICE_API_KEY", "").strip()
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={"X-API-Key": service_key},
                    timeout=aiohttp.ClientTimeout(total=4.0),
                ) as resp:
                    self._last_gallery_sync = time.time()
                    if resp.status == 200:
                        data = await resp.json()
                        gallery_list = data.get("gallery", [])
                        new_gallery = {}
                        new_names = {}
                        new_ids = {}
                        for item in gallery_list:
                            ident = item.get("identity")
                            name = item.get("name") or ident
                            stu_id = item.get("student_id") or ident
                            emb = item.get("embedding")
                            if ident and emb:
                                vec = np.array(emb, dtype=np.float32)
                                norm = np.linalg.norm(vec)
                                if norm > 1e-6:
                                    vec = vec / norm
                                new_gallery[ident] = vec
                                new_names[ident] = name
                                new_ids[ident] = stu_id
                        self.gallery = new_gallery
                        self.student_names = new_names
                        self.student_ids = new_ids
                        if self.pipeline_ref and hasattr(self.pipeline_ref, "gallery"):
                            self.pipeline_ref.gallery = dict(self.gallery)
                        self._save_enrolled_gallery_file()
                        logger.info(
                            "Successfully synced %d identities from backend", len(gallery_list)
                        )
                        return True
        except Exception as exc:
            self._last_gallery_sync = time.time()
            logger.warning("Could not sync gallery from backend (%s): %s", url, exc)
        return False

    def _backend_url(self) -> str:
        if self.event_dispatcher is not None and hasattr(self.event_dispatcher, "backend_url"):
            return self.event_dispatcher.backend_url
        return os.getenv("BACKEND_URL", "http://backend:8000")

    async def _refresh_gallery_if_stale(self) -> None:
        """Re-sync from the backend when the gallery is empty or older than the refresh window."""
        age = time.time() - self._last_gallery_sync
        if age >= GALLERY_REFRESH_SECONDS or (not self.gallery and age >= 2.0):
            await self._sync_from_backend(self._backend_url())

    async def _handle_extract_embedding(self, request: web.Request) -> web.Response:
        import base64
        import cv2
        import numpy as np

        origin = request.headers.get("Origin")
        cors_headers = make_cors_headers(origin)

        content_type = request.content_type or ""
        img_bgr = None

        if "application/json" in content_type:
            try:
                data = await request.json()
                raw_b64 = data.get("image") or data.get("photo_base64") or data.get("frame") or ""
                if "," in raw_b64:
                    raw_b64 = raw_b64.split(",", 1)[1]
                if raw_b64:
                    img_bytes = base64.b64decode(raw_b64)
                    img_bgr = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
            except Exception as exc:
                logger.warning("Failed decoding json image: %s", exc)
        elif "multipart/form-data" in content_type:
            try:
                reader = await request.multipart()
                while True:
                    part = await reader.next()
                    if part is None:
                        break
                    if part.name in ("image", "file", "photo", "frame"):
                        raw_bytes = await part.read()
                        img_bgr = cv2.imdecode(np.frombuffer(raw_bytes, np.uint8), cv2.IMREAD_COLOR)
            except Exception as exc:
                logger.warning("Failed decoding multipart image: %s", exc)
        else:
            try:
                raw_bytes = await request.read()
                if raw_bytes:
                    img_bgr = cv2.imdecode(np.frombuffer(raw_bytes, np.uint8), cv2.IMREAD_COLOR)
            except Exception as exc:
                logger.warning("Failed decoding raw image: %s", exc)

        if img_bgr is None:
            return web.json_response(
                {"status": "error", "message": "Failed to decode image data"},
                status=400,
                headers=cors_headers,
            )

        app = self._get_app()
        if app is None:
            return web.json_response(
                {"status": "error", "message": "InsightFace models not loaded"},
                status=503,
                headers=cors_headers,
            )

        faces = app.get(img_bgr)
        if not faces:
            return web.json_response(
                {
                    "status": "no_face",
                    "message": "No face detected in photo. Please ensure face is clearly visible.",
                },
                status=200,
                headers=cors_headers,
            )

        best_face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        feat = getattr(best_face, "normed_embedding", None)
        if feat is None and hasattr(best_face, "embedding"):
            feat = best_face.embedding / (np.linalg.norm(best_face.embedding) + 1e-10)

        if feat is None:
            return web.json_response(
                {"status": "error", "message": "Failed to extract embedding vector"},
                status=500,
                headers=cors_headers,
            )

        det_score = float(best_face.det_score) if hasattr(best_face, "det_score") else 1.0

        return web.json_response(
            {
                "status": "ok",
                "embedding": feat.tolist(),
                "det_score": det_score,
                "bbox": [int(v) for v in best_face.bbox],
            },
            headers=cors_headers,
        )

    async def _handle_enroll_student(self, request: web.Request) -> web.Response:
        origin = request.headers.get("Origin")
        cors_headers = make_cors_headers(origin)
        try:
            data = await request.json()
            identity = data.get("identity")
            name = data.get("name") or identity
            student_id = data.get("student_id") or identity
            embedding = data.get("embedding")
            if not identity or not embedding:
                return web.json_response(
                    {"status": "error", "message": "Missing identity or embedding"},
                    status=400,
                    headers=cors_headers,
                )

            vec = np.array(embedding, dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm > 1e-6:
                vec = vec / norm

            self.gallery[identity] = vec
            self.student_names[identity] = name
            self.student_ids[identity] = student_id

            if self.pipeline_ref and hasattr(self.pipeline_ref, "gallery"):
                self.pipeline_ref.gallery[identity] = vec

            self._save_enrolled_gallery_file()

            logger.info(
                "Enrolled student %s (%s) into live gallery. Total identities: %d",
                name,
                identity,
                len(self.gallery),
            )
            return web.json_response(
                {
                    "status": "ok",
                    "enrolled": identity,
                    "name": name,
                    "total_gallery": len(self.gallery),
                },
                headers=cors_headers,
            )
        except Exception as exc:
            logger.exception("Enroll student failed: %s", exc)
            return web.json_response(
                {"status": "error", "message": str(exc)}, status=500, headers=cors_headers
            )

    async def _handle_reload_gallery(self, request: web.Request) -> web.Response:
        origin = request.headers.get("Origin")
        cors_headers = make_cors_headers(origin)
        try:
            data = None
            try:
                data = await request.json()
            except Exception:
                pass

            if data and "gallery" in data:
                for item in data["gallery"]:
                    ident = item.get("identity")
                    name = item.get("name") or ident
                    stu_id = item.get("student_id") or ident
                    emb = item.get("embedding")
                    if ident and emb:
                        vec = np.array(emb, dtype=np.float32)
                        norm = np.linalg.norm(vec)
                        if norm > 1e-6:
                            vec = vec / norm
                        self.gallery[ident] = vec
                        self.student_names[ident] = name
                        self.student_ids[ident] = stu_id
                self._save_enrolled_gallery_file()
                return web.json_response(
                    {
                        "status": "gallery_reloaded",
                        "enrolled_count": len(self.gallery),
                        "identities": list(self.gallery.keys()),
                    },
                    headers=cors_headers,
                )

            backend_url = os.getenv("BACKEND_URL", "http://backend:8000")
            if self.event_dispatcher and hasattr(self.event_dispatcher, "backend_url"):
                backend_url = self.event_dispatcher.backend_url

            synced = await self._sync_from_backend(backend_url)
            return web.json_response(
                {
                    "status": "gallery_reloaded",
                    "synced_from_backend": synced,
                    "enrolled_count": len(self.gallery),
                    "identities": list(self.gallery.keys()),
                },
                headers=cors_headers,
            )
        except Exception as exc:
            logger.exception("Reload gallery error: %s", exc)
            return web.json_response(
                {"status": "error", "message": str(exc)}, status=500, headers=cors_headers
            )

    async def _handle_get_gallery(self, request: web.Request) -> web.Response:
        origin = request.headers.get("Origin")
        cors_headers = make_cors_headers(origin)
        gallery = self._get_gallery()
        items = [
            {
                "identity": k,
                "name": self.student_names.get(k, k),
                "student_id": self.student_ids.get(k, k),
            }
            for k in gallery.keys()
        ]
        return web.json_response(
            {
                "count": len(items),
                "students": items,
            },
            headers=cors_headers,
        )

    async def _handle_process_frame(self, request: web.Request) -> web.Response:
        import base64
        import cv2
        import numpy as np

        origin = request.headers.get("Origin")
        headers = make_cors_headers(origin)
        content_type = request.content_type or ""
        req_session_id = request.query.get("session_id") or request.headers.get("X-Session-Id")
        img_bgr = None

        if "application/json" in content_type:
            try:
                data = await request.json()
                req_session_id = req_session_id or data.get("session_id")
                raw_b64 = data.get("image") or data.get("frame") or ""
                if "," in raw_b64:
                    raw_b64 = raw_b64.split(",", 1)[1]
                if raw_b64:
                    img_bytes = base64.b64decode(raw_b64)
                    img_bgr = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
            except Exception:
                pass
        elif "multipart/form-data" in content_type:
            try:
                reader = await request.multipart()
                while True:
                    part = await reader.next()
                    if part is None:
                        break
                    if part.name == "session_id":
                        req_session_id = (await part.text()).strip()
                    elif part.name in ("frame", "image", "file"):
                        raw_bytes = await part.read()
                        img_bgr = cv2.imdecode(np.frombuffer(raw_bytes, np.uint8), cv2.IMREAD_COLOR)
            except Exception:
                pass
        else:
            try:
                raw_bytes = await request.read()
                if raw_bytes:
                    img_bgr = cv2.imdecode(np.frombuffer(raw_bytes, np.uint8), cv2.IMREAD_COLOR)
            except Exception:
                pass

        if img_bgr is None:
            return web.json_response(
                {"status": "error", "message": "Failed to decode image frame"},
                status=400,
                headers=headers,
            )

        target_sess = req_session_id or self.active_session_id
        frame_h, frame_w = img_bgr.shape[:2]

        app = self._get_app()
        await self._refresh_gallery_if_stale()
        gallery = self._get_gallery()
        signing_key = os.getenv("RECOGNITION_SIGNING_KEY", "").strip()

        if app is None:
            return web.json_response(
                {"status": "error", "message": "Vision pipeline not initialized"},
                status=503,
                headers=headers,
            )

        faces = app.get(img_bgr)
        if not faces:
            ret, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ret:
                self.update_preview_frame(buf.tobytes())
            return web.json_response(
                {
                    "status": "ok",
                    "detected_faces": 0,
                    "recognized": False,
                    "identity": None,
                    "student_name": None,
                    "student_id": None,
                    "similarity": 0.0,
                    "margin": 0.0,
                    "already_marked": False,
                    "status_message": "No face detected",
                    "box": None,
                    "frame_width": frame_w,
                    "frame_height": frame_h,
                    "faces": [],
                },
                headers=headers,
            )

        pipe = self.pipeline_ref
        sim_thresh = getattr(pipe, "similarity_threshold", 0.50) if pipe else 0.50
        min_marg = getattr(pipe, "min_margin", 0.15) if pipe else 0.15

        faces_output = []

        for face in faces:
            bx1, by1, bx2, by2 = [int(v) for v in face.bbox]
            feat = getattr(face, "normed_embedding", None)
            if feat is None and hasattr(face, "embedding"):
                feat = face.embedding / (np.linalg.norm(face.embedding) + 1e-10)

            best_ident = None
            best_score = -1.0
            runner_up = -1.0

            if feat is not None and gallery:
                for ident, g_feat in gallery.items():
                    score = float(np.dot(feat, g_feat))
                    ident_stu_id = self.student_ids.get(ident, ident)
                    ident_stu_name = self.student_names.get(ident, ident)
                    if score > best_score:
                        if best_ident:
                            prev_id = self.student_ids.get(best_ident, best_ident)
                            prev_name = self.student_names.get(best_ident, best_ident)
                            if ident_stu_id != prev_id and ident_stu_name != prev_name:
                                runner_up = best_score
                        best_score = score
                        best_ident = ident
                    elif score > runner_up:
                        if best_ident:
                            best_id = self.student_ids.get(best_ident, best_ident)
                            best_name = self.student_names.get(best_ident, best_ident)
                            if ident_stu_id != best_id and ident_stu_name != best_name:
                                runner_up = score

            margin = best_score - runner_up if runner_up > 0 else best_score
            is_confirmed = (best_score >= sim_thresh) and (margin >= min_marg)
            det_score = float(getattr(face, "det_score", 1.0))

            if is_confirmed and best_ident:
                student_name = self.student_names.get(best_ident, best_ident)
                student_id = self.student_ids.get(best_ident, best_ident)
                self.last_recognized_student = student_name

                # This service never marks attendance. It returns a signed result
                # bound to the session; the backend verifies it and decides.
                recognition = None
                if target_sess and signing_key:
                    recognition = sign_recognition(
                        session_id=target_sess,
                        identity=best_ident,
                        confidence=best_score,
                        key=signing_key,
                    )

                conf_pct = round(best_score * 100, 1)
                faces_output.append(
                    {
                        "bbox": [bx1, by1, bx2, by2],
                        "identity": best_ident,
                        "student_id": student_id,
                        "name": student_name,
                        "similarity": round(best_score, 4),
                        "confidence_percent": conf_pct,
                        "det_score": round(det_score, 3),
                        "status": "recognized",
                        "already_marked": False,
                        "recognition": recognition,
                    }
                )

                cv2.rectangle(img_bgr, (bx1, by1), (bx2, by2), (0, 220, 0), 2)
                cv2.putText(
                    img_bgr,
                    f"{student_name} ({conf_pct}%)",
                    (bx1, max(24, by1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 220, 0),
                    2,
                )
            else:
                conf_pct = round(best_score * 100, 1) if best_score > 0 else 0.0
                faces_output.append(
                    {
                        "bbox": [bx1, by1, bx2, by2],
                        "identity": None,
                        "student_id": None,
                        "name": "UNKNOWN",
                        "similarity": round(best_score, 4) if best_score > 0 else 0.0,
                        "confidence_percent": conf_pct,
                        "det_score": round(det_score, 3),
                        "status": "unknown",
                        "already_marked": False,
                    }
                )

                cv2.rectangle(img_bgr, (bx1, by1), (bx2, by2), (0, 200, 255), 2)
                cv2.putText(
                    img_bgr,
                    f"UNKNOWN ({conf_pct}%)",
                    (bx1, max(24, by1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 200, 255),
                    2,
                )

        ret, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ret:
            self.update_preview_frame(buf.tobytes())

        recognized_faces = [f for f in faces_output if f["status"] == "recognized"]
        if recognized_faces:
            top_face = max(recognized_faces, key=lambda f: f["similarity"])
            return web.json_response(
                {
                    "status": "ok",
                    "detected_faces": len(faces),
                    "recognized": True,
                    "identity": top_face["identity"],
                    "student_name": top_face["name"],
                    "student_id": top_face["student_id"],
                    "similarity": top_face["similarity"],
                    "margin": round(margin, 4),
                    "already_marked": top_face["already_marked"],
                    "status_message": f"{top_face['name']} recognized",
                    "box": top_face["bbox"],
                    "frame_width": frame_w,
                    "frame_height": frame_h,
                    "faces": faces_output,
                },
                headers=headers,
            )
        else:
            primary_face = faces_output[0]
            return web.json_response(
                {
                    "status": "ok",
                    "detected_faces": len(faces),
                    "recognized": False,
                    "identity": "UNKNOWN",
                    "student_name": None,
                    "student_id": None,
                    "similarity": primary_face["similarity"],
                    "margin": 0.0,
                    "already_marked": False,
                    "status_message": "Scanning for enrolled student...",
                    "box": primary_face["bbox"],
                    "frame_width": frame_w,
                    "frame_height": frame_h,
                    "faces": faces_output,
                },
                headers=headers,
            )

    async def _handle_status(self, request: web.Request) -> web.Response:
        origin = request.headers.get("Origin")
        cors_headers = make_cors_headers(origin)

        if not self._is_authorized(request):
            return web.json_response(
                {"error": "Unauthorized: valid access token required"},
                status=401,
                headers=cors_headers,
            )

        source_id = getattr(self.video_source, "source_id", "BROWSER_WEBCAM")
        source_type = "WEBRTC" if "PHONE" in source_id else "BROWSER_WEBCAM"
        present_list = list(self.marked_identities)
        cam_active = (
            (time.time() - self.latest_frame_time < 5.0) if self.latest_frame_time > 0 else False
        )
        res = {
            "status": "online",
            "camera_active": cam_active,
            "camera_connected": True,
            "fps": round(getattr(self, "fps", 0.0), 1),
            "camera_name": "Browser Webcam (getUserMedia)",
            "backend": "Browser MediaStream",
            "active_session_id": self.active_session_id,
            "active_tracks": 0,
            "present_count": len(present_list),
            "present_students": present_list,
            "marked_students_count": len(present_list),
            "marked_students": present_list,
            "last_recognized": self.last_recognized_student,
            "last_recognized_student": self.last_recognized_student,
            "connection_state": getattr(self.receiver, "connection_state", "IDLE"),
            "received_frames": getattr(self.receiver, "received_frames", 0),
            "source_id": source_id,
            "source_type": source_type,
            "buffer_size": getattr(self.video_source, "buffer_size", 0),
            "dropped_frames": getattr(self.video_source, "dropped_frames", 0),
            "emitted_frames": getattr(self.video_source, "emitted_frame_count", 0),
            "last_frame_age_seconds": (
                round(time.time() - self.latest_frame_time, 2)
                if self.latest_frame_time > 0
                else None
            ),
        }
        if self.pipeline_ref and hasattr(self.pipeline_ref, "funnel"):
            res["funnel"] = self.pipeline_ref.funnel.to_dict()
        return web.json_response(res, headers=cors_headers)

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "healthy",
                "service": "webrtc-ingest",
                "auth_enabled": bool(self.access_token),
            },
        )

    def update_preview_frame(self, frame_jpeg: bytes, cv_result: Optional[Any] = None) -> None:
        """Update the latest annotated JPEG frame for the MJPEG stream."""
        self.latest_preview_jpeg = frame_jpeg
        self.latest_cv_result = cv_result
        self.latest_frame_time = time.time()

    def set_pipeline(self, pipeline: Any) -> None:
        """Set a reference to the active LiveCVPipeline instance."""
        self.pipeline_ref = pipeline
        if pipeline and hasattr(pipeline, "gallery"):
            self.gallery.update(pipeline.gallery)
            pipeline.gallery.update(self.gallery)

    def _get_standby_jpeg(self) -> bytes:
        """Generate a clean 640x360 placeholder frame when stream is idle."""
        import cv2
        import numpy as np

        img = np.zeros((360, 640, 3), dtype=np.uint8)
        img[:] = (24, 24, 24)
        cv2.putText(
            img,
            "CAMERA FEED READY (WAITING FOR PHONE STREAM)",
            (40, 160),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 200, 255),
            2,
        )
        cv2.putText(
            img,
            "Open phone browser and tap 'Start Camera Stream'",
            (85, 200),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (180, 180, 180),
            1,
        )
        ret, buf = cv2.imencode(".jpg", img)
        return buf.tobytes() if ret else b""

    async def _handle_preview_mjpg(self, request: web.Request) -> web.StreamResponse:
        """Serve live MJPEG stream for the Teacher UI preview panel."""
        if not self._is_authorized(request):
            return web.Response(text="Unauthorized", status=401)

        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "multipart/x-mixed-replace; boundary=frame",
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
                "Access-Control-Allow-Origin": "*",
            },
        )
        await response.prepare(request)

        standby_bytes = self._get_standby_jpeg()
        try:
            while not self._stop_event.is_set():
                frame_bytes = self.latest_preview_jpeg or standby_bytes
                if frame_bytes:
                    header = (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(frame_bytes)).encode("ascii") + b"\r\n\r\n"
                    )
                    await response.write(header + frame_bytes + b"\r\n")
                await asyncio.sleep(0.04)  # ~25 FPS
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        return response

    async def _handle_preview_jpg(self, request: web.Request) -> web.Response:
        """Serve a single snapshot frame as image/jpeg."""
        if not self._is_authorized(request):
            return web.Response(text="Unauthorized", status=401)

        frame_bytes = self.latest_preview_jpeg or self._get_standby_jpeg()
        return web.Response(
            body=frame_bytes,
            content_type="image/jpeg",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "no-cache, no-store, must-revalidate",
            },
        )

    async def _handle_funnel(self, request: web.Request) -> web.Response:
        """Serve the live 10-stage funnel counter metrics."""
        if not self._is_authorized(request):
            return web.json_response({"error": "Unauthorized"}, status=401)

        funnel_data = (
            self.pipeline_ref.funnel.to_dict()
            if (self.pipeline_ref and hasattr(self.pipeline_ref, "funnel"))
            else {}
        )
        return web.json_response(
            funnel_data,
        )

    def start_background(self) -> None:
        """Start the signaling server in a background daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        ready_event = threading.Event()

        def run_server():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            async def _start():
                self._runner = web.AppRunner(self.app)
                await self._runner.setup()
                self._site = web.TCPSite(self._runner, self.host, self.port)
                await self._site.start()
                logger.info(
                    "WebRTC Ingestion Server listening on http://%s:%d", self.host, self.port
                )
                ready_event.set()

                async def _delayed_sync():
                    await asyncio.sleep(2.0)
                    backend_url = os.getenv("BACKEND_URL", "http://backend:8000")
                    if self.event_dispatcher and hasattr(self.event_dispatcher, "backend_url"):
                        backend_url = self.event_dispatcher.backend_url
                    await self._sync_from_backend(backend_url)

                self._loop.create_task(_delayed_sync())

            self._loop.run_until_complete(_start())
            try:
                self._loop.run_forever()
            finally:
                self._loop.run_until_complete(self._cleanup())
                self._loop.close()

        self._thread = threading.Thread(
            target=run_server, daemon=True, name="WebRTCSignalingServer"
        )
        self._thread.start()
        ready_event.wait(timeout=5.0)

    async def _cleanup(self) -> None:
        await self.receiver.close()
        if self._runner is not None:
            await self._runner.cleanup()

    def stop(self) -> None:
        """Stop the background signaling server and release resources."""
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
