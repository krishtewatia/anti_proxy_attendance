#!/usr/bin/env python3
"""Entry point of the vision service.

Starts the internal, key-protected HTTP API that the backend calls to
recognize faces in a camera frame and to extract embeddings at enrollment.
The service has no browser-facing surface and performs no live video ingest.
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import sys
import time

SERVICE_ROOT = Path(__file__).resolve().parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from camera.recognition_signing import validate_signing_key  # noqa: E402

logger = logging.getLogger("vision_service")


def load_face_analysis(detector: str, intra_threads: int, inter_threads: int):
    """Load InsightFace detection + recognition, optionally with a lighter SCRFD detector."""
    from insightface.app import FaceAnalysis
    from pipeline import configure_scrfd_threads, swap_scrfd_detector

    app = FaceAnalysis(
        name="buffalo_l",
        providers=["CPUExecutionProvider"],
        allowed_modules=["detection", "recognition"],
    )
    app.prepare(ctx_id=0, det_size=(640, 640))
    if detector != "10g":
        try:
            swap_scrfd_detector(
                app,
                detector_type=detector,
                intra_threads=intra_threads,
                inter_threads=inter_threads,
            )
            return app
        except Exception as exc:
            logger.info("Using the standard 10g detector: %s", exc)
    configure_scrfd_threads(app, intra_threads=intra_threads, inter_threads=inter_threads)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Vision service: internal recognition API")
    parser.add_argument("--host", default="0.0.0.0", help="Binding host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8088, help="Port to listen on (default: 8088)")
    parser.add_argument(
        "--backend-url",
        default=os.getenv("BACKEND_URL", "http://backend:8000"),
        help="Backend base URL used to sync the gallery",
    )
    parser.add_argument(
        "--detector",
        choices=["10g", "2.5g", "0.5g"],
        default=os.getenv("SCRFD_DETECTOR", "0.5g"),
        help="SCRFD detector variant (default: 0.5g)",
    )
    parser.add_argument("--intra-threads", type=int, default=4, help="ONNX intra-op threads")
    parser.add_argument("--inter-threads", type=int, default=2, help="ONNX inter-op threads")
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=float(os.getenv("RECOGNITION_SIMILARITY_THRESHOLD", "0.50")),
        help="Minimum cosine similarity for a confirmed match (default: 0.50)",
    )
    parser.add_argument(
        "--min-margin",
        type=float,
        default=float(os.getenv("RECOGNITION_MIN_MARGIN", "0.15")),
        help="Minimum margin over the runner-up identity (default: 0.15)",
    )
    parser.add_argument(
        "--no-preload",
        action="store_true",
        help="Do not load the face models at startup (they load on the first request)",
    )
    args = parser.parse_args()

    # Fail closed: never serve recognition results without a real signing key.
    try:
        validate_signing_key(
            os.getenv("RECOGNITION_SIGNING_KEY"),
            allow_insecure=os.getenv("ALLOW_INSECURE_RECOGNITION_KEY", "false").lower()
            in {"true", "1", "yes"},
        )
    except RuntimeError as exc:
        print(f"[FATAL] {exc}", file=sys.stderr)
        raise SystemExit(1)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    from camera.vision_api import VisionApiServer

    server = VisionApiServer(
        host=args.host,
        port=args.port,
        backend_url=args.backend_url,
        similarity_threshold=args.similarity_threshold,
        min_margin=args.min_margin,
    )
    # Listen first so the health check answers while the models load.
    server.start_background()
    logger.info(
        "Vision API started on %s:%d (internal, service key required)", args.host, args.port
    )

    if not args.no_preload:
        try:
            server.set_face_app(
                load_face_analysis(args.detector, args.intra_threads, args.inter_threads)
            )
            logger.info("Face models loaded (SCRFD-%s + ArcFace)", args.detector.upper())
        except Exception as exc:
            logger.warning("Face models not loaded at startup, will retry on first use: %s", exc)

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logger.info("Shutting down vision service")
    finally:
        server.stop()


if __name__ == "__main__":
    main()
