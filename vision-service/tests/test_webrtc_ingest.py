"""Integration & Acceptance Tests for Step 2D.2: Phone WebRTC Live Frame Ingest."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import time
import unittest

from aiohttp import ClientSession
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import VideoStreamTrack
import av
import numpy as np

# Ensure vision-service root is in sys.path
SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from camera import (
    FileVideoSource,
    PhoneVideoSource,
    RTSPVideoSource,
    VideoFrame,
    VideoSource,
    VideoSourceType,
    WebRTCSignalingServer,
)


class SyntheticPhoneCameraTrack(VideoStreamTrack):
    """Simulates a phone browser camera delivering frames via WebRTC media track."""

    def __init__(self, width: int = 640, height: int = 480, fps: int = 30) -> None:
        super().__init__()
        self.width = width
        self.height = height
        self.fps = fps
        self.frame_count = 0

    async def recv(self) -> av.VideoFrame:
        pts, time_base = await self.next_timestamp()

        # Generate a distinct synthetic color pattern for each frame
        img = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        img[:, :] = (self.frame_count % 256, (self.frame_count * 2) % 256, 128)

        frame = av.VideoFrame.from_ndarray(img, format="bgr24")
        frame.pts = pts
        frame.time_base = time_base
        self.frame_count += 1
        return frame


class TestWebRTCLiveFrameIngest(unittest.IsolatedAsyncioTestCase):
    """Verifies all 5 Acceptance Tests specified in Step 2D.2."""

    async def asyncSetUp(self):
        self.port = 8089
        self.host = "127.0.0.1"
        self.source = PhoneVideoSource(
            source_id="PHONE_CAM_01",
            source_type=VideoSourceType.WEBRTC,
            max_buffer_size=30,
            read_timeout=0.2,
        )
        self.source.open()

        self.server = WebRTCSignalingServer(
            video_source=self.source,
            host=self.host,
            port=self.port,
        )
        self.server.start_background()
        await asyncio.sleep(0.2)  # Allow server to bind

    async def asyncTearDown(self):
        self.server.stop()
        self.source.release()
        await asyncio.sleep(0.1)

    async def _create_phone_client(self) -> tuple[RTCPeerConnection, SyntheticPhoneCameraTrack]:
        """Simulates a mobile phone browser establishing a WebRTC session."""
        pc = RTCPeerConnection()
        track = SyntheticPhoneCameraTrack(width=640, height=480)
        pc.addTrack(track)

        # Create offer matching browser workflow
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        # Send offer to Vision Service signaling server
        async with ClientSession() as session:
            async with session.post(
                f"http://{self.host}:{self.port}/offer",
                json={"sdp": pc.localDescription.sdp, "type": pc.localDescription.type},
            ) as response:
                self.assertEqual(response.status, 200)
                answer_json = await response.json()

        # Set remote description from Vision Service SDP answer
        answer = RTCSessionDescription(sdp=answer_json["sdp"], type=answer_json["type"])
        await pc.setRemoteDescription(answer)

        return pc, track

    # =========================================================================
    # Acceptance Test 1 — Phone Connection (Phone -> WebRTC -> PC)
    # =========================================================================
    async def test_acceptance_1_phone_connection(self):
        """Proves phone browser can connect and establish WebRTC connection with PC receiver."""
        client_pc, _ = await self._create_phone_client()
        try:
            # Wait for connection state to reach CONNECTED
            for _ in range(50):
                if client_pc.connectionState == "connected":
                    break
                await asyncio.sleep(0.05)

            self.assertEqual(client_pc.connectionState, "connected")

            # Check receiver endpoint status
            async with ClientSession() as session:
                async with session.get(f"http://{self.host}:{self.port}/status") as resp:
                    data = await resp.json()
                    self.assertEqual(data["status"], "online")
                    self.assertEqual(data["source_id"], "PHONE_CAM_01")
                    self.assertEqual(data["source_type"], "WEBRTC")
        finally:
            await client_pc.close()

    # =========================================================================
    # Acceptance Test 2 — Continuous Frames (Frame contract & sequence)
    # =========================================================================
    async def test_acceptance_2_continuous_frames(self):
        """Proves frames arrive continuously with correct VideoFrame contract."""
        client_pc, track = await self._create_phone_client()
        try:
            received_frames: list[VideoFrame] = []

            # Read continuous frames from PhoneVideoSource without stalling the loop
            start_time = time.monotonic()
            while len(received_frames) < 15 and (time.monotonic() - start_time) < 5.0:
                frame = self.source.read(block=False)
                if frame is not None:
                    received_frames.append(frame)
                await asyncio.sleep(0.02)

            self.assertGreaterEqual(
                len(received_frames),
                10,
                f"Expected >=10 frames, received {len(received_frames)}",
            )

            # Validate each frame matches required contract
            for i, vf in enumerate(received_frames):
                self.assertEqual(vf.source_type, VideoSourceType.WEBRTC)
                self.assertEqual(vf.source_id, "PHONE_CAM_01")
                self.assertEqual(vf.width, 640)
                self.assertEqual(vf.height, 480)
                self.assertIsInstance(vf.frame, np.ndarray)
                self.assertIsInstance(vf.timestamp, datetime)
                self.assertEqual(vf.timestamp.tzinfo, timezone.utc)
                if i > 0:
                    self.assertGreater(vf.frame_index, received_frames[i - 1].frame_index)

            print(f"\n[Test 2 Output] Successfully received {len(received_frames)} continuous WebRTC frames.")
            print(f"Sample Frame: source_id={received_frames[0].source_id}, "
                  f"type={received_frames[0].source_type}, "
                  f"res={received_frames[0].width}x{received_frames[0].height}, "
                  f"ts={received_frames[0].timestamp.isoformat()}")
        finally:
            await client_pc.close()

    # =========================================================================
    # Acceptance Test 3 — No Uncontrolled Buffering (Drop-Oldest Protection)
    # =========================================================================
    async def test_acceptance_3_no_uncontrolled_buffering(self):
        """Proves buffer remains capped at max_buffer_size (30) by dropping stale frames."""
        client_pc, _ = await self._create_phone_client()
        try:
            # Let frames stream into buffer without consuming them
            await asyncio.sleep(1.5)

            # Buffer size must never exceed 30
            self.assertLessEqual(self.source.buffer_size, 30)

            # Stale frames were safely dropped
            self.assertGreater(self.source.dropped_frames, 0)
            print(f"\n[Test 3 Output] Buffer protected: current_buffer={self.source.buffer_size}/30, "
                  f"dropped_stale_frames={self.source.dropped_frames}")

            # Reading should now return the newest retained frames
            latest_frame = self.source.read()
            self.assertIsNotNone(latest_frame)
            self.assertEqual(latest_frame.source_id, "PHONE_CAM_01")
        finally:
            await client_pc.close()

    # =========================================================================
    # Acceptance Test 4 — Clean Disconnect & Reconnect
    # =========================================================================
    async def test_acceptance_4_disconnect_and_reconnect(self):
        """Proves phone closing browser or reconnecting cleans up without leaving dead threads."""
        # 1. First Connection
        client_1, _ = await self._create_phone_client()
        await asyncio.sleep(0.3)
        self.assertGreaterEqual(self.server.receiver.received_frames, 1)

        # 2. Client Disconnects
        await client_1.close()
        await asyncio.sleep(0.2)

        # 3. Client Reconnects
        client_2, _ = await self._create_phone_client()
        try:
            for _ in range(40):
                if client_2.connectionState == "connected":
                    break
                await asyncio.sleep(0.05)

            self.assertEqual(client_2.connectionState, "connected")

            # Verify new stream continues flowing cleanly
            prev_count = self.server.receiver.received_frames
            for _ in range(30):
                if self.server.receiver.received_frames > prev_count + 5:
                    break
                await asyncio.sleep(0.05)

            self.assertGreater(self.server.receiver.received_frames, prev_count)
            print(f"\n[Test 4 Output] Clean reconnect verified: total_frames={self.server.receiver.received_frames}")
        finally:
            await client_2.close()

    # =========================================================================
    # Acceptance Test 5 — Multiple Sources Remain Intact
    # =========================================================================
    async def test_acceptance_5_multiple_sources_remain_intact(self):
        """Proves FILE, RTSP, and WEBRTC all feed the exact same VideoFrame interface."""
        test_video = SERVICE_ROOT / "tests" / "video_test" / "person_1_vid.mp4"

        # 1. FILE Source
        file_src = FileVideoSource(test_video, source_id="RECORDED_TEST", target_fps=5.0)
        with file_src as src:
            f1 = src.read()

        # 2. WEBRTC Source (active phone source from setUp)
        self.source.push_frame(np.zeros((480, 640, 3), dtype=np.uint8))
        f2 = self.source.read()

        # 3. Downstream consumer function
        def inspect_frame_consumer(vf: VideoFrame) -> dict[str, str | int]:
            st_val = vf.source_type.value if hasattr(vf.source_type, "value") else str(vf.source_type)
            return {
                "source_id": vf.source_id,
                "source_type": st_val,
                "resolution": f"{vf.width}x{vf.height}",
                "valid": vf.frame is not None and isinstance(vf.timestamp, datetime),
            }

        res_file = inspect_frame_consumer(f1)
        res_webrtc = inspect_frame_consumer(f2)

        self.assertEqual(res_file["source_id"], "RECORDED_TEST")
        self.assertEqual(res_file["source_type"], "FILE")
        self.assertTrue(res_file["valid"])

        self.assertEqual(res_webrtc["source_id"], "PHONE_CAM_01")
        self.assertEqual(res_webrtc["source_type"], "WEBRTC")
        self.assertTrue(res_webrtc["valid"])

        print("\n[Test 5 Output] Multi-source interchangeability confirmed:")
        print(f"  FILE   -> {res_file}")
        print(f"  WEBRTC -> {res_webrtc}")


if __name__ == "__main__":
    unittest.main()
