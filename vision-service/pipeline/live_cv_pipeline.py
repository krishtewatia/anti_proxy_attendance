from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
from insightface.app import FaceAnalysis
import numpy as np

from camera.base import VideoFrame, VideoSourceType
from tracking.bytetrack import BYTETracker, box_iou

logger = logging.getLogger(__name__)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two 512-d feature vectors."""
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def load_gallery(app: FaceAnalysis, gallery_dir: Path) -> dict[str, np.ndarray]:
    """Extract reference ArcFace embeddings for all enrolled identities."""
    gallery: dict[str, np.ndarray] = {}
    if not gallery_dir.exists():
        raise FileNotFoundError(f"Gallery directory not found: {gallery_dir}")

    for person_dir in sorted(gallery_dir.iterdir()):
        if not person_dir.is_dir():
            continue
        person_name = person_dir.name
        img_paths = sorted(
            p
            for p in person_dir.iterdir()
            if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )

        embeddings: list[np.ndarray] = []
        for img_path in img_paths:
            img = cv2.imread(str(img_path))
            if img is None:
                continue
            faces = app.get(img)
            if faces:
                best_face = max(faces, key=lambda f: f.det_score)
                embeddings.append(best_face.embedding)

        if embeddings:
            mean_emb = np.mean(embeddings, axis=0)
            norm = np.linalg.norm(mean_emb)
            mean_emb = mean_emb / (norm + 1e-10)
            gallery[person_name] = mean_emb.astype(np.float32)

    return gallery


def create_face_analysis(
    name: str = "buffalo_l",
    allowed_modules: Optional[list[str]] = None,
    intra_threads: int = 0,
    inter_threads: int = 0,
    det_size: tuple[int, int] = (640, 640),
) -> FaceAnalysis:
    """Create and prepare FaceAnalysis with configurable ONNX Runtime thread options."""
    import onnxruntime as ort

    sess_options = ort.SessionOptions()
    if intra_threads > 0:
        sess_options.intra_op_num_threads = intra_threads
    if inter_threads > 0:
        sess_options.inter_op_num_threads = inter_threads

    app = FaceAnalysis(
        name=name,
        providers=["CPUExecutionProvider"],
        allowed_modules=allowed_modules or ["detection", "recognition"],
        sess_options=sess_options,
    )
    app.prepare(ctx_id=0, det_size=det_size)
    return app


def configure_scrfd_threads(
    app: FaceAnalysis,
    intra_threads: int = 0,
    inter_threads: int = 0,
) -> None:
    """Configure ONNX Runtime execution provider CPU threads specifically for SCRFD detection."""
    import onnxruntime as ort
    from insightface.model_zoo.model_zoo import PickableInferenceSession

    if "detection" not in app.models:
        return

    det = app.models["detection"]
    sess_options = ort.SessionOptions()
    if intra_threads > 0:
        sess_options.intra_op_num_threads = intra_threads
    if inter_threads > 0:
        sess_options.inter_op_num_threads = inter_threads

    providers = getattr(det.session, "_providers", ["CPUExecutionProvider"])
    det.session = PickableInferenceSession(
        det.model_file,
        providers=providers,
        sess_options=sess_options,
    )
    if hasattr(det, "_reset_resolution_session_pool"):
        det._reset_resolution_session_pool()
    app.det_model = det


def swap_scrfd_detector(
    app: FaceAnalysis,
    detector_type: str = "10g",
    intra_threads: int = 4,
    inter_threads: int = 2,
    det_size: tuple[int, int] = (640, 640),
) -> None:
    """Swap the SCRFD detector in FaceAnalysis ('10g', '2.5g', or '0.5g')."""
    import os
    from insightface.model_zoo import get_model

    det_map = {
        "10g": "~/.insightface/models/buffalo_l/det_10g.onnx",
        "2.5g": "~/.insightface/models/buffalo_m/det_2.5g.onnx",
        "0.5g": "~/.insightface/models/buffalo_s/det_500m.onnx",
        "500m": "~/.insightface/models/buffalo_s/det_500m.onnx",
    }
    path = os.path.expanduser(det_map.get(detector_type.lower(), detector_type))
    if not os.path.exists(path):
        raise FileNotFoundError(f"SCRFD model not found: {path}")

    new_det = get_model(path)
    new_det.prepare(ctx_id=0, input_size=det_size)
    app.models["detection"] = new_det
    app.det_model = new_det
    configure_scrfd_threads(app, intra_threads=intra_threads, inter_threads=inter_threads)


@dataclass
class TrackEvidence:
    """Maintains temporal identity and trajectory evidence for a tracked individual."""

    track_id: int
    first_seen: datetime
    last_seen: datetime
    total_frames: int = 0
    supporting_frames: int = 0
    identity_votes: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    similarities: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    assigned_identity: str = "UNKNOWN"
    assigned_confidence: float = 0.0
    identity_switches: int = 0
    last_bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    is_confirmed: bool = False
    recognition_attempts: int = 0

    def add_observation(
        self,
        identity: str,
        score: float,
        bbox: tuple[float, float, float, float],
        timestamp: datetime,
        min_supporting_frames: int = 3,
        max_unknown_attempts: int = 5,
    ) -> None:
        self.last_seen = timestamp
        self.total_frames += 1
        self.last_bbox = bbox
        self.recognition_attempts += 1

        if identity != "UNKNOWN":
            self.supporting_frames += 1
            self.identity_votes[identity] += 1
            self.similarities[identity].append(score)

        # Evaluate plurality winner
        if self.identity_votes:
            top_candidate, vote_count = max(self.identity_votes.items(), key=lambda kv: kv[1])
            avg_sim = float(np.mean(self.similarities[top_candidate]))

            if vote_count >= min_supporting_frames:
                # Check for an identity switch
                if (
                    self.assigned_identity != "UNKNOWN"
                    and self.assigned_identity != top_candidate
                ):
                    self.identity_switches += 1
                    logger.warning(
                        "Track %d identity switch detected: %s -> %s (vote=%d)",
                        self.track_id,
                        self.assigned_identity,
                        top_candidate,
                        vote_count,
                    )

                self.assigned_identity = top_candidate
                self.assigned_confidence = avg_sim
                self.is_confirmed = True
            else:
                self.assigned_identity = "UNKNOWN"
                self.assigned_confidence = avg_sim
                self.is_confirmed = False
        else:
            if self.recognition_attempts >= max_unknown_attempts:
                self.assigned_identity = "UNKNOWN"
                self.is_confirmed = True

    def update_position(
        self,
        bbox: tuple[float, float, float, float],
        timestamp: datetime,
    ) -> None:
        """Update track trajectory without re-running biometric recognition."""
        self.last_seen = timestamp
        self.total_frames += 1
        self.last_bbox = bbox


@dataclass
class FrameTrackInfo:
    """Per-track output for a single processed video frame."""

    track_id: int
    identity: str
    confidence: float
    bbox: tuple[float, float, float, float]
    supporting_frames: int
    is_confirmed: bool = False


@dataclass
class FrameCVResult:
    """Structured telemetry output for a processed VideoFrame."""

    source_id: str
    source_type: VideoSourceType
    frame_index: int
    timestamp: datetime
    resolution: tuple[int, int]
    face_count: int
    active_tracks_count: int
    tracks: list[FrameTrackInfo]
    latency_total_ms: float
    latency_detection_ms: float
    latency_embedding_ms: float
    latency_tracking_ms: float
    latency_arcface_ms: float = 0.0
    latency_landmark_3d_ms: float = 0.0
    latency_landmark_2d_ms: float = 0.0
    latency_genderage_ms: float = 0.0
    arcface_calls: int = 0
    confirmed_tracks_count: int = 0


class LiveCVPipeline:
    """Connects incoming VideoFrames (e.g. from WebRTC Phone) to InsightFace + ByteTrack."""

    def __init__(
        self,
        app: FaceAnalysis,
        gallery: dict[str, np.ndarray],
        tracker: Optional[BYTETracker] = None,
        similarity_threshold: float = 0.40,
        min_margin: float = 0.15,
        min_supporting_frames: int = 3,
        source_id: str = "PHONE_CAM_01",
        processing_resolution: Optional[Tuple[int, int]] = None,
    ) -> None:
        self.app = app
        self.gallery = gallery
        self.similarity_threshold = similarity_threshold
        self.min_margin = min_margin
        self.min_supporting_frames = min_supporting_frames
        self.source_id = source_id
        self.processing_resolution = processing_resolution

        self.tracker = tracker or BYTETracker(
            track_thresh=0.40,
            match_thresh=0.80,
            track_buffer=30,
            frame_rate=30,
        )

        # Temporal state
        self.tracks: dict[int, TrackEvidence] = {}
        self.processed_frames: int = 0
        self.total_detections: int = 0
        self.max_concurrent_faces: int = 0
        self.max_concurrent_tracks: int = 0
        self.total_identity_switches: int = 0

        # Latency telemetry (milliseconds)
        self.latencies_total: list[float] = []
        self.latencies_detect: list[float] = []
        self.latencies_landmark_3d: list[float] = []
        self.latencies_landmark_2d: list[float] = []
        self.latencies_genderage: list[float] = []
        self.latencies_arcface: list[float] = []
        self.latencies_embed: list[float] = []
        self.latencies_track: list[float] = []

        # Track-gated ArcFace invocation telemetry
        self.arcface_calls_per_frame: list[int] = []
        self.total_arcface_calls: int = 0

        self._start_perf_time: float = time.perf_counter()

    def match_identity(self, face_embedding: np.ndarray) -> tuple[str, float, str, float]:
        """Match 512-d ArcFace embedding against enrolled biometric gallery."""
        if not self.gallery:
            return "UNKNOWN", 0.0, "none", 0.0

        norm = np.linalg.norm(face_embedding)
        face_emb = face_embedding / (norm + 1e-10)

        scores: list[tuple[str, float]] = []
        for name, ref_emb in self.gallery.items():
            sim = float(np.dot(face_emb, ref_emb))
            scores.append((name, sim))

        scores.sort(key=lambda x: x[1], reverse=True)
        top_name, top_sim = scores[0]
        runner_up_name, runner_up_sim = scores[1] if len(scores) > 1 else ("none", -1.0)
        margin = top_sim - runner_up_sim

        # Check unknown criteria
        if top_sim < self.similarity_threshold or margin < self.min_margin:
            return "UNKNOWN", top_sim, runner_up_name, margin

        return top_name, top_sim, runner_up_name, margin

    def process_frame(self, video_frame: VideoFrame) -> FrameCVResult:
        """Execute CV inference, embedding matching, and tracking on a VideoFrame."""
        t_start = time.perf_counter()

        raw_frame = video_frame.frame
        if raw_frame is None or raw_frame.size == 0:
            raise ValueError("VideoFrame contains empty image matrix.")

        orig_h, orig_w = raw_frame.shape[:2]

        if self.processing_resolution is not None and self.processing_resolution != (orig_w, orig_h):
            proc_w, proc_h = self.processing_resolution
            proc_frame = cv2.resize(raw_frame, (proc_w, proc_h), interpolation=cv2.INTER_LINEAR)
            scale_x = orig_w / proc_w
            scale_y = orig_h / proc_h
        else:
            proc_frame = raw_frame
            scale_x = 1.0
            scale_y = 1.0

        # 1. SCRFD Face Detection
        t_det0 = time.perf_counter()
        det_model = self.app.models.get("detection", self.app.det_model)
        bboxes, kpss = det_model.detect(proc_frame, max_num=0, metric="default")
        t_detect = (time.perf_counter() - t_det0) * 1000.0

        from insightface.app.common import Face
        faces = []
        if bboxes is not None and bboxes.shape[0] > 0:
            for i in range(bboxes.shape[0]):
                kps = kpss[i] if kpss is not None else None
                face = Face(bbox=bboxes[i, 0:4], kps=kps, det_score=bboxes[i, 4])
                faces.append(face)

        face_count = len(faces)
        self.total_detections += face_count
        if face_count > self.max_concurrent_faces:
            self.max_concurrent_faces = face_count

        # Build detection bounding boxes for ByteTrack
        dets_for_tracker = []
        for face in faces:
            x1, y1, x2, y2 = face.bbox
            if scale_x != 1.0 or scale_y != 1.0:
                scaled_bbox = (float(x1 * scale_x), float(y1 * scale_y), float(x2 * scale_x), float(y2 * scale_y))
            else:
                scaled_bbox = (float(x1), float(y1), float(x2), float(y2))
            dets_for_tracker.append({
                "face": face,
                "scaled_bbox": scaled_bbox,
                "det_score": float(face.det_score),
            })

        # 2. ByteTrack Multi-Object Tracking (on detection boxes)
        t_trk0 = time.perf_counter()
        if dets_for_tracker:
            dets_array = np.array(
                [[*d["scaled_bbox"], d["det_score"]] for d in dets_for_tracker],
                dtype=np.float32,
            )
        else:
            dets_array = np.empty((0, 5), dtype=np.float32)

        online_tracks = self.tracker.update(dets_array)
        t_track = (time.perf_counter() - t_trk0) * 1000.0

        active_track_count = len(online_tracks)
        if active_track_count > self.max_concurrent_tracks:
            self.max_concurrent_tracks = active_track_count

        # 3. Associate ByteTrack Tracks to Face Detections via IoU & Apply Track-Gated Recognition
        frame_tracks_output: list[FrameTrackInfo] = []
        t_arcface = 0.0
        t_match = 0.0
        arcface_calls_this_frame = 0

        if online_tracks and len(dets_for_tracker) > 0:
            tb = np.array([tr.tlbr for tr in online_tracks])
            fb = np.array([d["scaled_bbox"] for d in dets_for_tracker])
            ious = box_iou(tb, fb)

            for tr_idx, tr in enumerate(online_tracks):
                track_id = int(tr.track_id)
                best_face_idx = int(np.argmax(ious[tr_idx]))

                if track_id not in self.tracks:
                    self.tracks[track_id] = TrackEvidence(
                        track_id=track_id,
                        first_seen=video_frame.timestamp,
                        last_seen=video_frame.timestamp,
                    )

                evidence = self.tracks[track_id]
                prior_switches = evidence.identity_switches
                matched_iou = ious[tr_idx, best_face_idx]

                if matched_iou >= 0.3:
                    face = dets_for_tracker[best_face_idx]["face"]

                    # TRACK-GATED RECOGNITION (Step 2D.4C):
                    # Only execute ArcFace if this track is NOT yet confirmed
                    if not evidence.is_confirmed:
                        t_rec0 = time.perf_counter()
                        if "recognition" in self.app.models:
                            self.app.models["recognition"].get(proc_frame, face)
                        t_arcface += (time.perf_counter() - t_rec0) * 1000.0
                        arcface_calls_this_frame += 1

                        t_m0 = time.perf_counter()
                        identity, score, r_name, margin = self.match_identity(face.embedding)
                        t_match += (time.perf_counter() - t_m0) * 1000.0

                        evidence.add_observation(
                            identity=identity,
                            score=score,
                            bbox=tuple(float(v) for v in tr.tlbr),
                            timestamp=video_frame.timestamp,
                            min_supporting_frames=self.min_supporting_frames,
                            max_unknown_attempts=self.min_supporting_frames,
                        )
                    else:
                        # Track is ALREADY CONFIRMED: Skip ArcFace entirely!
                        evidence.update_position(
                            bbox=tuple(float(v) for v in tr.tlbr),
                            timestamp=video_frame.timestamp,
                        )
                else:
                    # Unassociated track in this frame
                    evidence.update_position(
                        bbox=tuple(float(v) for v in tr.tlbr),
                        timestamp=video_frame.timestamp,
                    )

                if evidence.identity_switches > prior_switches:
                    self.total_identity_switches += (evidence.identity_switches - prior_switches)

                frame_tracks_output.append(
                    FrameTrackInfo(
                        track_id=track_id,
                        identity=evidence.assigned_identity,
                        confidence=evidence.assigned_confidence,
                        bbox=evidence.last_bbox,
                        supporting_frames=evidence.supporting_frames,
                        is_confirmed=evidence.is_confirmed,
                    )
                )

        t_landmark_3d = 0.0
        t_landmark_2d = 0.0
        t_genderage = 0.0
        t_embed = t_arcface + t_match
        t_total = (time.perf_counter() - t_start) * 1000.0

        # Update telemetry
        self.processed_frames += 1
        self.total_arcface_calls += arcface_calls_this_frame
        self.arcface_calls_per_frame.append(arcface_calls_this_frame)
        self.latencies_total.append(t_total)
        self.latencies_detect.append(t_detect)
        self.latencies_landmark_3d.append(t_landmark_3d)
        self.latencies_landmark_2d.append(t_landmark_2d)
        self.latencies_genderage.append(t_genderage)
        self.latencies_arcface.append(t_arcface)
        self.latencies_embed.append(t_embed)
        self.latencies_track.append(t_track)

        confirmed_count = sum(1 for tr in self.tracks.values() if tr.is_confirmed)

        return FrameCVResult(
            source_id=video_frame.source_id,
            source_type=video_frame.source_type,
            frame_index=video_frame.frame_index,
            timestamp=video_frame.timestamp,
            resolution=(video_frame.width, video_frame.height),
            face_count=face_count,
            active_tracks_count=active_track_count,
            tracks=frame_tracks_output,
            latency_total_ms=t_total,
            latency_detection_ms=t_detect,
            latency_embedding_ms=t_embed,
            latency_tracking_ms=t_track,
            latency_arcface_ms=t_arcface,
            latency_landmark_3d_ms=t_landmark_3d,
            latency_landmark_2d_ms=t_landmark_2d,
            latency_genderage_ms=t_genderage,
            arcface_calls=arcface_calls_this_frame,
            confirmed_tracks_count=confirmed_count,
        )

    def get_benchmark_telemetry(self, dropped_frames: int = 0) -> dict[str, Any]:
        """Compute aggregated benchmark performance metrics."""
        elapsed_sec = max(time.perf_counter() - self._start_perf_time, 0.001)
        proc_fps = self.processed_frames / elapsed_sec if self.processed_frames > 0 else 0.0

        avg_lat = float(np.mean(self.latencies_total)) if self.latencies_total else 0.0
        p95_lat = float(np.percentile(self.latencies_total, 95)) if self.latencies_total else 0.0
        det_avg = float(np.mean(self.latencies_detect)) if self.latencies_detect else 0.0
        l3d_avg = float(np.mean(self.latencies_landmark_3d)) if self.latencies_landmark_3d else 0.0
        l2d_avg = float(np.mean(self.latencies_landmark_2d)) if self.latencies_landmark_2d else 0.0
        ga_avg = float(np.mean(self.latencies_genderage)) if self.latencies_genderage else 0.0
        arcface_avg = float(np.mean(self.latencies_arcface)) if self.latencies_arcface else 0.0
        emb_avg = float(np.mean(self.latencies_embed)) if self.latencies_embed else 0.0
        trk_avg = float(np.mean(self.latencies_track)) if self.latencies_track else 0.0

        avg_arcface_calls = float(np.mean(self.arcface_calls_per_frame)) if self.arcface_calls_per_frame else 0.0
        confirmed_count = sum(1 for tr in self.tracks.values() if tr.is_confirmed)

        unknown_tracks = sum(
            1 for tr in self.tracks.values() if tr.assigned_identity == "UNKNOWN"
        )

        return {
            "source_id": self.source_id,
            "processed_frames": self.processed_frames,
            "processing_fps": round(proc_fps, 2),
            "max_concurrent_faces": self.max_concurrent_faces,
            "max_concurrent_tracks": self.max_concurrent_tracks,
            "active_tracks_count": len(self.tracks),
            "identity_switches": self.total_identity_switches,
            "unknown_identities": unknown_tracks,
            "confirmed_identities": confirmed_count,
            "arcface_calls_total": self.total_arcface_calls,
            "arcface_calls_avg": round(avg_arcface_calls, 1),
            "dropped_frames": dropped_frames,
            "avg_latency_ms": round(avg_lat, 2),
            "p95_latency_ms": round(p95_lat, 2),
            "detection_avg_ms": round(det_avg, 2),
            "landmark_3d_avg_ms": round(l3d_avg, 2),
            "landmark_2d_avg_ms": round(l2d_avg, 2),
            "genderage_avg_ms": round(ga_avg, 2),
            "arcface_avg_ms": round(arcface_avg, 2),
            "embedding_avg_ms": round(emb_avg, 2),
            "tracking_avg_ms": round(trk_avg, 2),
            "track_identities": {
                tr.track_id: {
                    "identity": tr.assigned_identity,
                    "confidence": round(tr.assigned_confidence, 2),
                    "frames": tr.total_frames,
                    "supporting_frames": tr.supporting_frames,
                    "is_confirmed": tr.is_confirmed,
                }
                for tr in self.tracks.values()
            },
        }


    def format_benchmark_report(
        self,
        resolution: tuple[int, int] = (1280, 720),
        input_fps: float = 30.0,
        dropped_frames: int = 0,
    ) -> str:
        """Format the exact WebRTC CV Benchmark summary requested in Step 2D.3."""
        telemetry = self.get_benchmark_telemetry(dropped_frames=dropped_frames)

        proc_res = self.processing_resolution or resolution
        lines = [
            "============================================================",
            "WebRTC CV Benchmark",
            "------------------------------------------------------------",
            f"Source: {telemetry['source_id']}",
            f"Camera Input Res : {resolution[0]}x{resolution[1]}",
            f"CV Processing Res: {proc_res[0]}x{proc_res[1]}",
            f"Input FPS        : {input_fps:.1f}",
            f"Processing FPS   : {telemetry['processing_fps']:.1f}",
            "",
            f"Concurrent faces : {telemetry['max_concurrent_faces']}",
            f"Active tracks    : {telemetry['max_concurrent_tracks']}",
            f"Confirmed tracks : {telemetry['confirmed_identities']}",
            "",
        ]

        # Individual track listings
        for tr_id, tr_info in sorted(telemetry["track_identities"].items()):
            conf_tag = "[CONFIRMED]" if tr_info.get("is_confirmed") else "[VOTING]"
            lines.append(
                f"Track {tr_id:02d} {conf_tag:<11} -> {tr_info['identity']:<10} "
                f"(confidence: {tr_info['confidence']:.2f}, frames: {tr_info['frames']})"
            )

        lines.extend([
            "",
            f"Identity switches: {telemetry['identity_switches']}",
            f"Confirmed identities: {telemetry['confirmed_identities']}",
            f"Unknown identities: {telemetry['unknown_identities']}",
            f"ArcFace calls/frame: {telemetry['arcface_calls_avg']}",
            f"Dropped frames: {telemetry['dropped_frames']}",
            f"Average processing latency: {telemetry['avg_latency_ms']}ms (p95: {telemetry['p95_latency_ms']}ms)",
            f"  - SCRFD Detection : {telemetry['detection_avg_ms']}ms",
            f"  - Landmark 3D     : {telemetry['landmark_3d_avg_ms']}ms",
            f"  - Landmark 2D     : {telemetry['landmark_2d_avg_ms']}ms",
            f"  - Gender/Age      : {telemetry['genderage_avg_ms']}ms",
            f"  - ArcFace Recog   : {telemetry['arcface_avg_ms']}ms",
            f"  - Embedding Match : {telemetry['embedding_avg_ms']}ms",
            f"  - Tracking        : {telemetry['tracking_avg_ms']}ms",
            "------------------------------------------------------------",
        ])

        return "\n".join(lines)


    def render_console_view(self, frame_result: FrameCVResult) -> str:
        """Render a clean ASCII visual representation of the active video frame."""
        lines = [
            "+----------------------------------------------------------+",
            f"| [LIVE PHONE FEED]: {frame_result.source_id:<37}|",
            f"| Frame #{frame_result.frame_index:04d} | Res: {frame_result.resolution[0]}x{frame_result.resolution[1]} | Latency: {frame_result.latency_total_ms:.1f}ms |",
            "+----------------------------------------------------------+",
        ]

        if not frame_result.tracks:
            lines.append("|    [No subjects detected in frame]                       |")
        else:
            for tr in frame_result.tracks:
                tag = "[ID]" if tr.identity != "UNKNOWN" else "[?]"
                lines.append(
                    f"|  {tag} Track {tr.track_id:02d} -> {tr.identity:<10} "
                    f"conf: {tr.confidence:.2f} (frames: {tr.supporting_frames:02d})        |"
                )

        lines.append("+----------------------------------------------------------+")
        return "\n".join(lines)
