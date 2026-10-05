"""Multi-Camera Worker and Orchestrator for Anti-Proxy Vision System.

Runs independent per-camera pipelines concurrently with:
- Dedicated VideoSource per camera (RTSP or local simulation).
- Dedicated LiveCVPipeline per camera with custom boundary geometry and directional role (ENTRY/EXIT/BOTH).
- Service-authenticated operational health heartbeat reporting to FastAPI.
- Benchmarking harness measuring CPU% and throughput FPS across 1 vs N concurrent cameras.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Optional

try:
    import psutil
except ImportError:
    psutil = None

from camera.base import VideoFrame, VideoSource
from camera.factory import create_video_source
from events.event_dispatcher import EventDispatcher
from pipeline.live_cv_pipeline import LiveCVPipeline

logger = logging.getLogger(__name__)


@dataclass
class CameraConfig:
    """Configuration specification for a single camera worker."""

    camera_id: str
    classroom_id: str
    role: str = "BOTH"  # "ENTRY", "EXIT", "BOTH"
    source_type: str = "RTSP"  # "RTSP", "FILE", "WEBRTC", "PHONE"
    source_uri: str = ""
    boundary_line: Optional[tuple[tuple[float, float], tuple[float, float]]] = None
    entry_side: str = "SIDE_A"
    deadband_pixels: float = 4.0
    target_fps: float = 5.0
    enabled: bool = True
    api_key: Optional[str] = None
    heartbeat_interval_sec: float = 5.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CameraConfig:
        boundary = data.get("boundary_line")
        if boundary and isinstance(boundary, (list, tuple)) and len(boundary) == 2:
            p1 = tuple(float(x) for x in boundary[0])
            p2 = tuple(float(x) for x in boundary[1])
            boundary = (p1, p2)
        else:
            boundary = None

        return cls(
            camera_id=data["camera_id"],
            classroom_id=data["classroom_id"],
            role=data.get("role", "BOTH").upper(),
            source_type=data.get("source_type", "RTSP").upper(),
            source_uri=str(data.get("source_uri", "")),
            boundary_line=boundary,
            entry_side=data.get("entry_side", "SIDE_A"),
            deadband_pixels=float(data.get("deadband_pixels", 4.0)),
            target_fps=float(data.get("target_fps", 5.0)),
            enabled=data.get("enabled", True),
            api_key=data.get("api_key"),
            heartbeat_interval_sec=float(data.get("heartbeat_interval_sec", 5.0)),
        )


class CameraWorker:
    """Dedicated background worker running CV inference and telemetry for a single camera."""

    def __init__(
        self,
        config: CameraConfig,
        app: Any,
        gallery: dict[str, Any],
        dispatcher: Optional[EventDispatcher] = None,
        backend_url: Optional[str] = None,
        default_api_key: Optional[str] = None,
    ) -> None:
        self.config = config
        self.app = app
        self.gallery = gallery
        self.backend_url = backend_url or os.getenv("BACKEND_URL", "http://localhost:8000")
        self.api_key = config.api_key or default_api_key or os.getenv("VISION_SERVICE_API_KEY")

        # Initialize dedicated EventDispatcher if not injected
        if dispatcher is not None:
            self.dispatcher = dispatcher
        else:
            self.dispatcher = EventDispatcher(
                backend_url=self.backend_url,
                api_key=self.api_key,
                raise_on_failure=False,
            )

        # Initialize dedicated LiveCVPipeline with individual role and boundary
        self.pipeline = LiveCVPipeline(
            app=self.app,
            gallery=self.gallery,
            source_id=self.config.camera_id,
            camera_id=self.config.camera_id,
            camera_role=self.config.role,
            boundary_line=self.config.boundary_line,
            deadband_pixels=self.config.deadband_pixels,
            entry_side=self.config.entry_side,
            event_dispatcher=self.dispatcher,
        )

        # Video source adapter
        self.source: Optional[VideoSource] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Telemetry metrics
        self.frames_processed: int = 0
        self.last_heartbeat_time: float = 0.0
        self.worker_start_time: float = 0.0
        self.current_worker_fps: float = 0.0
        self._fps_window: list[float] = []

    def start(self) -> None:
        """Start the camera ingestion and CV worker thread."""
        if not self.config.enabled:
            logger.info("Camera %s is disabled, skipping start.", self.config.camera_id)
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"worker_{self.config.camera_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal worker to stop and release video source."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)
            self._thread = None

        if self.source is not None:
            self.source.release()
            self.source = None

    def is_alive(self) -> bool:
        """Whether the worker thread is running."""
        return self._thread is not None and self._thread.is_alive()

    def _init_source(self) -> VideoSource:
        """Construct the configured VideoSource."""
        extra_kwargs = {}
        if self.config.source_type == "FILE":
            extra_kwargs["loop"] = True

        return create_video_source(
            source_type=self.config.source_type,
            source_uri=self.config.source_uri,
            source_id=self.config.camera_id,
            target_fps=self.config.target_fps,
            **extra_kwargs,
        )

    def _run_loop(self) -> None:
        """Main camera worker processing loop."""
        self.worker_start_time = time.monotonic()
        try:
            self.source = self._init_source()
            self.source.open()
        except Exception as exc:
            logger.error("Failed to open source for %s: %s", self.config.camera_id, exc)
            self._send_heartbeat(state="DISCONNECTED")
            return

        logger.info(
            "CameraWorker %s started (role=%s, source=%s)",
            self.config.camera_id,
            self.config.role,
            self.config.source_type,
        )
        self.last_heartbeat_time = time.monotonic()

        while not self._stop_event.is_set():
            loop_now = time.monotonic()

            # 1. Periodic service-authenticated heartbeat
            if loop_now - self.last_heartbeat_time >= self.config.heartbeat_interval_sec:
                src_status = self.source.status if self.source else "UNKNOWN"
                self._send_heartbeat(state=src_status)
                self.last_heartbeat_time = loop_now

            # 2. Read frame from source
            try:
                frame: Optional[VideoFrame] = self.source.read()
            except Exception as exc:
                logger.warning("Frame read exception in %s: %s", self.config.camera_id, exc)
                time.sleep(0.05)
                continue

            if frame is None:
                # End of stream or degraded
                time.sleep(0.02)
                continue

            # 3. Process frame through LiveCVPipeline
            try:
                self.pipeline.process_frame(frame)
                self.frames_processed += 1
                frame_done = time.monotonic()

                # Calculate worker throughput FPS
                self._fps_window.append(frame_done)
                cutoff = frame_done - 3.0
                while self._fps_window and self._fps_window[0] < cutoff:
                    self._fps_window.pop(0)
                if len(self._fps_window) > 1:
                    span = self._fps_window[-1] - self._fps_window[0]
                    self.current_worker_fps = (
                        (len(self._fps_window) - 1) / span if span > 0 else 0.0
                    )
                else:
                    self.current_worker_fps = 1.0

            except Exception as exc:
                logger.error(
                    "CV pipeline error in %s: %s", self.config.camera_id, exc, exc_info=True
                )

        logger.info("CameraWorker %s exited cleanly.", self.config.camera_id)

    def _send_heartbeat(self, state: str) -> None:
        """Transmit operational health telemetry to FastAPI backend."""
        fps = getattr(self.source, "fps", self.current_worker_fps)
        drops = getattr(self.source, "dropped_frames", 0)
        self.dispatcher.send_camera_heartbeat(
            camera_id=self.config.camera_id,
            state=state,
            fps=float(fps),
            dropped_frames=int(drops),
            metadata={
                "role": self.config.role,
                "frames_processed": self.frames_processed,
                "worker_fps": round(self.current_worker_fps, 2),
            },
            timeout=0.3,
        )

    def get_status(self) -> dict[str, Any]:
        """Telemetry snapshot for dashboards."""
        src_status = self.source.status if self.source else "STOPPED"
        src_fps = getattr(self.source, "fps", round(self.current_worker_fps, 2))
        src_drops = getattr(self.source, "dropped_frames", 0)

        return {
            "camera_id": self.config.camera_id,
            "classroom_id": self.config.classroom_id,
            "role": self.config.role,
            "source_type": self.config.source_type,
            "status": src_status,
            "fps": src_fps,
            "worker_fps": round(self.current_worker_fps, 2),
            "dropped_frames": src_drops,
            "frames_processed": self.frames_processed,
            "is_alive": self.is_alive(),
        }


class MultiCameraRunner:
    """Orchestrator for managing N camera workers simultaneously."""

    def __init__(
        self,
        configs: list[CameraConfig] | list[dict[str, Any]],
        app: Any,
        gallery: dict[str, Any],
        backend_url: Optional[str] = None,
        default_api_key: Optional[str] = None,
    ) -> None:
        self.app = app
        self.gallery = gallery
        self.backend_url = backend_url
        self.default_api_key = default_api_key

        self.workers: dict[str, CameraWorker] = {}
        for item in configs:
            cfg = item if isinstance(item, CameraConfig) else CameraConfig.from_dict(item)
            worker = CameraWorker(
                config=cfg,
                app=self.app,
                gallery=self.gallery,
                backend_url=self.backend_url,
                default_api_key=self.default_api_key,
            )
            self.workers[cfg.camera_id] = worker

    @classmethod
    def from_config_file(
        cls,
        config_path: str | Path,
        app: Any,
        gallery: dict[str, Any],
        backend_url: Optional[str] = None,
        default_api_key: Optional[str] = None,
    ) -> MultiCameraRunner:
        """Instantiate runner from JSON or YAML configuration file."""
        path = Path(config_path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        camera_list = data if isinstance(data, list) else data.get("cameras", [])
        return cls(
            configs=camera_list,
            app=app,
            gallery=gallery,
            backend_url=backend_url,
            default_api_key=default_api_key,
        )

    def start(self) -> None:
        """Start all configured camera workers."""
        logger.info("Starting MultiCameraRunner with %d cameras...", len(self.workers))
        for worker in self.workers.values():
            worker.start()

    def stop(self) -> None:
        """Stop all running camera workers."""
        logger.info("Stopping all camera workers...")
        for worker in self.workers.values():
            worker.stop()

    def get_health_status(self) -> list[dict[str, Any]]:
        """Collect telemetry status from all workers."""
        return [w.get_status() for w in self.workers.values()]

    @staticmethod
    def benchmark(
        camera_configs: list[dict[str, Any]],
        app: Any,
        gallery: dict[str, Any],
        duration_sec: float = 5.0,
    ) -> dict[str, Any]:
        """Benchmark 1 vs 2 (or N) cameras measuring CPU% and throughput FPS."""
        results = {}

        for n_cams in (1, min(2, len(camera_configs))):
            test_cams = camera_configs[:n_cams]
            runner = MultiCameraRunner(configs=test_cams, app=app, gallery=gallery)

            proc = psutil.Process() if psutil is not None else None
            if proc is not None:
                proc.cpu_percent(interval=None)
            cpu_t0 = time.process_time()

            t_start = time.monotonic()
            runner.start()
            time.sleep(duration_sec)
            t_end = time.monotonic()

            cpu_t1 = time.process_time()
            if proc is not None:
                cpu_pct = proc.cpu_percent(interval=None)
            else:
                elapsed = max(t_end - t_start, 0.001)
                cpu_pct = round(((cpu_t1 - cpu_t0) / elapsed) * 100.0, 1)

            statuses = runner.get_health_status()
            runner.stop()

            total_frames = sum(s["frames_processed"] for s in statuses)
            actual_duration = max(t_end - t_start, 0.001)
            aggregate_fps = total_frames / actual_duration

            results[f"{n_cams}_cameras"] = {
                "cameras_count": n_cams,
                "cpu_percent": round(cpu_pct, 1),
                "aggregate_fps": round(aggregate_fps, 2),
                "per_camera_fps": [s["worker_fps"] for s in statuses],
                "frames_processed": total_frames,
                "duration_seconds": round(actual_duration, 2),
            }

        return results
