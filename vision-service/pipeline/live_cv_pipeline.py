from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import math
import os
from pathlib import Path
import time
from typing import Any, Optional, Tuple
import uuid


import cv2
from insightface.app import FaceAnalysis
import numpy as np

from camera.base import VideoFrame, VideoSourceType
from tracking.bytetrack import BYTETracker, box_iou

logger = logging.getLogger(__name__)


def classify_point_side(
    cx: float,
    cy: float,
    boundary_p1: tuple[float, float],
    boundary_p2: tuple[float, float],
    deadband: float = 4.0,
) -> str:
    """Classify 2D point relative to directed boundary line P1 -> P2.

    Returns:
      "SIDE_A": Point is on Side A (approach / outside zone)
      "SIDE_B": Point is on Side B (entered / inside zone)
      "ON_LINE": Point is within hysteresis deadband (+/- deadband pixels)
    """
    x1, y1 = boundary_p1
    x2, y2 = boundary_p2

    # Horizontal boundary line
    if abs(y2 - y1) < 1e-5:
        line_y = y1
        if cy < line_y - deadband:
            return "SIDE_A"
        elif cy > line_y + deadband:
            return "SIDE_B"
        else:
            return "ON_LINE"

    # General line
    if abs(x2 - x1) > 1e-5:
        slope = (y2 - y1) / (x2 - x1)
        line_y = y1 + slope * (cx - x1)
        if cy < line_y - deadband:
            return "SIDE_A"
        elif cy > line_y + deadband:
            return "SIDE_B"
        else:
            return "ON_LINE"
    else:
        # Vertical boundary line
        line_x = x1
        if cx < line_x - deadband:
            return "SIDE_A"
        elif cx > line_x + deadband:
            return "SIDE_B"
        else:
            return "ON_LINE"


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two 512-d feature vectors."""
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


# No built-in mapping from fixture folder names to accounts. Callers that want
# to rename gallery labels pass their own identity_map.
DEFAULT_IDENTITY_MAP: dict[str, str] = {}


@dataclass
class FunnelCounters:
    """10-stage funnel counter tracking end-to-end event progression."""

    frames_in: int = 0
    faces_detected: int = 0
    tracks_active: int = 0
    tracks_confirmed: int = 0
    crossings_detected: int = 0
    crossings_discarded_unconfirmed: int = 0
    events_dispatched: int = 0
    http_2xx: int = 0
    backend_stored: int = 0
    in_active_session: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "frames_in": self.frames_in,
            "faces_detected": self.faces_detected,
            "tracks_active": self.tracks_active,
            "tracks_confirmed": self.tracks_confirmed,
            "crossings_detected": self.crossings_detected,
            "crossings_discarded_unconfirmed": self.crossings_discarded_unconfirmed,
            "events_dispatched": self.events_dispatched,
            "http_2xx": self.http_2xx,
            "backend_stored": self.backend_stored,
            "in_active_session": self.in_active_session,
        }

    def summary_str(self) -> str:
        return (
            f"Funnel: frames_in={self.frames_in} -> faces={self.faces_detected} -> "
            f"tracks={self.tracks_active} (conf={self.tracks_confirmed}) -> "
            f"crossings={self.crossings_detected} (discarded_unconf={self.crossings_discarded_unconfirmed}) -> "
            f"dispatched={self.events_dispatched} -> http_2xx={self.http_2xx} -> "
            f"stored={self.backend_stored} -> active_session={self.in_active_session}"
        )


def load_gallery_from_npz(npz_path: Path | str) -> dict[str, np.ndarray]:
    """Load reference ArcFace embeddings from an .npz file (labels + embeddings)."""
    p = Path(npz_path)
    if not p.exists():
        raise FileNotFoundError(f"Gallery npz not found: {p}")
    data = np.load(str(p))
    labels = data["labels"]
    embs = data["embeddings"]
    gallery: dict[str, np.ndarray] = {}
    for lbl, emb in zip(labels, embs):
        vec = np.asarray(emb, dtype=np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        gallery[str(lbl)] = vec
    return gallery


def load_gallery(
    app: FaceAnalysis,
    gallery_dir: Path,
    enable_quality_gates: bool = False,
    min_face_size: int = 80,
    min_det_score: float = 0.60,
    min_sharpness: float = 50.0,
    identity_map: Optional[dict[str, str]] = None,
) -> dict[str, np.ndarray]:
    """Extract reference ArcFace embeddings for all enrolled identities.

    If enable_quality_gates is True, per-image quality gates and quality-weighted
    mean fusion are applied. Otherwise, standard detection and arithmetic mean are used.
    Gallery labels are the folder names unless an identity_map renames them.
    """
    id_map = identity_map if identity_map is not None else DEFAULT_IDENTITY_MAP
    gallery: dict[str, np.ndarray] = {}
    if not gallery_dir.exists():
        raise FileNotFoundError(f"Gallery directory not found: {gallery_dir}")

    for person_dir in sorted(gallery_dir.iterdir()):
        if not person_dir.is_dir():
            continue
        raw_name = person_dir.name
        person_name = id_map.get(raw_name, raw_name)
        img_paths = sorted(
            p for p in person_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )

        embeddings: list[np.ndarray] = []
        weights: list[float] = []

        for img_path in img_paths:
            img = cv2.imread(str(img_path))
            if img is None:
                continue

            if enable_quality_gates:
                from enrollment.quality_gates import check_image_quality

                res = check_image_quality(
                    img,
                    app=app,
                    min_face_size=min_face_size,
                    min_det_score=min_det_score,
                    min_sharpness=min_sharpness,
                )
                if res.passed and res.embedding is not None:
                    embeddings.append(res.embedding)
                    import math

                    w = res.det_score * math.log(1.0 + max(res.sharpness, 0.0))
                    weights.append(max(w, 1e-4))
            else:
                faces = app.get(img)
                if faces:
                    best_face = max(faces, key=lambda f: f.det_score)
                    embeddings.append(best_face.embedding)
                    weights.append(1.0)

        if embeddings:
            total_w = sum(weights)
            weighted_emb = np.zeros_like(embeddings[0], dtype=np.float32)
            for w, emb in zip(weights, embeddings):
                weighted_emb += (float(w / total_w) * emb).astype(np.float32)
            norm = np.linalg.norm(weighted_emb)
            mean_emb = weighted_emb / (norm + 1e-10)
            gallery[person_name] = mean_emb.astype(np.float32)

    return gallery


def load_gallery_from_backend(
    backend_url: str,
    auth_token: str,
    timeout: float = 5.0,
) -> dict[str, np.ndarray]:
    """Fetch active biometric mean embeddings from the restricted backend gallery endpoint."""
    import requests

    headers = {"Authorization": f"Bearer {auth_token}"}
    url = f"{backend_url.rstrip('/')}/api/v1/enrollment/gallery"
    resp = requests.get(url, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch gallery from backend: HTTP {resp.status_code} - {resp.text}"
        )
    data = resp.json()
    gallery: dict[str, np.ndarray] = {}
    for ident, vec in data.get("gallery", {}).items():
        arr = np.array(vec, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        gallery[ident] = arr.astype(np.float32)
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
    raw_str = str(detector_type)
    mapped_path = det_map.get(raw_str.lower(), raw_str)
    path = os.path.expanduser(mapped_path)
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

    # Boundary crossing & Direction tracking (Step 2D.5 / 2E.5)
    initial_side: Optional[str] = None
    current_side: Optional[str] = None
    side_history: list[str] = field(default_factory=list)
    pending_directions: list[str] = field(default_factory=list)
    # 2E.5: Replace set with sequence log to allow re-entry (ENTRY->EXIT->ENTRY)
    # while blocking jitter duplicates (ENTRY->ENTRY).
    emitted_directions: set[str] = field(default_factory=set)  # Legacy compat
    emitted_sequence: list[str] = field(default_factory=list)
    last_emitted_direction: Optional[str] = None

    # ID-swap guard (Step 2E.5): periodic re-verification of confirmed tracks
    last_reverification_time: Optional[datetime] = None
    reverification_interval_sec: float = 10.0  # Re-verify identity every N seconds
    reverification_disagreement_count: int = 0
    max_disagreement_before_reset: int = 3  # Consecutive disagreements before reset

    # Kinematic anti-spoofing trajectory tracking (Step 2E.7)
    first_bbox: Optional[tuple[float, float, float, float]] = None
    crossing_displacement_px: float = 0.0
    transit_duration_sec: float = 0.0
    kinematic_status: str = (
        "NORMAL"  # "NORMAL", "FLAGGED_STATIONARY", "FLAGGED_INSTANT", "FLAGGED_HOVER"
    )
    kinematic_anomalies: list[str] = field(default_factory=list)

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
        if self.first_bbox is None:
            self.first_bbox = bbox

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
                if self.assigned_identity != "UNKNOWN" and self.assigned_identity != top_candidate:
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
                if not self.is_confirmed:
                    # First confirmation — start reverification timer from now
                    self.last_reverification_time = timestamp
                self.is_confirmed = True
            elif self.recognition_attempts >= max_unknown_attempts:
                self.assigned_identity = "UNKNOWN"
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
        if self.first_bbox is None:
            self.first_bbox = bbox

    def update_boundary_position(
        self,
        bbox: tuple[float, float, float, float],
        boundary_p1: tuple[float, float],
        boundary_p2: tuple[float, float],
        deadband: float = 4.0,
        entry_side: str = "SIDE_A",
        timestamp: Optional[datetime] = None,
        min_track_displacement_px: float = 15.0,
        min_transit_duration_sec: float = 0.20,
        max_stationary_duration_sec: float = 8.0,
    ) -> Optional[str]:
        """Update track trajectory and evaluate boundary line crossing.

        Returns new crossing direction ("ENTRY" or "EXIT") if boundary was crossed.
        entry_side controls which side is the "approach" zone:
          - "SIDE_A" (default): A->B = ENTRY, B->A = EXIT
          - "SIDE_B":          B->A = ENTRY, A->B = EXIT
        """
        if self.first_bbox is None:
            self.first_bbox = bbox

        cx = (bbox[0] + bbox[2]) / 2.0
        cy = (bbox[1] + bbox[3]) / 2.0
        side = classify_point_side(cx, cy, boundary_p1, boundary_p2, deadband=deadband)

        new_direction: Optional[str] = None
        if side != "ON_LINE":
            if self.initial_side is None:
                self.initial_side = side
                self.current_side = side
            elif self.current_side != side:
                # Determine ENTRY/EXIT based on configurable entry_side
                if entry_side == "SIDE_A":
                    if self.current_side == "SIDE_A" and side == "SIDE_B":
                        new_direction = "ENTRY"
                    elif self.current_side == "SIDE_B" and side == "SIDE_A":
                        new_direction = "EXIT"
                else:  # entry_side == "SIDE_B"
                    if self.current_side == "SIDE_B" and side == "SIDE_A":
                        new_direction = "ENTRY"
                    elif self.current_side == "SIDE_A" and side == "SIDE_B":
                        new_direction = "EXIT"
                self.current_side = side

        self.side_history.append(side)

        # 2E.5 FIX: Allow re-entry by checking against last_emitted_direction
        # instead of a set of all ever-emitted directions.
        # This blocks jitter duplicates (ENTRY->ENTRY) but allows
        # legitimate re-entry sequences (ENTRY->EXIT->ENTRY).
        if new_direction and new_direction != self.last_emitted_direction:
            # Kinematic anti-spoof checks (Step 2E.7)
            if self.first_bbox is not None:
                cx0 = (self.first_bbox[0] + self.first_bbox[2]) / 2.0
                cy0 = (self.first_bbox[1] + self.first_bbox[3]) / 2.0
                self.crossing_displacement_px = float(math.hypot(cx - cx0, cy - cy0))
            else:
                self.crossing_displacement_px = 0.0

            curr_time = timestamp or self.last_seen
            if self.first_seen:
                self.transit_duration_sec = max(
                    0.0, float((curr_time - self.first_seen).total_seconds())
                )
            else:
                self.transit_duration_sec = 0.0

            anomalies = []
            if self.crossing_displacement_px < min_track_displacement_px:
                anomalies.append("INSUFFICIENT_DISPLACEMENT")
            if self.transit_duration_sec < min_transit_duration_sec:
                anomalies.append("INSTANT_TRANSIT")
            if (
                self.transit_duration_sec > max_stationary_duration_sec
                and self.crossing_displacement_px < (min_track_displacement_px * 1.5)
            ):
                anomalies.append("STATIONARY_HOVER")

            if anomalies:
                self.kinematic_anomalies = anomalies
                if "INSUFFICIENT_DISPLACEMENT" in anomalies:
                    self.kinematic_status = "FLAGGED_STATIONARY"
                elif "INSTANT_TRANSIT" in anomalies:
                    self.kinematic_status = "FLAGGED_INSTANT"
                else:
                    self.kinematic_status = "FLAGGED_HOVER"
            else:
                self.kinematic_status = "NORMAL"
                self.kinematic_anomalies = []

            if new_direction not in self.pending_directions:
                self.pending_directions.append(new_direction)

        return new_direction

    def get_emittable_directions(self) -> list[str]:
        """Safety Gate Rule (Step 2D.5 / 2E.5):
        Only confirmed, known identities (not UNKNOWN) can produce attendance events.
        Jitter duplicates are suppressed by checking against last_emitted_direction.
        """
        if not self.is_confirmed:
            return []
        if self.assigned_identity == "UNKNOWN" or not self.assigned_identity:
            return []

        emittable = []
        for direction in list(self.pending_directions):
            # Block consecutive duplicates but allow re-entry
            if direction != self.last_emitted_direction:
                emittable.append(direction)
        return emittable

    def mark_emitted(self, direction: str) -> None:
        """Record that a direction event was emitted (2E.5).

        Tracks the full emission sequence and updates last_emitted_direction
        for jitter suppression while allowing legitimate re-crossings.
        """
        self.last_emitted_direction = direction
        self.emitted_sequence.append(direction)
        self.emitted_directions.add(direction)  # Legacy compat
        if direction in self.pending_directions:
            self.pending_directions.remove(direction)

    def needs_reverification(self, current_time: datetime) -> bool:
        """ID-swap guard (2E.5): Check if a confirmed track is due for re-verification."""
        if not self.is_confirmed:
            return False
        if self.assigned_identity == "UNKNOWN":
            return False
        if self.last_reverification_time is None:
            return True
        elapsed = (current_time - self.last_reverification_time).total_seconds()
        return elapsed >= self.reverification_interval_sec

    def reverify_identity(
        self,
        observed_identity: str,
        observed_score: float,
        current_time: datetime,
    ) -> bool:
        """ID-swap guard (2E.5): Compare live ArcFace result against confirmed identity.

        Returns True if identity is still consistent, False if disagreement detected.
        On sustained disagreement (>= max_disagreement_before_reset), resets confirmation
        so the track must re-earn its identity through the normal voting process.
        """
        self.last_reverification_time = current_time

        if observed_identity == self.assigned_identity:
            # Agreement — reset disagreement counter
            self.reverification_disagreement_count = 0
            return True

        # Disagreement detected
        self.reverification_disagreement_count += 1
        logger.warning(
            "Track %d reverification disagreement %d/%d: confirmed=%s observed=%s (score=%.3f)",
            self.track_id,
            self.reverification_disagreement_count,
            self.max_disagreement_before_reset,
            self.assigned_identity,
            observed_identity,
            observed_score,
        )

        if self.reverification_disagreement_count >= self.max_disagreement_before_reset:
            self.invalidate_confirmation()
        return False

    def invalidate_confirmation(self) -> None:
        """ID-swap guard (2E.5): Reset confirmation state, forcing re-earning identity.

        Clears votes and similarity history but preserves trajectory and boundary state.
        No events will be emitted until the track re-confirms through normal voting.
        """
        logger.warning(
            "Track %d confirmation INVALIDATED after %d disagreements (was: %s). "
            "Track must re-confirm identity before further events.",
            self.track_id,
            self.reverification_disagreement_count,
            self.assigned_identity,
        )
        self.is_confirmed = False
        self.assigned_identity = "UNKNOWN"
        self.assigned_confidence = 0.0
        self.identity_votes = defaultdict(int)
        self.similarities = defaultdict(list)
        self.supporting_frames = 0
        self.recognition_attempts = 0
        self.reverification_disagreement_count = 0


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
    emitted_events: list[dict[str, Any]] = field(default_factory=list)


class LiveCVPipeline:
    """Connects incoming VideoFrames (from any video source) to InsightFace + ByteTrack."""

    def __init__(
        self,
        app: FaceAnalysis,
        gallery: dict[str, np.ndarray],
        tracker: Optional[BYTETracker] = None,
        similarity_threshold: Optional[float] = None,
        min_margin: Optional[float] = None,
        min_supporting_frames: int = 3,
        source_id: str = "PHONE_CAM_01",
        processing_resolution: Optional[Tuple[int, int]] = None,
        boundary_line: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None,
        deadband_pixels: float = 4.0,
        entry_side: str = "SIDE_A",
        event_dispatcher: Optional[Any] = None,
        camera_id: Optional[str] = None,
        reverification_interval_sec: float = 10.0,
        max_reverification_disagreement: int = 3,
        enable_kinematic_anti_spoof: Optional[bool] = None,
        min_track_displacement_px: float = 15.0,
        min_transit_duration_sec: float = 0.20,
        max_stationary_duration_sec: float = 8.0,
        kinematic_spoof_policy: str = "FLAG",
        camera_role: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> None:
        if similarity_threshold is None:
            env_thresh = os.getenv("RECOGNITION_SIMILARITY_THRESHOLD") or os.getenv(
                "SIMILARITY_THRESHOLD"
            )
            similarity_threshold = float(env_thresh) if env_thresh else 0.50
        if min_margin is None:
            env_margin = os.getenv("RECOGNITION_MIN_MARGIN")
            min_margin = float(env_margin) if env_margin else 0.15

        if enable_kinematic_anti_spoof is None:
            env_val = os.getenv("ENABLE_KINEMATIC_ANTI_SPOOF", "true").lower()
            enable_kinematic_anti_spoof = env_val in ("true", "1", "yes")

        env_policy = os.getenv("KINEMATIC_SPOOF_POLICY")
        if env_policy:
            kinematic_spoof_policy = env_policy.upper()

        if kinematic_spoof_policy not in ("FLAG", "REJECT"):
            raise ValueError(
                f"kinematic_spoof_policy must be 'FLAG' or 'REJECT', got '{kinematic_spoof_policy}'"
            )

        self.app = app
        self.gallery = gallery
        self.similarity_threshold = similarity_threshold
        self.min_margin = min_margin
        self.min_supporting_frames = min_supporting_frames
        self.source_id = source_id
        self.camera_id = camera_id or source_id
        self.processing_resolution = processing_resolution
        self.boundary_line = boundary_line
        self.deadband_pixels = deadband_pixels
        self.entry_side = entry_side
        self.event_dispatcher = event_dispatcher
        self.reverification_interval_sec = reverification_interval_sec
        self.max_reverification_disagreement = max_reverification_disagreement
        self.enable_kinematic_anti_spoof = enable_kinematic_anti_spoof
        self.min_track_displacement_px = min_track_displacement_px
        self.min_transit_duration_sec = min_transit_duration_sec
        self.max_stationary_duration_sec = max_stationary_duration_sec
        self.kinematic_spoof_policy = kinematic_spoof_policy

        if camera_role is None:
            env_role = os.getenv("CAMERA_ROLE")
            camera_role = env_role if env_role else "BOTH"

        role_clean = camera_role.upper().strip()
        if role_clean not in ("ENTRY", "EXIT", "BOTH"):
            raise ValueError(f"camera_role must be 'ENTRY', 'EXIT', or 'BOTH', got '{camera_role}'")
        self.camera_role = role_clean

        # Validate entry_side
        if self.entry_side not in ("SIDE_A", "SIDE_B"):
            raise ValueError(f"entry_side must be 'SIDE_A' or 'SIDE_B', got '{self.entry_side}'")

        # Validate boundary_line endpoints if provided (normalized 0..1 or pixel coords)
        if self.boundary_line is not None:
            p1, p2 = self.boundary_line
            if len(p1) != 2 or len(p2) != 2:
                raise ValueError(f"boundary_line endpoints must be 2-tuples, got {p1}, {p2}")
            if p1 == p2:
                raise ValueError("boundary_line endpoints must not be identical")

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
        self.total_arcface_calls: int = 0
        self.arcface_calls_per_frame: list[int] = []

        # Dispatched sensory events (Step 2D.5)
        self.dispatched_events: list[dict[str, Any]] = []

        # Latency telemetry (milliseconds)
        self.latencies_total: list[float] = []
        self.latencies_detect: list[float] = []
        self.latencies_landmark_3d: list[float] = []
        self.latencies_landmark_2d: list[float] = []
        self.latencies_genderage: list[float] = []
        self.latencies_arcface: list[float] = []
        self.latencies_embed: list[float] = []
        self.latencies_track: list[float] = []

        # Normalized boundary points
        if self.boundary_line is not None:
            p1_raw, p2_raw = self.boundary_line
            if p1_raw[0] <= 1.0 and p1_raw[1] <= 1.0 and p2_raw[0] <= 1.0 and p2_raw[1] <= 1.0:
                self.p1_norm = (float(p1_raw[0]), float(p1_raw[1]))
                self.p2_norm = (float(p2_raw[0]), float(p2_raw[1]))
            else:
                self.p1_norm = (0.0, 0.5)
                self.p2_norm = (1.0, 0.5)
        else:
            self.p1_norm = (0.0, 0.5)
            self.p2_norm = (1.0, 0.5)

        from pipeline.identity_boundary import IdentityBoundary

        self.identity_boundary = IdentityBoundary(
            a=self.p1_norm,
            b=self.p2_norm,
            deadband=0.02,
            pending_ttl=4.0,
            infer_window=3.0,
            cooldown=2.0,
            entry_side=self.entry_side,
        )

        # One-time face recognition attendance state
        if mode is not None:
            self.mode = mode
        else:
            self.mode = os.getenv(
                "ATTENDANCE_MODE",
                "BOUNDARY_CROSSING" if boundary_line is not None else "ONE_TIME_ATTENDANCE",
            )
        self.session_marked_students: set[str] = set()
        self.last_recognized_student: Optional[str] = None
        self.last_recognized_time: float = 0.0

        # 10-stage funnel counters
        self.funnel = FunnelCounters()

        self._start_perf_time: float = time.perf_counter()

    def reset_session_attendance(self) -> None:
        """Reset marked students for a new attendance session."""
        self.session_marked_students.clear()
        self.last_recognized_student = None
        self.last_recognized_time = 0.0

    def reload_gallery(self, new_gallery: dict[str, np.ndarray]) -> int:
        """Dynamically reload or update the biometric recognition gallery.

        Allows recognizing newly enrolled students in real-time without restarting
        the video stream or pipeline.
        Returns the new total count of enrolled identities.
        """
        self.gallery = dict(new_gallery)
        logger.info("Biometric gallery reloaded: %d active identities", len(self.gallery))
        return len(self.gallery)

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

        if self.processing_resolution is not None and self.processing_resolution != (
            orig_w,
            orig_h,
        ):
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
                scaled_bbox = (
                    float(x1 * scale_x),
                    float(y1 * scale_y),
                    float(x2 * scale_x),
                    float(y2 * scale_y),
                )
            else:
                scaled_bbox = (float(x1), float(y1), float(x2), float(y2))
            dets_for_tracker.append(
                {
                    "face": face,
                    "scaled_bbox": scaled_bbox,
                    "det_score": float(face.det_score),
                }
            )

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
                        reverification_interval_sec=self.reverification_interval_sec,
                        max_disagreement_before_reset=self.max_reverification_disagreement,
                    )

                evidence = self.tracks[track_id]
                prior_switches = evidence.identity_switches
                matched_iou = ious[tr_idx, best_face_idx]

                if matched_iou >= 0.3:
                    face = dets_for_tracker[best_face_idx]["face"]

                    # TRACK-GATED RECOGNITION (Step 2D.4C / 2E.5 ID-swap guard):
                    # Run ArcFace if: (a) track not confirmed, OR
                    #                 (b) confirmed but due for periodic re-verification
                    run_arcface = not evidence.is_confirmed or evidence.needs_reverification(
                        video_frame.timestamp
                    )

                    if run_arcface:
                        t_rec0 = time.perf_counter()
                        if "recognition" in self.app.models:
                            self.app.models["recognition"].get(proc_frame, face)
                        t_arcface += (time.perf_counter() - t_rec0) * 1000.0
                        arcface_calls_this_frame += 1

                        t_m0 = time.perf_counter()
                        identity, score, r_name, margin = self.match_identity(face.embedding)
                        t_match += (time.perf_counter() - t_m0) * 1000.0

                        if evidence.is_confirmed:
                            # Re-verification of already confirmed track (ID-swap guard)
                            evidence.reverify_identity(
                                observed_identity=identity,
                                observed_score=score,
                                current_time=video_frame.timestamp,
                            )
                            evidence.update_position(
                                bbox=tuple(float(v) for v in tr.tlbr),
                                timestamp=video_frame.timestamp,
                            )
                        else:
                            # Initial confirmation voting (allow several attempts before UNKNOWN)
                            evidence.add_observation(
                                identity=identity,
                                score=score,
                                bbox=tuple(float(v) for v in tr.tlbr),
                                timestamp=video_frame.timestamp,
                                min_supporting_frames=self.min_supporting_frames,
                                max_unknown_attempts=max(self.min_supporting_frames * 5, 15),
                            )
                    else:
                        # Track is confirmed and not due for reverification
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

                # Determine boundary line points in native frame pixels (for legacy kinematic checks)
                if self.boundary_line is not None:
                    p1_raw, p2_raw = self.boundary_line
                    if (
                        p1_raw[0] <= 1.0
                        and p1_raw[1] <= 1.0
                        and p2_raw[0] <= 1.0
                        and p2_raw[1] <= 1.0
                    ):
                        bp1 = (p1_raw[0] * orig_w, p1_raw[1] * orig_h)
                        bp2 = (p2_raw[0] * orig_w, p2_raw[1] * orig_h)
                    else:
                        bp1, bp2 = p1_raw, p2_raw
                else:
                    bp1 = (0.0, orig_h * 0.5)
                    bp2 = (float(orig_w), orig_h * 0.5)

                # Update track displacement and kinematic metrics
                evidence.update_boundary_position(
                    bbox=evidence.last_bbox,
                    boundary_p1=bp1,
                    boundary_p2=bp2,
                    deadband=self.deadband_pixels,
                    entry_side=self.entry_side,
                    timestamp=video_frame.timestamp,
                    min_track_displacement_px=self.min_track_displacement_px,
                    min_transit_duration_sec=self.min_transit_duration_sec,
                    max_stationary_duration_sec=self.max_stationary_duration_sec,
                )

                if evidence.identity_switches > prior_switches:
                    self.total_identity_switches += evidence.identity_switches - prior_switches

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

        # 4. Attendance Evaluation
        emitted_events_this_frame: list[dict[str, Any]] = []
        ts_sec = (
            video_frame.timestamp.timestamp()
            if hasattr(video_frame.timestamp, "timestamp")
            else time.time()
        )

        if self.mode == "ONE_TIME_ATTENDANCE":
            # Direct Face Recognition Attendance (See face -> Confirm ID -> Mark PRESENT once)
            for tr_info in frame_tracks_output:
                tid = tr_info.track_id
                ev = self.tracks.get(tid)
                if not ev or ev.last_bbox is None:
                    continue

                conf_ident = (
                    ev.assigned_identity
                    if (
                        ev.is_confirmed
                        and ev.assigned_identity
                        and ev.assigned_identity != "UNKNOWN"
                    )
                    else None
                )

                if conf_ident:
                    if conf_ident not in self.session_marked_students:
                        self.session_marked_students.add(conf_ident)
                        self.last_recognized_student = conf_ident
                        self.last_recognized_time = time.time()

                        scores = ev.similarities.get(conf_ident, [])
                        peak_sim = max(scores) if scores else ev.assigned_confidence
                        mean_sim = float(np.mean(scores)) if scores else ev.assigned_confidence
                        total_rec_frames = max(ev.recognition_attempts, 1)
                        consistency_pct = (ev.supporting_frames / total_rec_frames) * 100.0

                        event_doc = {
                            "event_id": f"evt_{uuid.uuid4().hex[:16]}",
                            "camera_id": self.camera_id,
                            "track_id": tid,
                            "identity": conf_ident,
                            "direction": "ENTRY",
                            "timestamp": datetime.fromtimestamp(ts_sec, tz=timezone.utc),
                            "evidence": {
                                "peak_similarity": round(float(peak_sim), 4),
                                "mean_similarity": round(float(mean_sim), 4),
                                "supporting_frames": int(ev.supporting_frames),
                                "total_frames": int(ev.recognition_attempts),
                                "consistency_pct": round(float(consistency_pct), 2),
                                "margin_over_runner_up": None,
                                "runner_up_identity": None,
                            },
                            "kinematic_status": "NORMAL",
                            "kinematic_anomalies": [],
                        }

                        if self.event_dispatcher is not None:
                            try:
                                self.event_dispatcher.send_event(event_doc, sync=False)
                            except Exception as exc:
                                logger.error("EventDispatcher error for %s: %s", conf_ident, exc)

                        self.funnel.events_dispatched += 1
                        emitted_events_this_frame.append(event_doc)
                        self.dispatched_events.append(event_doc)
        else:
            # Legacy Boundary Crossing Mode
            if self.boundary_line is not None:
                p1_raw, p2_raw = self.boundary_line
                if p1_raw[0] > 1.0 or p1_raw[1] > 1.0 or p2_raw[0] > 1.0 or p2_raw[1] > 1.0:
                    self.identity_boundary.a = (
                        float(p1_raw[0]) / orig_w,
                        float(p1_raw[1]) / orig_h,
                    )
                    self.identity_boundary.b = (
                        float(p2_raw[0]) / orig_w,
                        float(p2_raw[1]) / orig_h,
                    )
                else:
                    self.identity_boundary.a = (float(p1_raw[0]), float(p1_raw[1]))
                    self.identity_boundary.b = (float(p2_raw[0]), float(p2_raw[1]))
            if self.deadband_pixels > 0:
                self.identity_boundary.deadband = max(0.005, self.deadband_pixels / float(orig_h))

            for tr_info in frame_tracks_output:
                tid = tr_info.track_id
                ev = self.tracks.get(tid)
                if not ev or ev.last_bbox is None:
                    continue

                # Compute normalized center of bounding box
                bx1, by1, bx2, by2 = ev.last_bbox
                cx_norm = ((bx1 + bx2) / 2.0) / float(orig_w)
                cy_norm = ((by1 + by2) / 2.0) / float(orig_h)
                point_norm = (cx_norm, cy_norm)

                conf_ident = (
                    ev.assigned_identity
                    if (
                        ev.is_confirmed
                        and ev.assigned_identity
                        and ev.assigned_identity != "UNKNOWN"
                    )
                    else None
                )

                # Evaluate crossing through IdentityBoundary
                b_crossings = self.identity_boundary.update(
                    track_id=tid,
                    point=point_norm,
                    identity=conf_ident,
                    now=ts_sec,
                )

                for cr in b_crossings:
                    direction = cr["direction"]
                    c_ident = cr["identity"]
                    c_ts = cr["ts"]

                    # Camera role directional enforcement
                    if self.camera_role == "ENTRY" and direction != "ENTRY":
                        logger.debug(
                            "Dropping %s event for %s: camera role is ENTRY", direction, c_ident
                        )
                        continue
                    if self.camera_role == "EXIT" and direction != "EXIT":
                        logger.debug(
                            "Dropping %s event for %s: camera role is EXIT", direction, c_ident
                        )
                        continue

                    # Soft kinematic anti-spoof check (FLAG mode)
                    if self.enable_kinematic_anti_spoof and ev.kinematic_anomalies:
                        if self.kinematic_spoof_policy == "REJECT":
                            logger.warning(
                                "Kinematic anti-spoof REJECTED transit for %s (%s): %s",
                                c_ident,
                                direction,
                                ev.kinematic_anomalies,
                            )
                            continue
                        else:
                            logger.warning(
                                "Kinematic anti-spoof FLAGGED transit for %s (%s): %s",
                                c_ident,
                                direction,
                                ev.kinematic_anomalies,
                            )

                    scores = ev.similarities.get(c_ident, [])
                    peak_sim = max(scores) if scores else ev.assigned_confidence
                    mean_sim = float(np.mean(scores)) if scores else ev.assigned_confidence
                    total_rec_frames = max(ev.recognition_attempts, 1)
                    consistency_pct = (ev.supporting_frames / total_rec_frames) * 100.0

                    event_doc = {
                        "event_id": f"evt_{uuid.uuid4().hex[:16]}",
                        "camera_id": self.camera_id,
                        "track_id": tid,
                        "identity": c_ident,
                        "direction": direction,
                        "timestamp": datetime.fromtimestamp(c_ts, tz=timezone.utc),
                        "evidence": {
                            "peak_similarity": round(float(peak_sim), 4),
                            "mean_similarity": round(float(mean_sim), 4),
                            "supporting_frames": int(ev.supporting_frames),
                            "total_frames": int(ev.recognition_attempts),
                            "consistency_pct": round(float(consistency_pct), 2),
                            "margin_over_runner_up": None,
                            "runner_up_identity": None,
                        },
                        "kinematic_status": ev.kinematic_status,
                        "kinematic_anomalies": list(ev.kinematic_anomalies),
                    }

                    if self.event_dispatcher is not None:
                        try:
                            self.event_dispatcher.send_event(event_doc, sync=False)
                        except Exception as exc:
                            logger.error("EventDispatcher error for track %d: %s", tid, exc)

                    self.funnel.events_dispatched += 1
                    ev.mark_emitted(direction)
                    emitted_events_this_frame.append(event_doc)
                    self.dispatched_events.append(event_doc)

        # Update funnel metrics
        self.funnel.frames_in = self.processed_frames + 1
        self.funnel.faces_detected = self.total_detections
        self.funnel.tracks_active = len(online_tracks)
        self.funnel.tracks_confirmed = sum(
            1
            for tr in self.tracks.values()
            if tr.is_confirmed and tr.assigned_identity != "UNKNOWN"
        )
        self.funnel.crossings_detected = self.identity_boundary.crossings_detected
        self.funnel.crossings_discarded_unconfirmed = (
            self.identity_boundary.crossings_discarded_unconfirmed
        )
        if self.event_dispatcher is not None:
            self.funnel.http_2xx = getattr(self.event_dispatcher, "http_2xx_count", 0)
            self.funnel.backend_stored = getattr(self.event_dispatcher, "backend_stored_count", 0)
            self.funnel.in_active_session = getattr(
                self.event_dispatcher, "in_active_session_count", 0
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
            emitted_events=emitted_events_this_frame,
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

        avg_arcface_calls = (
            float(np.mean(self.arcface_calls_per_frame)) if self.arcface_calls_per_frame else 0.0
        )
        confirmed_count = sum(1 for tr in self.tracks.values() if tr.is_confirmed)

        unknown_tracks = sum(1 for tr in self.tracks.values() if tr.assigned_identity == "UNKNOWN")

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
            "dispatched_events_count": len(self.dispatched_events),
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
        """Format the exact CV Benchmark summary requested in Step 2D.3."""
        telemetry = self.get_benchmark_telemetry(dropped_frames=dropped_frames)

        proc_res = self.processing_resolution or resolution
        lines = [
            "============================================================",
            "CV Benchmark",
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

        lines.extend(
            [
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
            ]
        )

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

        if frame_result.emitted_events:
            for evt in frame_result.emitted_events:
                dir_tag = f"[{evt['direction']}]"
                lines.append(
                    f"|  * {dir_tag:<7} Track {evt['track_id']:02d} -> {evt['identity']:<12} "
                    f"sim: {evt['evidence']['peak_similarity']:.2f}           |"
                )

        lines.append(f"| {self.funnel.summary_str():<56} |")
        lines.append("+----------------------------------------------------------+")
        return "\n".join(lines)

    def render_annotated_frame(
        self, raw_frame: np.ndarray, frame_result: FrameCVResult
    ) -> np.ndarray:
        """Render clean, teacher-friendly attendance annotations onto video frame."""
        vis = raw_frame.copy()
        h, w = vis.shape[:2]

        now = time.time()

        # Draw detected face boxes and recognition tags
        for tr in frame_result.tracks:
            x1, y1, x2, y2 = [int(v) for v in tr.bbox]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w - 1, x2), min(h - 1, y2)
            is_conf = tr.is_confirmed
            ident = tr.identity

            if is_conf and ident != "UNKNOWN":
                if ident in self.session_marked_students:
                    # Already marked present
                    color = (255, 180, 0)  # Cyan/Blue
                    label = f"{ident} - Already Present"
                else:
                    # Newly confirmed
                    color = (0, 230, 0)  # Bright Green
                    label = f"{ident} - PRESENT"
            elif ident == "UNKNOWN":
                color = (0, 0, 220)  # Red
                label = "Unknown Face"
            else:
                color = (0, 215, 255)  # Yellow
                label = "Identifying..."

            # Draw smooth bounding box
            cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)

            # Draw background tag for high text contrast
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            tag_y1 = max(0, y1 - th - 10)
            tag_y2 = y1
            cv2.rectangle(vis, (x1, tag_y1), (x1 + tw + 12, tag_y2), (20, 20, 20), -1)
            cv2.putText(
                vis,
                label,
                (x1 + 6, tag_y2 - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
            )

        # Top Banner: Clean teacher UI (No engineering jargon)
        cv2.rectangle(vis, (0, 0), (w, 36), (20, 20, 20), -1)
        present_count = len(self.session_marked_students)
        header_text = f"AI Face Attendance | Students Present: {present_count}"

        # If someone was recently recognized within last 3.5s, highlight them!
        if self.last_recognized_student and (now - self.last_recognized_time < 3.5):
            header_text = f"{header_text}  |  {self.last_recognized_student} PRESENT"
            banner_color = (0, 255, 120)
        else:
            banner_color = (255, 255, 255)

        cv2.putText(vis, header_text, (12, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.65, banner_color, 2)

        return vis
