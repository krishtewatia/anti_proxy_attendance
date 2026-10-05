"""Per-Image Biometric Quality Gates for Face Enrollment (Step 2E.2).

Enforces:
1. Exactly one face detected (rejects 0 faces or multiple faces).
2. Minimum face size (bounding box width and height >= min_face_size).
3. Minimum detection confidence score (det_score >= min_det_score).
4. Sharpness / blur filter (Laplacian variance of face crop >= min_sharpness).

Provides clear rejection reasons for rejected images.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np


@dataclass
class QualityGateResult:
    """Result of passing an image through face quality gates."""

    passed: bool
    rejection_reasons: list[str] = field(default_factory=list)
    face_count: int = 0
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    face_size: tuple[int, int] = (0, 0)
    det_score: float = 0.0
    sharpness: float = 0.0
    embedding: Optional[np.ndarray] = None


def compute_laplacian_sharpness(img_crop: np.ndarray) -> float:
    """Calculate variance of Laplacian as a metric of image sharpness."""
    if img_crop.size == 0:
        return 0.0
    if len(img_crop.shape) == 3 and img_crop.shape[2] == 3:
        gray = cv2.cvtColor(img_crop, cv2.COLOR_BGR2GRAY)
    else:
        gray = img_crop
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def check_image_quality(
    image: np.ndarray | str | Path,
    app: Any,
    min_face_size: int = 80,
    min_det_score: float = 0.60,
    min_sharpness: float = 50.0,
) -> QualityGateResult:
    """Evaluate an enrollment image against all biometric quality gates.

    Args:
        image: BGR numpy image array or file path.
        app: FaceAnalysis instance.
        min_face_size: Minimum bounding box width and height in pixels.
        min_det_score: Minimum detection confidence score.
        min_sharpness: Minimum Laplacian variance for sharpness.

    Returns:
        QualityGateResult with pass status, metrics, and any rejection reasons.
    """
    if isinstance(image, (str, Path)):
        img_path = Path(image)
        if not img_path.exists():
            return QualityGateResult(
                passed=False,
                rejection_reasons=[f"FILE_NOT_FOUND: Image file does not exist: {img_path}"],
            )
        img = cv2.imread(str(img_path))
        if img is None:
            return QualityGateResult(
                passed=False,
                rejection_reasons=[f"CORRUPT_IMAGE: Failed to decode image file: {img_path}"],
            )
    else:
        img = image

    if not isinstance(img, np.ndarray) or img.size == 0 or len(img.shape) != 3:
        return QualityGateResult(
            passed=False,
            rejection_reasons=["INVALID_IMAGE_ARRAY: Input image must be a non-empty 3-channel numpy array"],
        )

    h_img, w_img = img.shape[:2]

    # 1. Face detection
    faces = app.get(img)
    face_count = len(faces)

    if face_count == 0:
        return QualityGateResult(
            passed=False,
            face_count=0,
            rejection_reasons=["NO_FACE_DETECTED: No human face detected in the image"],
        )

    if face_count > 1:
        return QualityGateResult(
            passed=False,
            face_count=face_count,
            rejection_reasons=[
                f"MULTIPLE_FACES_DETECTED: Found {face_count} faces in image, exactly one required"
            ],
        )

    face = faces[0]
    bbox = tuple(float(v) for v in face.bbox)
    x1, y1, x2, y2 = bbox
    face_w = int(round(x2 - x1))
    face_h = int(round(y2 - y1))
    det_score = float(face.det_score)

    rejections: list[str] = []

    # 2. Minimum Face Size Gate
    if face_w < min_face_size or face_h < min_face_size:
        rejections.append(
            f"FACE_TOO_SMALL: Detected face {face_w}x{face_h}px is smaller than minimum required {min_face_size}x{min_face_size}px"
        )

    # 3. Detection Confidence Score Gate
    if det_score < min_det_score:
        rejections.append(
            f"DETECTION_SCORE_TOO_LOW: Detection score {det_score:.2f} is below required threshold {min_det_score:.2f}"
        )

    # 4. Blur / Sharpness Gate
    crop_x1 = max(0, int(round(x1)))
    crop_y1 = max(0, int(round(y1)))
    crop_x2 = min(w_img, int(round(x2)))
    crop_y2 = min(h_img, int(round(y2)))

    face_crop = img[crop_y1:crop_y2, crop_x1:crop_x2]
    sharpness = compute_laplacian_sharpness(face_crop)

    if sharpness < min_sharpness:
        rejections.append(
            f"IMAGE_TOO_BLURRY: Face crop sharpness (Laplacian variance: {sharpness:.1f}) is below minimum threshold {min_sharpness:.1f}"
        )

    if rejections:
        return QualityGateResult(
            passed=False,
            rejection_reasons=rejections,
            face_count=1,
            bbox=bbox,
            face_size=(face_w, face_h),
            det_score=det_score,
            sharpness=sharpness,
        )

    # All gates passed: return ArcFace embedding
    embedding = getattr(face, "embedding", None)
    if embedding is not None and isinstance(embedding, np.ndarray):
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm

    return QualityGateResult(
        passed=True,
        rejection_reasons=[],
        face_count=1,
        bbox=bbox,
        face_size=(face_w, face_h),
        det_score=det_score,
        sharpness=sharpness,
        embedding=embedding,
    )
