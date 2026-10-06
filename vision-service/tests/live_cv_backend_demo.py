from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
import sys
import time
import uuid

import cv2
from insightface.app import FaceAnalysis
import numpy as np

# Allow imports from vision-service/
VISION_SERVICE_DIR = Path(__file__).resolve().parents[1]

if str(VISION_SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(VISION_SERVICE_DIR))

from events.event_dispatcher import EventDispatcher
from tracking.bytetrack import BYTETracker, box_iou


# ============================================================
# CONFIGURATION
# ============================================================

VIDEO_PATH = (
    Path(os.environ.get("VISION_FIXTURES_DIR") or "vision-fixtures-not-configured") / "video_test"
    / "entry_exit_simultaneous.mp4"
    if (Path(os.environ.get("VISION_FIXTURES_DIR") or "vision-fixtures-not-configured") / "video_test" / "entry_exit_simultaneous.mp4").exists()
    else Path(os.environ.get("VISION_FIXTURES_DIR") or "vision-fixtures-not-configured") / "video_test" / "multi_person_simultaneous.mp4"
)

ENROLLMENT_DIR = (
    Path(os.environ.get("VISION_FIXTURES_DIR") or "vision-fixtures-not-configured") / "recognition_benchmark"
    if (Path(os.environ.get("VISION_FIXTURES_DIR") or "vision-fixtures-not-configured") / "recognition_benchmark").exists()
    else VISION_SERVICE_DIR / "tests" / "face_images"
)

TARGET_FPS = 5.0
CAMERA_ID = "CAM_ROOM_101_DOOR"

# Calibrated from Step 4.10.6 multi-person benchmark (0f5bb1d)
RECOGNITION_THRESHOLD = 0.40
MIN_SUPPORTING_FRAMES = 3

# Calibrated perspective boundary across doorway (supports both ENTRY and EXIT)
BOUNDARY_P1 = (0.0, 575.0)
BOUNDARY_P2 = (1152.0, 640.0)
DEADBAND = 4.0


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)

    denominator = np.linalg.norm(a) * np.linalg.norm(b)
    if denominator == 0:
        return 0.0

    return float(np.dot(a, b) / denominator)


def normalize_embedding(embedding: np.ndarray) -> np.ndarray:
    embedding = embedding.astype(np.float32)
    norm = np.linalg.norm(embedding)
    if norm == 0:
        return embedding
    return embedding / norm


# ============================================================
# ENROLLMENT GALLERY
# ============================================================

def load_gallery(app: FaceAnalysis) -> dict[str, np.ndarray]:
    gallery = {}

    if not ENROLLMENT_DIR.exists():
        raise FileNotFoundError(
            f"Enrollment directory not found: {ENROLLMENT_DIR}"
        )

    person_dirs = sorted(
        path for path in ENROLLMENT_DIR.iterdir() if path.is_dir()
    )

    print("\nLoading enrollment gallery...")

    for person_dir in person_dirs:
        embeddings = []

        image_files = sorted(
            path
            for path in person_dir.iterdir()
            if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )

        for image_path in image_files:
            image = cv2.imread(str(image_path))
            if image is None:
                continue

            faces = app.get(image)
            if not faces:
                continue

            face = max(
                faces,
                key=lambda f: (
                    (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])
                ),
            )

            embedding = normalize_embedding(face.embedding)
            embeddings.append(embedding)

        if embeddings:
            mean_embedding = normalize_embedding(
                np.mean(embeddings, axis=0)
            )
            gallery[person_dir.name] = mean_embedding
            print(f"  {person_dir.name}: {len(embeddings)} images")

    if not gallery:
        raise RuntimeError("No enrollment identities loaded.")

    print(f"Gallery loaded: {len(gallery)} identities")
    return gallery


# ============================================================
# RECOGNITION
# ============================================================

def recognize_face(
    embedding: np.ndarray,
    gallery: dict[str, np.ndarray],
):
    embedding = normalize_embedding(embedding)

    scores = {
        person_name: cosine_similarity(embedding, enrolled_embedding)
        for person_name, enrolled_embedding in gallery.items()
    }

    best_identity = max(scores, key=scores.get)
    best_score = scores[best_identity]

    if best_score >= RECOGNITION_THRESHOLD:
        return best_identity, best_score, scores

    return "UNKNOWN", best_score, scores


# ============================================================
# TRACK EVIDENCE
# ============================================================

