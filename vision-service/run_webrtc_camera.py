#!/usr/bin/env python3
"""Run WebRTC Phone Ingestion Server (Step 2D.2).

Launches the WebRTC signaling and media reception server for phone camera ingest.
Mobile phones on the local network can open the web UI and stream video directly
into PhoneVideoSource -> VideoFrame.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import logging
import os
from pathlib import Path
import socket
import sys
import time

# Ensure vision-service root is in sys.path
SERVICE_ROOT = Path(__file__).resolve().parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

import cv2

from camera import PhoneVideoSource, VideoFrame, VideoSourceType, WebRTCSignalingServer


def get_local_ip() -> str:
    """Best-effort detection of local LAN IP address for phone connection."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connecting to a public UDP address doesn't send packets, but assigns outbound interface IP
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def main() -> None:
    parser = argparse.ArgumentParser(description="WebRTC Phone Camera Ingest Server")
    parser.add_argument("--host", default="0.0.0.0", help="Binding host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8088, help="Port to listen on (default: 8088)")
    parser.add_argument("--source-id", default="PHONE_CAM_01", help="Camera source identifier")
    parser.add_argument(
        "--buffer-size", type=int, default=30, help="Drop-oldest queue buffer capacity"
    )
    parser.add_argument(
        "--cv",
        action=argparse.BooleanOptionalAction,
        default=os.getenv("ENABLE_CV", "true").lower() in {"true", "1", "yes"},
        help="Enable live InsightFace + ByteTrack processing on phone feed (default: True via ENABLE_CV)",
    )
    parser.add_argument(
        "--detector",
        choices=["10g", "2.5g", "0.5g"],
        default="0.5g",
        help="SCRFD detector variant (default: 0.5g)",
    )
    parser.add_argument(
        "--intra-threads", type=int, default=4, help="SCRFD ONNX intra_op_num_threads (default: 4)"
    )
    parser.add_argument(
        "--inter-threads", type=int, default=2, help="SCRFD ONNX inter_op_num_threads (default: 2)"
    )
    parser.add_argument(
        "--dispatch",
        action=argparse.BooleanOptionalAction,
        default=os.getenv("ENABLE_DISPATCH", "true").lower() in {"true", "1", "yes"},
        help="Dispatch attendance events to FastAPI backend (default: True via ENABLE_DISPATCH)",
    )
    parser.add_argument(
        "--backend-url",
        default=os.getenv("BACKEND_URL", "http://127.0.0.1:8000"),
        help="FastAPI backend URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--camera-id",
        default=os.getenv("CAMERA_ID", "CAM_ROOM_101_DOOR"),
        help="Camera ID for attendance events (default: CAM_ROOM_101_DOOR)",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("VISION_SERVICE_API_KEY", "test_vision_api_key_for_smoke_test_12345"),
        help="Vision Service API key for backend event authentication",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("WEBRTC_ACCESS_TOKEN", None),
        help="Access token required for WebRTC phone stream authentication",
    )
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=float(os.getenv("RECOGNITION_SIMILARITY_THRESHOLD", "0.50")),
        help="Cosine similarity threshold for biometric face recognition (default: 0.50)",
    )
    parser.add_argument(
        "--min-margin",
        type=float,
        default=float(os.getenv("RECOGNITION_MIN_MARGIN", "0.15")),
        help="Minimum top-1 vs runner-up similarity margin (default: 0.15)",
    )
    parser.add_argument(
        "--kinematic-anti-spoof",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable kinematic motion-consistent trajectory and duration checks (default: True)",
    )
    parser.add_argument(
        "--kinematic-policy",
        choices=["FLAG", "REJECT"],
        default=os.getenv("KINEMATIC_SPOOF_POLICY", "FLAG"),
        help="Action to take when kinematic spoof is detected (default: FLAG)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    local_ip = get_local_ip()

    source = PhoneVideoSource(
        source_id=args.source_id,
        source_type=VideoSourceType.WEBRTC,
        max_buffer_size=args.buffer_size,
        read_timeout=0.2,
    )
    source.open()

    dispatcher = None
    if args.dispatch:
        try:
            from events.event_dispatcher import EventDispatcher

            dispatcher = EventDispatcher(
                backend_url=args.backend_url,
                raise_on_failure=False,
                api_key=args.api_key,
            )
            print(f"EventDispatcher connected to backend: {dispatcher.backend_url}")
        except Exception as exc:
            print(f"Notice: EventDispatcher initialization warning: {exc}")

    # Start signaling server immediately so HTTP port 8088 is responsive right away
    server = WebRTCSignalingServer(
        video_source=source,
        host=args.host,
        port=args.port,
        access_token=args.token,
        event_dispatcher=dispatcher,
        camera_id=args.camera_id or "CAM_ROOM_101_DOOR",
    )
    server.start_background()

    token_suffix = f"?token={args.token}" if args.token else ""

    print("\n" + "=" * 75)
    print("VISION SERVICE - PHONE WEBRTC LIVE FRAME INGEST (Step 2D.5)")
    print("=" * 75)
    print(f"  Local URL     : http://localhost:{args.port}/{token_suffix}")
    print(f"  Phone LAN URL : http://{local_ip}:{args.port}/{token_suffix}")
    print(f"  Source ID     : {args.source_id}")
    print(
        f"  Live CV Mode  : {'ENABLED (SCRFD-' + args.detector.upper() + ' + ByteTrack)' if args.cv else 'DISABLED (Raw Ingestion)'}"
    )
    print(
        f"  Event Dispatch: {'ENABLED -> ' + args.backend_url if (args.cv and args.dispatch) else 'DISABLED'}"
    )
    print(f"  Security Token: {'CONFIGURED (Protected)' if args.token else 'NONE (Open)'}")
    print(f"  Buffer Policy : Drop oldest (max {args.buffer_size} frames)")
    print("-" * 75)
    print("  Instructions for Phone:")
    print("  1. Connect your phone to the same Wi-Fi network as this PC.")
    print(f"  2. Open http://{local_ip}:{args.port}/{token_suffix} in Chrome / Safari.")
    print("  3. Allow camera access and tap 'Start Camera Stream'.")
    print("=" * 75 + "\n")

    pipeline = None
    if args.cv:
        print("\nInitializing InsightFace and Biometric Gallery for live CV tracking...")
        try:
            from insightface.app import FaceAnalysis
            from pipeline import (
                LiveCVPipeline,
                configure_scrfd_threads,
                swap_scrfd_detector,
            )

            app = FaceAnalysis(
                name="buffalo_l",
                providers=["CPUExecutionProvider"],
                allowed_modules=["detection", "recognition"],
            )
            app.prepare(ctx_id=0, det_size=(640, 640))
            if args.detector != "10g":
                try:
                    swap_scrfd_detector(
                        app,
                        detector_type=args.detector,
                        intra_threads=args.intra_threads,
                        inter_threads=args.inter_threads,
                    )
                except Exception as exc:
                    print(f"[INFO] Using standard 10g detector: {exc}")
                    configure_scrfd_threads(
                        app, intra_threads=args.intra_threads, inter_threads=args.inter_threads
                    )
            else:
                configure_scrfd_threads(
                    app, intra_threads=args.intra_threads, inter_threads=args.inter_threads
                )

            # The gallery starts empty. Embeddings are loaded only from the backend
            # over its authenticated internal route, never from a file.
            gallery = {}
            print(f"[INFO] Loaded {len(gallery)} enrolled identities: {list(gallery.keys())}")

            pipeline = LiveCVPipeline(
                app=app,
                gallery=gallery,
                similarity_threshold=args.similarity_threshold,
                min_margin=args.min_margin,
                min_supporting_frames=2,
                source_id=args.source_id,
                camera_id=args.camera_id or args.source_id,
                boundary_line=((0.0, 0.5), (1.0, 0.5)),
                entry_side="SIDE_A",
                deadband_pixels=8.0,
                event_dispatcher=dispatcher,
                enable_kinematic_anti_spoof=args.kinematic_anti_spoof,
                kinematic_spoof_policy="FLAG",
            )
            server.set_pipeline(pipeline)
            print("Live CV Pipeline loaded and ready!")
        except Exception as exc:
            print(
                f"Notice: Live CV models not available ({exc}). Running in WebRTC ingestion bridge mode."
            )
            pipeline = None

    last_report = time.monotonic()
    consumed_count = 0

    try:
        while True:
            # Consume incoming frames to demonstrate live ingestion
            frame: VideoFrame | None = source.read(block=False)
            if frame is not None:
                consumed_count += 1

                if pipeline is not None:
                    # Run live CV pipeline on phone frame
                    cv_result = pipeline.process_frame(frame)

                    # Update live annotated preview stream (MJPEG on port 8088)
                    annotated = pipeline.render_annotated_frame(frame.frame, cv_result)
                    ret, jpeg = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                    if ret:
                        server.update_preview_frame(jpeg.tobytes(), cv_result)

                    if consumed_count % 5 == 0 or consumed_count == 1:
                        print(pipeline.render_console_view(cv_result))
                else:
                    if consumed_count % 30 == 0 or consumed_count == 1:
                        print(
                            f"[{datetime.now().strftime('%H:%M:%S')}] Ingested Frame #{frame.frame_index:05d} | "
                            f"Source: {frame.source_id} ({frame.source_type.value}) | "
                            f"Res: {frame.width}x{frame.height} | "
                            f"Queue: {source.buffer_size}/{args.buffer_size} | "
                            f"Dropped: {source.dropped_frames}"
                        )

            time.sleep(0.01)

            # Heartbeat telemetry every 10 seconds if idle
            if time.monotonic() - last_report > 10.0:
                last_report = time.monotonic()
                if consumed_count == 0:
                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] Waiting for phone camera connection at http://{local_ip}:{args.port}..."
                    )

    except KeyboardInterrupt:
        print("\nStopping WebRTC ingest server...")
    finally:
        if pipeline is not None:
            print(
                "\n" + pipeline.format_benchmark_report(dropped_frames=source.dropped_frames) + "\n"
            )
        server.stop()
        source.release()
        print("WebRTC ingest server safely stopped.")


if __name__ == "__main__":
    main()
