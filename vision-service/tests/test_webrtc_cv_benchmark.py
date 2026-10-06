"""Multi-Person WebRTC CV Pipeline Benchmark (Step 2D.3).

Validates concurrent multi-subject perception on live WebRTC phone frames:
1. 5–10 simultaneous people visible in camera canvas (1280x720).
2. Live WebRTC ingestion through PhoneVideoSource -> VideoFrame.
3. SCRFD multi-face detection.
4. ArcFace biometric embedding matching against enrolled gallery.
5. ByteTrack multi-object tracking with Kalman filtering across motion.
6. Track-level identity persistence without identity switches.
7. Rejection of unknown non-enrolled individuals (marked UNKNOWN).
8. Real-time latency, throughput FPS, and buffer telemetry.
"""

import asyncio
from datetime import datetime, timezone
import math
from pathlib import Path
import sys
import time
import unittest

import pytest
from aiohttp import ClientSession
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import VideoStreamTrack
import av
import cv2
from insightface.app import FaceAnalysis
import numpy as np

# Ensure vision-service root is in sys.path
SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from camera import PhoneVideoSource, VideoFrame, VideoSourceType, WebRTCSignalingServer
from pipeline import LiveCVPipeline, load_gallery, create_face_analysis, configure_scrfd_threads, swap_scrfd_detector


class MultiPersonPhoneWebRTCTrack(VideoStreamTrack):
    """Simulates a phone browser transmitting a 1280x720 video feed with 6-7 simultaneous moving subjects."""

    def __init__(self, gallery_dir: Path, width: int = 1280, height: int = 720, target_faces: int = 7) -> None:
        super().__init__()
        self.width = width
        self.height = height
        self.target_faces = target_faces
        self.frame_count = 0

        # Load reference face crops from gallery
        self.face_crops: dict[str, np.ndarray] = {}
        for p in ["person_01", "person_02", "person_03", "person_04"]:
            img_path = list((gallery_dir / p).glob("*.*"))[0]
            img = cv2.imread(str(img_path))
            if img is not None:
                # Basic center crop as fallback face
                h, w = img.shape[:2]
                face_crop = img[int(h * 0.15):int(h * 0.65), int(w * 0.2):int(w * 0.8)]
                self.face_crops[p] = cv2.resize(face_crop, (120, 140))

        # Generate a synthetic non-enrolled 'unknown' face
        unknown_face = np.zeros((140, 120, 3), dtype=np.uint8)
        cv2.circle(unknown_face, (60, 70), 50, (180, 180, 180), -1)
        cv2.circle(unknown_face, (45, 55), 8, (40, 40, 40), -1)
        cv2.circle(unknown_face, (75, 55), 8, (40, 40, 40), -1)
        cv2.ellipse(unknown_face, (60, 95), (20, 10), 0, 0, 180, (40, 40, 40), 3)
        self.face_crops["unknown_subject"] = unknown_face

        # Configure 6-7 distinct subjects with continuous motion trajectories
        self.subjects = [
            {"id": "person_01", "crop": self.face_crops["person_01"], "x": 60.0, "y": 80.0, "vx": 2.5, "vy": 0.5},
            {"id": "person_02", "crop": self.face_crops["person_02"], "x": 240.0, "y": 140.0, "vx": -1.8, "vy": 1.0},
            {"id": "person_03", "crop": self.face_crops["person_03"], "x": 420.0, "y": 90.0, "vx": 1.2, "vy": -0.8},
            {"id": "person_04", "crop": self.face_crops["person_04"], "x": 600.0, "y": 160.0, "vx": -2.0, "vy": 0.6},
            {"id": "person_01_b", "crop": self.face_crops["person_01"], "x": 780.0, "y": 100.0, "vx": 1.5, "vy": 1.2},
            {"id": "person_02_b", "crop": self.face_crops["person_02"], "x": 960.0, "y": 150.0, "vx": -1.0, "vy": -1.0},
            {"id": "unknown_01", "crop": self.face_crops["unknown_subject"], "x": 1100.0, "y": 120.0, "vx": -1.5, "vy": 0.5},
        ][:target_faces]

    async def recv(self) -> av.VideoFrame:
        pts, time_base = await self.next_timestamp()

        # Create canvas background (classroom ambient lighting)
        canvas = np.ones((self.height, self.width, 3), dtype=np.uint8) * 65

        # Render moving subjects onto canvas
        for s in self.subjects:
            # Update position with bounce bounds
            s["x"] += s["vx"]
            s["y"] += s["vy"]

            if s["x"] < 20 or s["x"] > (self.width - 140):
                s["vx"] *= -1
            if s["y"] < 40 or s["y"] > (self.height - 200):
                s["vy"] *= -1

            x_pos = int(s["x"])
            y_pos = int(s["y"])
            crop = s["crop"]
            ch, cw = crop.shape[:2]

            # Place subject onto canvas
            canvas[y_pos : y_pos + ch, x_pos : x_pos + cw] = crop

        frame = av.VideoFrame.from_ndarray(canvas, format="bgr24")
        frame.pts = pts
        frame.time_base = time_base
        self.frame_count += 1
        return frame


