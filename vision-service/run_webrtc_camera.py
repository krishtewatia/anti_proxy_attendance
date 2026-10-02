#!/usr/bin/env python3
"""Run WebRTC Phone Ingestion Server (Step 2D.2).

Launches the WebRTC signaling and media reception server for phone camera ingest.
Mobile phones on the local network can open the web UI and stream video directly
into PhoneVideoSource -> VideoFrame.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import logging
from pathlib import Path
import socket
import sys
import time

# Ensure vision-service root is in sys.path
SERVICE_ROOT = Path(__file__).resolve().parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

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
    parser.add_argument("--buffer-size", type=int, default=30, help="Drop-oldest queue buffer capacity")
    parser.add_argument("--cv", action="store_true", help="Enable live InsightFace + ByteTrack processing on phone feed")
    parser.add_argument("--intra-threads", type=int, default=4, help="SCRFD ONNX intra_op_num_threads (default: 4)")
    parser.add_argument("--inter-threads", type=int, default=2, help="SCRFD ONNX inter_op_num_threads (default: 2)")
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

    pipeline = None
    if args.cv:
        print("\nInitializing InsightFace and Biometric Gallery for live CV tracking...")
        from insightface.app import FaceAnalysis
        from pipeline import LiveCVPipeline, load_gallery, configure_scrfd_threads

        app = FaceAnalysis(
            name="buffalo_l",
            providers=["CPUExecutionProvider"],
            allowed_modules=["detection", "recognition"],
        )
        app.prepare(ctx_id=0, det_size=(640, 640))
        configure_scrfd_threads(app, intra_threads=args.intra_threads, inter_threads=args.inter_threads)

        gallery_dir = SERVICE_ROOT / "tests" / "recognition_benchmark"
        gallery = load_gallery(app, gallery_dir)
        pipeline = LiveCVPipeline(
            app=app,
            gallery=gallery,
            similarity_threshold=0.40,
            min_margin=0.15,
            min_supporting_frames=2,
            source_id=args.source_id,
        )
        print("Live CV Pipeline loaded and ready!")

    server = WebRTCSignalingServer(
        video_source=source,
        host=args.host,
        port=args.port,
    )

    print("\n" + "=" * 75)
    print("VISION SERVICE - PHONE WEBRTC LIVE FRAME INGEST (Step 2D.3)")
    print("=" * 75)
    print(f"  Local URL     : http://localhost:{args.port}")
    print(f"  Phone LAN URL : http://{local_ip}:{args.port}")
    print(f"  Source ID     : {args.source_id}")
    print(f"  Live CV Mode  : {'ENABLED (InsightFace + ByteTrack)' if args.cv else 'DISABLED (Raw Ingestion)'}")
    print(f"  Buffer Policy : Drop oldest (max {args.buffer_size} frames)")
    print("-" * 75)
    print("  Instructions for Phone:")
    print(f"  1. Connect your phone to the same Wi-Fi network as this PC.")
    print(f"  2. Open http://{local_ip}:{args.port} in Chrome / Safari.")
    print("  3. Allow camera access and tap 'Start Camera Stream'.")
    print("=" * 75 + "\n")

    server.start_background()

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
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Waiting for phone camera connection at http://{local_ip}:{args.port}...")

    except KeyboardInterrupt:
        print("\nStopping WebRTC ingest server...")
    finally:
        if pipeline is not None:
            print("\n" + pipeline.format_benchmark_report(dropped_frames=source.dropped_frames) + "\n")
        server.stop()
        source.release()
        print("WebRTC ingest server safely stopped.")


if __name__ == "__main__":
    main()