class TrackEvidence:
    def __init__(self):
        self.identities: list[str] = []
        self.scores: list[float] = []
        self.detections: list[dict] = []
        self.sides: list[str] = []
        self.event_emitted: bool = False
        self.first_timestamp = None
        self.last_timestamp = None

    def add(self, identity: str, score: float, detection: dict, side: str, timestamp):
        self.identities.append(identity)
        self.scores.append(score)
        self.detections.append(detection)
        self.sides.append(side)

        if self.first_timestamp is None:
            self.first_timestamp = timestamp

        self.last_timestamp = timestamp

    def best_identity(self) -> str:
        known = [
            identity for identity in self.identities if identity != "UNKNOWN"
        ]
        if not known:
            return "UNKNOWN"

        counts: dict[str, int] = {}
        for identity in known:
            counts[identity] = counts.get(identity, 0) + 1

        return max(counts, key=counts.get)

    def supporting_frames(self) -> int:
        identity = self.best_identity()
        return sum(
            1 for curr_id in self.identities if curr_id == identity
        )

    def best_score(self) -> float:
        identity = self.best_identity()
        scores = [
            score
            for curr_id, score in zip(self.identities, self.scores)
            if curr_id == identity
        ]
        return max(scores) if scores else 0.0

    def mean_score(self) -> float:
        identity = self.best_identity()
        scores = [
            score
            for curr_id, score in zip(self.identities, self.scores)
            if curr_id == identity
        ]
        if not scores:
            return 0.0
        return float(np.mean(scores))

    def consistency(self) -> float:
        identity = self.best_identity()
        if not self.identities:
            return 0.0

        matching = sum(
            1 for curr_id in self.identities if curr_id == identity
        )
        return (matching / len(self.identities)) * 100.0


# ============================================================
# BOUNDARY LOGIC
# ============================================================

def get_boundary_y_at_x(x: float) -> float:
    """Calculate the Y-threshold of the calibrated boundary line at given X coordinate."""
    x1, y1 = BOUNDARY_P1
    x2, y2 = BOUNDARY_P2
    if x2 == x1:
        return y1
    slope = (y2 - y1) / (x2 - x1)
    return y1 + slope * (x - x1)


def classify_side(x: float, y: float) -> str:
    line_y = get_boundary_y_at_x(x)
    if y < line_y - DEADBAND:
        return "SIDE_A"
    if y > line_y + DEADBAND:
        return "SIDE_B"
    return "ON_LINE"


def determine_event(sides: list[str]) -> str:
    if not sides:
        return "UNRESOLVED"

    has_side_a = "SIDE_A" in sides
    has_side_b = "SIDE_B" in sides

    if has_side_a and has_side_b:
        first_a_idx = sides.index("SIDE_A")
        last_b_idx = len(sides) - 1 - sides[::-1].index("SIDE_B")
        if first_a_idx < last_b_idx:
            return "ENTRY"

        first_b_idx = sides.index("SIDE_B")
        last_a_idx = len(sides) - 1 - sides[::-1].index("SIDE_A")
        if first_b_idx < last_a_idx:
            return "EXIT"

    return "UNRESOLVED"


# ============================================================
# EVENT CREATION
# ============================================================

def create_event(
    track_id: int,
    evidence: TrackEvidence,
    direction: str,
) -> dict:
    identity = evidence.best_identity()
    timestamp = evidence.last_timestamp or datetime.now(timezone.utc)

    event = {
        "event_id": f"evt_{uuid.uuid4().hex[:16]}",
        "camera_id": CAMERA_ID,
        "track_id": int(track_id),
        "identity": identity,
        "direction": direction,
        "timestamp": timestamp.isoformat(),
        "evidence": {
            "peak_similarity": round(evidence.best_score(), 4),
            "mean_similarity": round(evidence.mean_score(), 4),
            "supporting_frames": evidence.supporting_frames(),
            "total_frames": len(evidence.identities),
            "consistency_pct": round(evidence.consistency(), 2),
            "margin_over_runner_up": 0.0,
            "runner_up_identity": None,
        },
    }

    return event


# ============================================================
# MAIN PIPELINE
# ============================================================

