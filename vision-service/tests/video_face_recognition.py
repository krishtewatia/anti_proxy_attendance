from pathlib import Path
import time

import cv2
import numpy as np
from insightface.app import FaceAnalysis


# ============================================================
# CONFIGURATION
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent

# Video source directory
VIDEO_DIR = PROJECT_ROOT / "vision-service" / "tests" / "video_test"
if not VIDEO_DIR.exists():
    VIDEO_DIR = SCRIPT_DIR / "video_test"

# Enrolled benchmark gallery directory (matches still-image benchmark)
ENROLLMENT_DIR = PROJECT_ROOT / "vision-service" / "tests" / "recognition_benchmark"
if not ENROLLMENT_DIR.exists():
    ENROLLMENT_DIR = SCRIPT_DIR / "face_images"

TARGET_FPS = 5.0

# Do NOT treat this as the final production threshold.
# This is only for the first moving-video experiment.
RECOGNITION_THRESHOLD = 0.60


# ============================================================
# HELPERS
# ============================================================

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Calculate cosine similarity between two embeddings."""
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)

    denominator = np.linalg.norm(a) * np.linalg.norm(b)

    if denominator == 0:
        return 0.0

    return float(np.dot(a, b) / denominator)


def load_enrollment_gallery(app):
    """
    Load enrolled face images and create one averaged embedding
    per person.
    """

    gallery = {}

    if not ENROLLMENT_DIR.exists():
        raise FileNotFoundError(
            f"Enrollment directory not found: {ENROLLMENT_DIR}"
        )

    person_dirs = sorted(
        path for path in ENROLLMENT_DIR.iterdir()
        if path.is_dir()
    )

    if not person_dirs:
        raise RuntimeError(
            f"No person folders found inside {ENROLLMENT_DIR}"
        )

    print("\n" + "=" * 70)
    print("LOADING ENROLLMENT GALLERY")
    print("=" * 70)

    for person_dir in person_dirs:
        embeddings = []

        image_files = sorted(
            [
                path
                for path in person_dir.iterdir()
                if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
            ]
        )

        for image_path in image_files:
            image = cv2.imread(str(image_path))

            if image is None:
                print(f"WARNING: Could not read {image_path}")
                continue

            faces = app.get(image)

            if not faces:
                print(f"WARNING: No face detected in {image_path}")
                continue

            # Use the largest detected face.
            face = max(
                faces,
                key=lambda detected_face: (
                    detected_face.bbox[2] - detected_face.bbox[0]
                )
                * (
                    detected_face.bbox[3] - detected_face.bbox[1]
                ),
            )

            embedding = face.embedding.astype(np.float32)

            # Normalize before storing.
            embedding /= np.linalg.norm(embedding)

            embeddings.append(embedding)

        if embeddings:
            # Average all enrollment embeddings for this person.
            mean_embedding = np.mean(
                embeddings,
                axis=0,
            )

            mean_embedding /= np.linalg.norm(mean_embedding)

            gallery[person_dir.name] = mean_embedding

            print(
                f"{person_dir.name}: "
                f"{len(embeddings)} enrollment image(s)"
            )

    if not gallery:
        raise RuntimeError("No valid enrollment embeddings were created.")

    print(f"\nGallery identities: {len(gallery)}")

    return gallery


def recognize_face(embedding, gallery):
    """
    Compare a probe embedding against every enrolled identity.
    """

    embedding = embedding.astype(np.float32)
    embedding /= np.linalg.norm(embedding)

    scores = {}

    for person_name, enrolled_embedding in gallery.items():
        score = cosine_similarity(
            embedding,
            enrolled_embedding,
        )

        scores[person_name] = score

    best_person = max(
        scores,
        key=scores.get,
    )

    best_score = scores[best_person]

    if best_score >= RECOGNITION_THRESHOLD:
        return best_person, best_score

    return "UNKNOWN", best_score


# ============================================================
# VIDEO PROCESSING
# ============================================================

def process_video(video_path, app, gallery):
    print("\n" + "=" * 70)
    print(f"PROCESSING: {video_path.name}")
    print("=" * 70)

    cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        raise RuntimeError(
            f"Could not open video: {video_path}"
        )

    source_fps = cap.get(cv2.CAP_PROP_FPS)

    if source_fps <= 0:
        raise RuntimeError(
            f"Invalid source FPS for {video_path}"
        )

    frame_interval = 1.0 / TARGET_FPS
    next_sample_time = 0.0

    frame_number = 0
    sampled_frames = 0
    frames_with_faces = 0
    recognized_frames = 0
    unknown_frames = 0

    recognition_results = []

    start_time = time.perf_counter()

    while True:
        success, frame = cap.read()

        if not success:
            break

        current_time = frame_number / source_fps

        if current_time + 1e-9 < next_sample_time:
            frame_number += 1
            continue

        sampled_frames += 1

        faces = app.get(frame)

        if faces:
            frames_with_faces += 1

        frame_results = []

        for face in faces:
            person_name, similarity = recognize_face(
                face.embedding,
                gallery,
            )

            if person_name == "UNKNOWN":
                unknown_frames += 1
            else:
                recognized_frames += 1

            frame_results.append(
                {
                    "identity": person_name,
                    "similarity": similarity,
                    "bbox": face.bbox.tolist(),
                }
            )

        recognition_results.append(
            {
                "frame": frame_number,
                "timestamp": current_time,
                "faces": frame_results,
            }
        )

        # Print only sampled-frame recognition results.
        print(
            f"Frame {frame_number:4d} | "
            f"Time {current_time:6.2f}s | "
            f"Faces: {len(faces)}",
            end="",
            flush=True,
        )

        if frame_results:
            for result in frame_results:
                print(
                    f" | {result['identity']}"
                    f" ({result['similarity']:.3f})",
                    end="",
                    flush=True,
                )

        print(flush=True)

        next_sample_time += frame_interval
        frame_number += 1

    cap.release()

    elapsed = time.perf_counter() - start_time

    effective_fps = (
        sampled_frames / elapsed
        if elapsed > 0
        else 0
    )

    print("\n" + "-" * 70)
    print("VIDEO SUMMARY")
    print("-" * 70)

    print(f"Total frames read       : {frame_number}")
    print(f"Frames sampled          : {sampled_frames}")
    print(f"Frames containing faces : {frames_with_faces}")
    print(f"Recognized face results : {recognized_frames}")
    print(f"Unknown face results    : {unknown_frames}")
    print(f"Processing time         : {elapsed:.2f}s")
    print(f"Processing FPS          : {effective_fps:.2f}")

    return recognition_results


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("STEP 4.10.2: VIDEO FACE RECOGNITION")
    print("=" * 70)

    # --------------------------------------------------------
    # Initialize InsightFace
    # --------------------------------------------------------

    print("\nLoading InsightFace...")

    app = FaceAnalysis(
        name="buffalo_l",
        providers=["CPUExecutionProvider"],
    )

    app.prepare(
        ctx_id=0,
        det_size=(640, 640),
    )

    print("InsightFace loaded successfully.")

    # --------------------------------------------------------
    # Load enrolled identities
    # --------------------------------------------------------

    gallery = load_enrollment_gallery(app)

    # --------------------------------------------------------
    # Find test videos
    # --------------------------------------------------------

    videos = sorted(
        VIDEO_DIR.glob("*.mp4")
    )

    if not videos:
        raise RuntimeError(
            f"No .mp4 videos found in {VIDEO_DIR}"
        )

    print("\n" + "=" * 70)
    print(f"FOUND {len(videos)} TEST VIDEO(S)")
    print("=" * 70)

    # --------------------------------------------------------
    # Process every video
    # --------------------------------------------------------

    for video_path in videos:
        process_video(
            video_path,
            app,
            gallery,
        )

    print("\n" + "=" * 70)
    print("STEP 4.10.2 COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
