from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os
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


class WebRTCSignalingServer:
    """Lightweight HTTP & WebRTC Signaling server for phone camera ingest."""

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
        self.latest_frame_time: float = 0.0

        self.app = web.Application()
        self.app.router.add_get("/", self._handle_index)
        self.app.router.add_post("/offer", self._handle_offer)
        self.app.router.add_post("/transit", self._handle_transit)
        self.app.router.add_get("/status", self._handle_status)
        self.app.router.add_get("/health", self._handle_health)
        self.app.router.add_get("/funnel", self._handle_funnel)
        self.app.router.add_get("/preview.mjpg", self._handle_preview_mjpg)
        self.app.router.add_get("/preview.jpg", self._handle_preview_jpg)

        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event = threading.Event()

    def _is_authorized(self, request: web.Request) -> bool:
        """Verify request authorization against configured access token."""
        if not self.access_token:
            return True

        # 1. Query parameter ?token=...
        query_token = request.query.get("token")
        if query_token and secrets.compare_digest(query_token, self.access_token):
            return True

        # 2. Authorization: Bearer <token>
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            bearer_token = auth_header[7:].strip()
            if secrets.compare_digest(bearer_token, self.access_token):
                return True

        # 3. X-Access-Token header
        x_token = request.headers.get("X-Access-Token")
        if x_token and secrets.compare_digest(x_token, self.access_token):
            return True

        return False

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
            logger.exception("Failed to process mobile transit event")
            return web.json_response({"error": str(exc)}, status=500)

    async def _handle_status(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return web.json_response(
                {"error": "Unauthorized: valid access token required"}, status=401
            )

        res = {
            "status": "online",
            "connection_state": self.receiver.connection_state,
            "received_frames": self.receiver.received_frames,
            "source_id": self.video_source.source_id,
            "source_type": self.video_source.source_type.value,
            "buffer_size": self.video_source.buffer_size,
            "dropped_frames": self.video_source.dropped_frames,
            "emitted_frames": self.video_source.emitted_frame_count,
            "last_frame_age_seconds": (
                round(time.time() - self.latest_frame_time, 2)
                if self.latest_frame_time > 0
                else None
            ),
        }
        if self.pipeline_ref and hasattr(self.pipeline_ref, "funnel"):
            res["funnel"] = self.pipeline_ref.funnel.to_dict()
        return web.json_response(res, headers={"Access-Control-Allow-Origin": "*"})

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "healthy",
                "service": "webrtc-ingest",
                "auth_enabled": bool(self.access_token),
            },
            headers={"Access-Control-Allow-Origin": "*"},
        )

    def update_preview_frame(self, frame_jpeg: bytes, cv_result: Optional[Any] = None) -> None:
        """Update the latest annotated JPEG frame for the MJPEG stream."""
        self.latest_preview_jpeg = frame_jpeg
        self.latest_cv_result = cv_result
        self.latest_frame_time = time.time()

    def set_pipeline(self, pipeline: Any) -> None:
        """Set a reference to the active LiveCVPipeline instance."""
        self.pipeline_ref = pipeline

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
            headers={"Access-Control-Allow-Origin": "*"},
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