def main():
    print("=" * 75)
    print("LIVE CV -> FASTAPI -> MONGODB DEMO")
    print("=" * 75)

    # 1. InsightFace
    print("\nLoading InsightFace...")
    app = FaceAnalysis(
        name="buffalo_l",
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=0, det_size=(640, 640))
    print("InsightFace ready.")

    # 2. Gallery
    gallery = load_gallery(app)

    # 3. Dispatcher
    dispatcher = EventDispatcher()
    print("\nBackend target:", dispatcher.backend_url)

    # 4. ByteTrack (matching benchmark parameters)
    tracker = BYTETracker(
        track_thresh=0.40,
        match_thresh=0.80,
        track_buffer=20,
        frame_rate=30,
    )

    # 5. Video
    cap = cv2.VideoCapture(str(VIDEO_PATH))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {VIDEO_PATH}")

    source_fps = cap.get(cv2.CAP_PROP_FPS)
    if source_fps <= 0:
        raise RuntimeError("Invalid source FPS.")

    step_interval = source_fps / TARGET_FPS
    next_sample_frame = 0.0
    read_count = 0

    tracks: dict[int, TrackEvidence] = {}
    emitted_events = []

    print(f"\nProcessing: {VIDEO_PATH.name}")
    print(f"Source FPS: {source_fps:.2f}")
    print(f"Target sampling: {TARGET_FPS:.1f} FPS")

    # 6. Process video
    while True:
        success, frame = cap.read()
        if not success:
            break

        if read_count >= int(round(next_sample_frame)):
            timestamp_seconds = read_count / source_fps

            # Face detection
            faces = app.get(frame)
            detections = []
            for face in faces:
                x1, y1, x2, y2 = face.bbox
                detections.append({
                    "bbox": [float(x1), float(y1), float(x2), float(y2)],
                    "score": float(face.det_score),
                    "embedding": face.embedding,
                })

            # ByteTrack
            tracker_input = np.array(
                [[*d["bbox"], d["score"]] for d in detections],
                dtype=np.float32,
            ) if detections else np.empty((0, 5), dtype=np.float32)

            active_tracks = tracker.update(tracker_input)

            # Match tracks back to detections via box IoU
            if active_tracks and len(detections) > 0:
                tb = np.array([tr.tlbr for tr in active_tracks])
                fb = np.array([d["bbox"] for d in detections])
                ious = box_iou(tb, fb)

                for tr_idx, track in enumerate(active_tracks):
                    track_id = int(track.track_id)
                    best_face_idx = np.argmax(ious[tr_idx])

                    if ious[tr_idx, best_face_idx] < 0.3:
                        continue

                    best_detection = detections[best_face_idx]
                    tx1, ty1, tx2, ty2 = track.tlbr
                    track_center_x = (tx1 + tx2) / 2.0
                    track_center_y = (ty1 + ty2) / 2.0

                    # Recognition
                    identity, similarity, _ = recognize_face(
                        best_detection["embedding"],
                        gallery,
                    )

                    side = classify_side(track_center_x, track_center_y)
                    timestamp = datetime.fromtimestamp(
                        timestamp_seconds,
                        tz=timezone.utc,
                    )

                    if track_id not in tracks:
                        tracks[track_id] = TrackEvidence()

                    tracks[track_id].add(
                        identity=identity,
                        score=similarity,
                        detection=best_detection,
                        side=side,
                        timestamp=timestamp,
                    )

                    evidence = tracks[track_id]

                    # Check for ENTRY / EXIT
                    direction = determine_event(evidence.sides)

                    if (
                        direction in {"ENTRY", "EXIT"}
                        and not evidence.event_emitted
                        and evidence.supporting_frames() >= MIN_SUPPORTING_FRAMES
                        and evidence.best_identity() != "UNKNOWN"
                    ):
                        event = create_event(
                            track_id,
                            evidence,
                            direction,
                        )

                        print("\n" + "=" * 75)
                        print("VISION EVENT GENERATED")
                        print("=" * 75)
                        print(f"Track ID       : {track_id}")
                        print(f"Identity       : {event['identity']}")
                        print(f"Direction      : {event['direction']}")
                        print(f"Best similarity: {event['evidence']['peak_similarity']}")
                        print(f"Mean similarity: {event['evidence']['mean_similarity']}")
                        print(f"Support frames : {event['evidence']['supporting_frames']}")
                        print("Sending to FastAPI...")

                        try:
                            response = dispatcher.send_event(event)
                            print("Backend response:", response)
                            evidence.event_emitted = True
                            emitted_events.append(event)
                        except Exception as exc:
                            print("ERROR sending event:", exc)

            next_sample_frame += step_interval

        read_count += 1

    cap.release()

    # 7. Final summary
    print("\n" + "=" * 75)
    print("LIVE DEMO COMPLETE")
    print("=" * 75)
    print(f"Tracks observed : {len(tracks)}")
    print(f"Events emitted  : {len(emitted_events)}")

    for event in emitted_events:
        print(
            f"  {event['identity']} -> {event['direction']} "
            f"(Track {event['track_id']}, ID: {event['event_id']})"
        )


if __name__ == "__main__":
    main()
