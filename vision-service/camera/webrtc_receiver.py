from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import threading
from typing import Any, Optional, Set

from aiohttp import web
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError
import av
import numpy as np

from camera.base import VideoFrame, VideoSourceType
from camera.phone_source import PhoneVideoSource

logger = logging.getLogger(__name__)


HTML_PHONE_CLIENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Vision Service — Phone Camera Ingest</title>
    <style>
        :root {
            --bg: #090d16;
            --card-bg: rgba(22, 30, 49, 0.7);
            --card-border: rgba(99, 102, 241, 0.25);
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
            padding: 12px 0 16px 0;
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
            background: rgba(0, 0, 0, 0.65);
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
        }

        .controls-card {
            width: 100%;
            max-width: 520px;
            margin-top: 16px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .btn-row {
            display: flex;
            gap: 10px;
        }

        button {
            flex: 1;
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

        .btn-secondary {
            background: rgba(255, 255, 255, 0.08);
            color: var(--text-main);
            border: 1px solid rgba(255, 255, 255, 0.15);
        }

        .btn-danger {
            background: linear-gradient(135deg, #ef4444, #dc2626);
            color: white;
        }

        .info-card {
            width: 100%;
            max-width: 520px;
            margin-top: 16px;
            padding: 14px 16px;
            background: rgba(15, 23, 42, 0.5);
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.06);
            font-size: 0.78rem;
            color: var(--text-muted);
            line-height: 1.4;
        }
    </style>
</head>
<body>
    <header>
        <div class="title-group">
            <h1>Mobile Live Ingest</h1>
            <p>Step 2D.2 WebRTC Video Source</p>
        </div>
        <div id="statusPill" class="status-pill">
            <span class="status-dot"></span>
            <span id="statusText">IDLE</span>
        </div>
    </header>

    <div class="viewport-card">
        <video id="localVideo" autoplay playsinline muted></video>
        <div class="overlay-stats" id="statsOverlay">
            <div>Source: <span id="statSource" style="color:#f8fafc">PHONE_CAM_01</span></div>
            <div>Resolution: <span id="statResolution" style="color:#f8fafc">-</span></div>
            <div>Sent: <span id="statFrames" style="color:#38bdf8">0</span> frames</div>
        </div>
    </div>

    <div class="controls-card">
        <button id="startBtn" class="btn-primary" onclick="startStreaming()">
            Start Camera Stream
        </button>
        <div class="btn-row">
            <button id="switchBtn" class="btn-secondary" onclick="switchCamera()">
                Switch Camera
            </button>
            <button id="stopBtn" class="btn-secondary btn-danger" onclick="stopStreaming()" disabled>
                Stop
            </button>
        </div>
    </div>

    <div class="info-card">
        Frames are streamed directly via WebRTC to the Vision Service receiver and ingested into <code>PhoneVideoSource</code> for real-time face detection & tracking.
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

        function setStatus(status, className) {
            statusText.innerText = status;
            statusPill.className = 'status-pill ' + (className || '');
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
                        setStatus('STREAMING LIVE', 'connected');
                    } else if (state === 'disconnected' || state === 'failed') {
                        setStatus('DISCONNECTED', 'error');
                    } else if (state === 'closed') {
                        setStatus('CLOSED', '');
                    }
                };

                // Add local camera track
                localStream.getTracks().forEach(track => {
                    peerConnection.addTrack(track, localStream);
                });

                // Create SDP Offer
                const offer = await peerConnection.createOffer();
                await peerConnection.setLocalDescription(offer);

                // Wait for complete ICE gathering before sending offer to receiver
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

                // Post Offer to Vision Service WebRTC receiver
                const response = await fetch('/offer', {
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

                // Track sent frames estimate
                frameCount = 0;
                clearInterval(statsInterval);
                statsInterval = setInterval(() => {
                    if (peerConnection && peerConnection.connectionState === 'connected') {
                        frameCount += 15; // Approximate client broadcast rate
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
            except Exception:
                pass

    async def _cleanup_active_connections(self) -> None:
        """Cancel lingering tasks and close peer connections."""
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()

        for pc in list(self._pcs):
            try:
                await pc.close()
            except Exception:
                pass
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
    ) -> None:
        self.video_source = video_source
        self.host = host
        self.port = port
        self.receiver = WebRTCReceiver(video_source=video_source, source_id=video_source.source_id)

        self.app = web.Application()
        self.app.router.add_get("/", self._handle_index)
        self.app.router.add_post("/offer", self._handle_offer)
        self.app.router.add_get("/status", self._handle_status)
        self.app.router.add_get("/health", self._handle_health)

        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event = threading.Event()

    async def _handle_index(self, request: web.Request) -> web.Response:
        return web.Response(text=HTML_PHONE_CLIENT, content_type="text/html")

    async def _handle_offer(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            if "sdp" not in data or "type" not in data:
                return web.json_response({"error": "Invalid offer payload"}, status=400)

            answer = await self.receiver.handle_offer(data)
            return web.json_response(answer)
        except Exception as exc:
            logger.exception("Failed to process WebRTC offer")
            return web.json_response({"error": str(exc)}, status=500)

    async def _handle_status(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "online",
            "connection_state": self.receiver.connection_state,
            "received_frames": self.receiver.received_frames,
            "source_id": self.video_source.source_id,
            "source_type": self.video_source.source_type.value,
            "buffer_size": self.video_source.buffer_size,
            "dropped_frames": self.video_source.dropped_frames,
            "emitted_frames": self.video_source.emitted_frame_count,
        })

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "healthy", "service": "webrtc-ingest"})

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
                logger.info("WebRTC Ingestion Server listening on http://%s:%d", self.host, self.port)
                ready_event.set()

            self._loop.run_until_complete(_start())
            try:
                self._loop.run_forever()
            finally:
                self._loop.run_until_complete(self._cleanup())
                self._loop.close()

        self._thread = threading.Thread(target=run_server, daemon=True, name="WebRTCSignalingServer")
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