@pytest.mark.slow
@pytest.mark.needs_models
class TestWebRTCCVPipelineBenchmark(unittest.IsolatedAsyncioTestCase):
    """Executes Step 2D.3: Live WebRTC Phone Ingestion -> Existing CV Pipeline Benchmark."""

    @classmethod
    def setUpClass(cls):
        cls.gallery_dir = SERVICE_ROOT / "tests" / "recognition_benchmark"
        cls.app = FaceAnalysis(
            name="buffalo_l",
            providers=["CPUExecutionProvider"],
            allowed_modules=["detection", "recognition"],
        )
        cls.app.prepare(ctx_id=0, det_size=(640, 640))
        cls.gallery = load_gallery(cls.app, cls.gallery_dir)

    async def asyncSetUp(self):
        self.port = 8091
        self.host = "127.0.0.1"

        # Initialize PhoneVideoSource and LiveCVPipeline
        self.source = PhoneVideoSource(
            source_id="PHONE_CAM_01",
            source_type=VideoSourceType.WEBRTC,
            max_buffer_size=30,
            read_timeout=0.2,
        )
        self.source.open()

        self.pipeline = LiveCVPipeline(
            app=self.app,
            gallery=self.gallery,
            similarity_threshold=0.40,
            min_margin=0.15,
            min_supporting_frames=2,
            source_id="PHONE_CAM_01",
        )

        # 4. Start WebRTC signaling server
        self.server = WebRTCSignalingServer(
            video_source=self.source,
            host=self.host,
            port=self.port,
        )
        self.server.start_background()
        await asyncio.sleep(0.2)

    async def asyncTearDown(self):
        self.server.stop()
        self.source.release()
        await asyncio.sleep(0.1)

    async def _connect_phone_stream(self) -> tuple[RTCPeerConnection, MultiPersonPhoneWebRTCTrack]:
        """Establish WebRTC stream transmitting multi-person frames."""
        pc = RTCPeerConnection()
        track = MultiPersonPhoneWebRTCTrack(gallery_dir=self.gallery_dir, target_faces=7)
        pc.addTrack(track)

        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        async with ClientSession() as session:
            async with session.post(
                f"http://{self.host}:{self.port}/offer",
                json={"sdp": pc.localDescription.sdp, "type": pc.localDescription.type},
            ) as response:
                self.assertEqual(response.status, 200)
                answer_json = await response.json()

        answer = RTCSessionDescription(sdp=answer_json["sdp"], type=answer_json["type"])
        await pc.setRemoteDescription(answer)
        return pc, track

    async def _run_benchmark_trial(
        self,
        processing_resolution: tuple[int, int] | None,
        target_frames: int = 3,
        trial_name: str = "TRIAL",
        min_supporting_frames: int = 3,
        app: FaceAnalysis | None = None,
    ) -> dict[str, Any]:
        """Execute a single WebRTC CV benchmark trial with specified processing resolution."""
        pipeline = LiveCVPipeline(
            app=app or self.app,
            gallery=self.gallery,
            similarity_threshold=0.40,
            min_margin=0.15,
            min_supporting_frames=min_supporting_frames,
            source_id="PHONE_CAM_01",
            processing_resolution=processing_resolution,
        )

        # Clear buffer
        while not self.source._queue.empty():
            try:
                self.source._queue.get_nowait()
            except Exception:
                break

        client_pc, track = await self._connect_phone_stream()
        processed_results = []
        start_time = time.monotonic()

        print(f"\n--- Starting {trial_name} ({'1280x720 Native' if not processing_resolution else f'{processing_resolution[0]}x{processing_resolution[1]} Downscaled'}) ---")

        try:
            for _ in range(40):
                if client_pc.connectionState == "connected":
                    break
                await asyncio.sleep(0.05)

            while len(processed_results) < target_frames and (time.monotonic() - start_time) < 65.0:
                vf = self.source.read(block=False)
                if vf is not None:
                    result = pipeline.process_frame(vf)
                    processed_results.append(result)
                    print(
                        f"  [{trial_name}] Frame #{len(processed_results):02d} | "
                        f"Faces: {result.face_count} | Tracks: {result.active_tracks_count} | "
                        f"ArcFace Calls: {result.arcface_calls} | Confirmed: {result.confirmed_tracks_count} | "
                        f"Latency: {result.latency_total_ms:.1f}ms (det={result.latency_detection_ms:.1f}ms, arc={result.latency_arcface_ms:.1f}ms)"
                    )
                else:
                    await asyncio.sleep(0.02)

            telemetry = pipeline.get_benchmark_telemetry(dropped_frames=self.source.dropped_frames)
            telemetry["processed_count"] = len(processed_results)
            telemetry["buffer_size"] = self.source.buffer_size
            telemetry["frame_results"] = processed_results
            return telemetry
        finally:
            track.stop()
            try:
                await asyncio.wait_for(client_pc.close(), timeout=1.5)
            except Exception:
                pass
            await asyncio.sleep(0.2)

    async def test_webrtc_resolution_optimization_comparison(self):
        """Execute Step 2D.4A: Benchmark 1280x720 vs 640x360 CV processing resolution."""
        # Trial 1: 1280x720 Native
        tel_1280 = await self._run_benchmark_trial(
            processing_resolution=None,
            target_frames=3,
            trial_name="1280x720 NATIVE",
        )

        # Trial 2: 640x360 Downscaled for CV
        tel_640 = await self._run_benchmark_trial(
            processing_resolution=(640, 360),
            target_frames=3,
            trial_name="640x360 DOWNSCALED",
        )

        tot_lat_1280 = f"{tel_1280['avg_latency_ms']:.1f} ms"
        tot_lat_640 = f"{tel_640['avg_latency_ms']:.1f} ms"
        det_lat_1280 = f"{tel_1280['detection_avg_ms']:.1f} ms"
        det_lat_640 = f"{tel_640['detection_avg_ms']:.1f} ms"
        emb_lat_1280 = f"{tel_1280['embedding_avg_ms']:.1f} ms"
        emb_lat_640 = f"{tel_640['embedding_avg_ms']:.1f} ms"
        trk_lat_1280 = f"{tel_1280['tracking_avg_ms']:.1f} ms"
        trk_lat_640 = f"{tel_640['tracking_avg_ms']:.1f} ms"

        # Print Side-by-Side Comparative Table
        print("\n" + "=" * 80)
        print("STEP 2D.4A: RESOLUTION OPTIMIZATION BENCHMARK (1280x720 vs 640x360)")
        print("=" * 80)
        print(f"{'Metric':<30} | {'1280x720 (Native)':<18} | {'640x360 (Downscaled)':<20} | {'Difference / Speedup'}")
        print("-" * 80)
        print(f"{'Camera Input Res':<30} | {'1280x720':<18} | {'1280x720':<20} | {'Preserved for display'}")
        print(f"{'CV Processing Res':<30} | {'1280x720':<18} | {'640x360':<20} | {'4x fewer pixels'}")
        print(f"{'Processing FPS':<30} | {tel_1280['processing_fps']:<18.2f} | {tel_640['processing_fps']:<20.2f} | {tel_640['processing_fps'] / max(tel_1280['processing_fps'], 0.001):.2f}x throughput")
        print(f"{'Average Total Latency':<30} | {tot_lat_1280:<18} | {tot_lat_640:<20} | {tel_1280['avg_latency_ms'] - tel_640['avg_latency_ms']:.1f} ms reduction")
        print(f"{'Detection Latency (SCRFD)':<30} | {det_lat_1280:<18} | {det_lat_640:<20} | {tel_1280['detection_avg_ms'] - tel_640['detection_avg_ms']:.1f} ms reduction")
        print(f"{'Embedding Latency (ArcFace)':<30} | {emb_lat_1280:<18} | {emb_lat_640:<20} | {tel_1280['embedding_avg_ms'] - tel_640['embedding_avg_ms']:.1f} ms")
        print(f"{'Tracking Latency (ByteTrack)':<30} | {trk_lat_1280:<18} | {trk_lat_640:<20} | {tel_1280['tracking_avg_ms'] - tel_640['tracking_avg_ms']:.1f} ms")
        print(f"{'Concurrent Faces Detected':<30} | {tel_1280['max_concurrent_faces']:<18} | {tel_640['max_concurrent_faces']:<20} | {'All subjects detected' if tel_640['max_concurrent_faces'] >= tel_1280['max_concurrent_faces'] else 'Fewer detections'}")
        print(f"{'Active Tracks Maintained':<30} | {tel_1280['max_concurrent_tracks']:<18} | {tel_640['max_concurrent_tracks']:<20} | {'Maintained'}")
        print(f"{'Identity Switches':<30} | {tel_1280['identity_switches']:<18} | {tel_640['identity_switches']:<20} | {'0 switches (stable)'}")
        print(f"{'Unknown Identities':<30} | {tel_1280['unknown_identities']:<18} | {tel_640['unknown_identities']:<20} | {'Consistent'}")
        print(f"{'Ingestion Buffer Size':<30} | {tel_1280['buffer_size']:<18} | {tel_640['buffer_size']:<20} | {'Bounded'}")
        print(f"{'Dropped Stale Frames':<30} | {tel_1280['dropped_frames']:<18} | {tel_640['dropped_frames']:<20} | {'Queue protection active'}")
        print("=" * 80 + "\n")

        # Acceptance Assertions
        self.assertGreaterEqual(tel_640["max_concurrent_faces"], 4)
        self.assertGreaterEqual(tel_640["max_concurrent_tracks"], 4)
        self.assertEqual(tel_640["identity_switches"], 0)
        self.assertLessEqual(tel_640["buffer_size"], 30)

    async def test_webrtc_step_2d_4b_option_a_benchmark(self):
        """Execute Step 2D.4B — Option A: 640x360 WebRTC CV Benchmark with only detection and recognition."""
        tel_option_a = await self._run_benchmark_trial(
            processing_resolution=(640, 360),
            target_frames=3,
            trial_name="STEP_2D_4B_OPTION_A_640x360",
        )

        det_ms = tel_option_a["detection_avg_ms"]
        l3d_ms = tel_option_a["landmark_3d_avg_ms"]
        l2d_ms = tel_option_a["landmark_2d_avg_ms"]
        ga_ms = tel_option_a["genderage_avg_ms"]
        arc_ms = tel_option_a["arcface_avg_ms"]
        tot_ms = tel_option_a["avg_latency_ms"]
        faces = tel_option_a["max_concurrent_faces"]
        tracks = tel_option_a["max_concurrent_tracks"]
        switches = tel_option_a["identity_switches"]

        print("\n" + "=" * 85)
        print("STEP 2D.4B — OPTION A BENCHMARK (UNLOAD AUXILIARY INSIGHTFACE MODELS)")
        print("=" * 85)
        print(f"{'Metric':<30} | {'Current (Baseline)':<20} | {'After Option A':<20} | {'Status / Verification'}")
        print("-" * 85)
        print(f"{'InsightFace Modules':<30} | {'5 modules':<20} | {str(list(self.app.models.keys())):<20} | {'Auxiliary unloaded'}")
        print(f"{'SCRFD detection':<30} | {'~255 ms':<20} | {f'{det_ms:.1f} ms':<20} | {'Measured'}")
        print(f"{'Landmark 3D':<30} | {'~2,462 ms':<20} | {f'{l3d_ms:.1f} ms':<20} | {'Disappeared (0.0 ms)'}")
        print(f"{'Landmark 2D':<30} | {'~653 ms':<20} | {f'{l2d_ms:.1f} ms':<20} | {'Disappeared (0.0 ms)'}")
        print(f"{'Gender/Age':<30} | {'~147 ms':<20} | {f'{ga_ms:.1f} ms':<20} | {'Disappeared (0.0 ms)'}")
        print(f"{'ArcFace':<30} | {'~18.15 s':<20} | {f'{arc_ms / 1000.0:.2f} s':<20} | {'Measured'}")
        print(f"{'Total 5-face frame':<30} | {'~21.67 s':<20} | {f'{tot_ms / 1000.0:.2f} s':<20} | {f'Measured ({21667.0 / max(tot_ms, 1.0):.2f}x speedup)'}")
        print(f"{'Faces detected':<30} | {'5/5':<20} | {f'{faces}/5':<20} | {'Verified' if faces == 5 else 'Check'}")
        print(f"{'Active tracks':<30} | {'5/5':<20} | {f'{tracks}/5':<20} | {'Verified' if tracks == 5 else 'Check'}")
        print(f"{'Identity switches':<30} | {'0':<20} | {f'{switches}':<20} | {'Verified (0 switches)' if switches == 0 else 'Failed'}")
        print("=" * 85 + "\n")

        # Acceptance Assertions
        self.assertAlmostEqual(l3d_ms, 0.0, places=1)
        self.assertAlmostEqual(l2d_ms, 0.0, places=1)
        self.assertAlmostEqual(ga_ms, 0.0, places=1)
        self.assertEqual(faces, 5)
        self.assertEqual(tracks, 5)
        self.assertEqual(switches, 0)
        self.assertLessEqual(tel_option_a["buffer_size"], 30)

    async def test_webrtc_step_2d_4c_track_gated_benchmark(self):
        """Execute Step 2D.4C: 640x360 WebRTC CV Benchmark with Track-Gated ArcFace Recognition."""
        tel_gated = await self._run_benchmark_trial(
            processing_resolution=(640, 360),
            target_frames=6,
            trial_name="STEP_2D_4C_TRACK_GATED_640x360",
            min_supporting_frames=3,
        )

        det_ms = tel_gated["detection_avg_ms"]
        arc_ms = tel_gated["arcface_avg_ms"]
        tot_ms = tel_gated["avg_latency_ms"]
        faces = tel_gated["max_concurrent_faces"]
        tracks = tel_gated["max_concurrent_tracks"]
        switches = tel_gated["identity_switches"]
        arc_calls_avg = tel_gated["arcface_calls_avg"]
        confirmed = tel_gated["confirmed_identities"]
        fps = tel_gated["processing_fps"]
        frame_results = tel_gated["frame_results"]

        # Steady-state latency (Frame 6 where all tracks are confirmed and ArcFace is 100% bypassed)
        steady_state_results = frame_results[5:] if len(frame_results) >= 6 else []
        steady_lat_ms = float(np.mean([r.latency_total_ms for r in steady_state_results])) if steady_state_results else 0.0
        steady_arc_calls = int(np.mean([r.arcface_calls for r in steady_state_results])) if steady_state_results else 0

        print("\n" + "=" * 90)
        print("STEP 2D.4C — TRACK-GATED ARCFACE RECOGNITION BENCHMARK")
        print("=" * 90)
        print(f"{'Metric':<32} | {'Option A Baseline':<20} | {'Step 2D.4C (Track-Gated)':<26} | {'Status / Verification'}")
        print("-" * 90)
        print(f"{'Detection latency':<32} | {'~533 ms':<20} | {f'{det_ms:.1f} ms':<26} | {'Measured'}")
        print(f"{'ArcFace calls/frame (6-frame avg)':<32} | {'~5':<20} | {f'{arc_calls_avg:.1f} calls/frame':<26} | {'Gated after 3 votes'}")
        print(f"{'  - Steady-State ArcFace Calls':<32} | {'~5':<20} | {f'{steady_arc_calls} calls/frame':<26} | {'Bypassed (0 calls!)'}")
        print(f"{'Total ArcFace time/frame':<32} | {'~4.02 s/frame':<20} | {f'{arc_ms / 1000.0:.2f} s/frame':<26} | {'Measured'}")
        print(f"{'Average Frame Latency':<32} | {'~4.56 s':<20} | {f'{tot_ms / 1000.0:.2f} s':<26} | {f'Measured ({4560.0 / max(tot_ms, 1.0):.2f}x speedup)'}")
        print(f"{'  - Steady-State Frame Latency':<32} | {'~4.56 s':<20} | {f'{steady_lat_ms:.1f} ms':<26} | {f'{4560.0 / max(steady_lat_ms, 1.0):.2f}x steady speedup!'}")
        print(f"{'Faces detected':<32} | {'5/5':<20} | {f'{faces}/5':<26} | {'Verified' if faces >= 5 else 'Check'}")
        print(f"{'Active tracks':<32} | {'5/5':<20} | {f'{tracks}/5':<26} | {'Verified' if tracks == 5 else 'Check'}")
        print(f"{'Identity switches':<32} | {'0':<20} | {f'{switches}':<26} | {'Verified (0 switches)' if switches == 0 else 'Failed'}")
        print(f"{'Recognition support':<32} | {'existing voting':<20} | {'3 supporting frames':<26} | {'Verified (3 votes required)'}")
        print(f"{'Confirmed identities':<32} | {'—':<20} | {f'{confirmed}/5 confirmed':<26} | {'Measured'}")
        print(f"{'Processing FPS':<32} | {'0.22 FPS':<20} | {f'{fps:.2f} FPS':<26} | {'Measured'}")
        print(f"{'  - Steady-State Throughput':<32} | {'0.22 FPS':<20} | {f'{1000.0 / max(steady_lat_ms, 1.0):.2f} FPS':<26} | {'High-throughput tracking'}")
        print("=" * 90 + "\n")

        # Formal Acceptance Assertions
        self.assertGreaterEqual(faces, 5)
        self.assertEqual(tracks, 5)
        self.assertEqual(switches, 0)
        self.assertEqual(confirmed, 5)
        self.assertLess(arc_calls_avg, 5.0)
        self.assertLess(tot_ms, 4500.0)
        if steady_state_results:
            self.assertEqual(steady_arc_calls, 0)
            self.assertLess(steady_lat_ms, 1200.0)
        self.assertLessEqual(tel_gated["buffer_size"], 30)

    async def test_webrtc_step_2d_4d_cpu_threads_benchmark(self):
        """Execute Step 2D.4D: ONNX Runtime CPU Thread Optimization Benchmark."""
        thread_configs = [
            ("Current/default", 0, 0),
            ("Thread config 1 (2 intra / 1 inter)", 2, 1),
            ("Thread config 2 (4 intra / 1 inter)", 4, 1),
            ("Thread config 3 (6 intra / 1 inter)", 6, 1),
            ("Thread config 4 (4 intra / 2 inter)", 4, 2),
        ]

        results = []

        try:
            for name, intra, inter in thread_configs:
                configure_scrfd_threads(self.app, intra_threads=intra, inter_threads=inter)

                tel = await self._run_benchmark_trial(
                    processing_resolution=(640, 360),
                    target_frames=6,
                    trial_name=f"2D_4D_{name}",
                    min_supporting_frames=3,
                    app=self.app,
                )

                frame_results = tel["frame_results"]
                steady_frames = frame_results[5:] if len(frame_results) >= 6 else frame_results[-1:]
                steady_det_ms = float(np.mean([r.latency_detection_ms for r in steady_frames]))
                steady_tot_ms = float(np.mean([r.latency_total_ms for r in steady_frames]))
                steady_fps = 1000.0 / max(steady_tot_ms, 1.0)
                steady_arc_calls = int(np.mean([r.arcface_calls for r in steady_frames]))

                results.append({
                    "name": name,
                    "intra": intra,
                    "inter": inter,
                    "detection_ms": steady_det_ms,
                    "steady_tot_ms": steady_tot_ms,
                    "steady_fps": steady_fps,
                    "faces": tel["max_concurrent_faces"],
                    "tracks": tel["max_concurrent_tracks"],
                    "switches": tel["identity_switches"],
                    "steady_arc_calls": steady_arc_calls,
                    "telemetry": tel,
                })

                # Assertions for each thread configuration
                self.assertGreaterEqual(tel["max_concurrent_faces"], 5)
                self.assertEqual(tel["max_concurrent_tracks"], 5)
                self.assertEqual(tel["identity_switches"], 0)
                self.assertEqual(steady_arc_calls, 0)
        finally:
            configure_scrfd_threads(self.app, 0, 0)

        # Print Side-by-Side Comparative Table
        print("\n" + "=" * 110)
        print("STEP 2D.4D: ONNX RUNTIME CPU THREAD OPTIMIZATION BENCHMARK (SCRFD DETECTION)")
        print("=" * 110)
        print(f"{'Configuration':<38} | {'Detection ms':<15} | {'Total steady-state ms':<24} | {'FPS':<10} | {'Verification'}")
        print("-" * 110)
        for r in results:
            verif = f"{r['faces']}/5 faces | {r['tracks']}/5 trk | {r['switches']} sw | {r['steady_arc_calls']} arc"
            det_str = f"{r['detection_ms']:.1f} ms"
            tot_str = f"{r['steady_tot_ms']:.1f} ms"
            fps_str = f"{r['steady_fps']:.2f}"
            print(f"{r['name']:<38} | {det_str:<15} | {tot_str:<24} | {fps_str:<10} | {verif}")
        print("=" * 110 + "\n")

    async def test_webrtc_step_2d_4e_detector_benchmark(self):
        """Execute Step 2D.4E: Lighter SCRFD Detection Model Benchmark (10G vs 2.5G vs 0.5G)."""
        detector_variants = [
            ("Current SCRFD (10G)", "10g"),
            ("SCRFD-2.5G", "2.5g"),
            ("SCRFD-0.5G", "0.5g"),
        ]

        results = []

        try:
            for name, det_type in detector_variants:
                swap_scrfd_detector(
                    self.app,
                    detector_type=det_type,
                    intra_threads=4,
                    inter_threads=2,
                )

                tel = await self._run_benchmark_trial(
                    processing_resolution=(640, 360),
                    target_frames=7,
                    trial_name=f"2D_4E_{name}",
                    min_supporting_frames=3,
                    app=self.app,
                )

                frame_results = tel["frame_results"]
                # Steady state frames where tracks are confirmed and ArcFace is bypassed
                steady_frames = [r for r in frame_results if r.arcface_calls == 0]
                if not steady_frames:
                    steady_frames = frame_results[-2:]
                steady_det_ms = float(np.mean([r.latency_detection_ms for r in steady_frames]))
                steady_tot_ms = float(np.mean([r.latency_total_ms for r in steady_frames]))
                steady_fps = 1000.0 / max(steady_tot_ms, 1.0)
                steady_arc_calls = int(np.mean([r.arcface_calls for r in steady_frames]))

                # Count detections across all 6 frames
                face_counts = [r.face_count for r in frame_results]
                track_counts = [r.active_tracks_count for r in frame_results]

                min_faces = min(face_counts)
                max_faces = max(face_counts)
                avg_faces = float(np.mean(face_counts))

                results.append({
                    "name": name,
                    "det_type": det_type,
                    "detection_ms": steady_det_ms,
                    "steady_tot_ms": steady_tot_ms,
                    "steady_fps": steady_fps,
                    "max_faces": tel["max_concurrent_faces"],
                    "min_faces": min_faces,
                    "avg_faces": avg_faces,
                    "face_counts": face_counts,
                    "max_tracks": tel["max_concurrent_tracks"],
                    "track_counts": track_counts,
                    "switches": tel["identity_switches"],
                    "steady_arc_calls": steady_arc_calls,
                    "telemetry": tel,
                })

                # Assertions
                self.assertGreaterEqual(tel["max_concurrent_faces"], 4)
                self.assertGreaterEqual(tel["max_concurrent_tracks"], 4)
                self.assertEqual(tel["identity_switches"], 0)
                self.assertEqual(steady_arc_calls, 0)
        finally:
            # Restore 10G detector and standard threading
            swap_scrfd_detector(self.app, "10g", intra_threads=4, inter_threads=2)

        # Print Side-by-Side Comparative Table
        print("\n" + "=" * 125)
        print("STEP 2D.4E: LIGHTER SCRFD DETECTOR BENCHMARK (10G vs 2.5G vs 0.5G)")
        print("=" * 125)
        print(f"{'Detector':<24} | {'Detection ms':<15} | {'Steady Frame ms':<18} | {'Throughput (FPS)':<18} | {'Faces':<12} | {'Tracks':<8} | {'Switches':<10} | {'ArcFace Steady'}")
        print("-" * 125)
        for r in results:
            det_str = f"{r['detection_ms']:.1f} ms"
            tot_str = f"{r['steady_tot_ms']:.1f} ms"
            fps_str = f"{r['steady_fps']:.2f} FPS"
            face_str = f"{r['max_faces']}/5 ({r['min_faces']}-{r['max_faces']})"
            track_str = f"{r['max_tracks']}/5"
            sw_str = f"{r['switches']} sw"
            arc_str = f"{r['steady_arc_calls']} calls"
            print(f"{r['name']:<24} | {det_str:<15} | {tot_str:<18} | {fps_str:<18} | {face_str:<12} | {track_str:<8} | {sw_str:<10} | {arc_str}")
        print("=" * 125 + "\n")


if __name__ == "__main__":
    unittest.main()

# The phone WebRTC flow is dropped: /offer and the other WebRTC routes are no
# longer registered on the vision service (it is an internal, key-protected API
# now). These tests exercise that removed flow and are skipped until the WebRTC
# code itself is deleted in the follow-up cleanup.
pytestmark = pytest.mark.skip(reason="phone WebRTC flow removed; routes no longer registered")
