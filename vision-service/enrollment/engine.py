"""Multi-Image Enrollment Engine with Quality-Weighted Fusion and Duplicate Checking (Step 2E.2).

Performs:
1. Batch validation: 3 to 5 images.
2. Per-image quality gating with detailed rejection logging.
3. Quality-weighted mean embedding fusion:
   Weights proportional to (det_score * ln(1 + sharpness)).
4. Cross-student duplicate check against existing gallery.
5. Immediate discarding of raw image data from memory/disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Any, Optional

import numpy as np

from enrollment.quality_gates import QualityGateResult, check_image_quality

DUPLICATE_SIMILARITY_THRESHOLD = 0.70


@dataclass
class EnrollmentBatchResult:
    """Result of processing a multi-image enrollment batch for an identity."""

    identity: str
    passed: bool
    mean_embedding: Optional[np.ndarray] = None
    individual_embeddings: list[np.ndarray] = field(default_factory=list)
    sample_count: int = 0
    quality_score: float = 0.0
    per_image_results: list[QualityGateResult] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)


def check_gallery_duplicate(
    candidate_embedding: np.ndarray,
    gallery: dict[str, np.ndarray],
    identity: str,
    threshold: float = DUPLICATE_SIMILARITY_THRESHOLD,
) -> tuple[bool, Optional[str], float]:
    """Compare candidate embedding against existing gallery templates."""
    cand_norm = candidate_embedding / (np.linalg.norm(candidate_embedding) + 1e-10)

    for existing_id, existing_emb in gallery.items():
        if existing_id == identity:
            continue
        ex_norm = existing_emb / (np.linalg.norm(existing_emb) + 1e-10)
        sim = float(np.dot(cand_norm, ex_norm))
        if sim >= threshold:
            return True, existing_id, sim

    return False, None, 0.0


def process_multi_image_enrollment(
    images: list[np.ndarray | str | Path],
    identity: str,
    app: Any,
    existing_gallery: Optional[dict[str, np.ndarray]] = None,
    min_images: int = 3,
    max_images: int = 5,
    min_face_size: int = 80,
    min_det_score: float = 0.60,
    min_sharpness: float = 50.0,
    duplicate_threshold: float = DUPLICATE_SIMILARITY_THRESHOLD,
) -> EnrollmentBatchResult:
    """Process 3-5 images for an identity, applying quality gates, weighted fusion, and duplicate checks.

    Raw image buffers/files are not retained after feature extraction.
    """
    total_input = len(images)
    if total_input < min_images:
        return EnrollmentBatchResult(
            identity=identity,
            passed=False,
            rejection_reasons=[
                f"INSUFFICIENT_IMAGES: Provided {total_input} images, minimum required is {min_images}"
            ],
        )

    if total_input > max_images:
        return EnrollmentBatchResult(
            identity=identity,
            passed=False,
            rejection_reasons=[
                f"TOO_MANY_IMAGES: Provided {total_input} images, maximum allowed is {max_images}"
            ],
        )

    per_image_results: list[QualityGateResult] = []
    valid_embeddings: list[np.ndarray] = []
    quality_weights: list[float] = []

    for idx, img in enumerate(images):
        res = check_image_quality(
            image=img,
            app=app,
            min_face_size=min_face_size,
            min_det_score=min_det_score,
            min_sharpness=min_sharpness,
        )
        per_image_results.append(res)

        if res.passed and res.embedding is not None:
            valid_embeddings.append(res.embedding)
            # Quality weight: detection score * log(1 + sharpness)
            weight = res.det_score * math.log(1.0 + max(res.sharpness, 0.0))
            quality_weights.append(max(weight, 1e-4))

    # Free references to input images immediately
    del images

    valid_count = len(valid_embeddings)
    if valid_count < min_images:
        failed_reasons = []
        for idx, res in enumerate(per_image_results):
            if not res.passed:
                failed_reasons.append(f"Image #{idx + 1}: {'; '.join(res.rejection_reasons)}")
        return EnrollmentBatchResult(
            identity=identity,
            passed=False,
            per_image_results=per_image_results,
            rejection_reasons=[
                f"INSUFFICIENT_VALID_IMAGES: Only {valid_count} images passed quality gates ({min_images} required). "
                f"Failures: {' | '.join(failed_reasons)}"
            ],
        )

    # Compute Quality-Weighted Mean Embedding
    total_weight = sum(quality_weights)
    norm_weights = [w / total_weight for w in quality_weights]

    weighted_emb = np.zeros_like(valid_embeddings[0], dtype=np.float32)
    for w, emb in zip(norm_weights, valid_embeddings):
        weighted_emb += (w * emb).astype(np.float32)

    norm = np.linalg.norm(weighted_emb)
    mean_embedding = (weighted_emb / (norm + 1e-10)).astype(np.float32)

    avg_quality = float(np.mean(quality_weights))

    # Cross-student duplicate check against existing gallery
    if existing_gallery:
        is_dup, conflict_id, sim = check_gallery_duplicate(
            candidate_embedding=mean_embedding,
            gallery=existing_gallery,
            identity=identity,
            threshold=duplicate_threshold,
        )
        if is_dup:
            return EnrollmentBatchResult(
                identity=identity,
                passed=False,
                sample_count=valid_count,
                quality_score=avg_quality,
                per_image_results=per_image_results,
                rejection_reasons=[
                    f"DUPLICATE_IDENTITY_DETECTED: Candidate face matches existing enrolled identity "
                    f"'{conflict_id}' (similarity: {sim:.4f} >= {duplicate_threshold:.4f})"
                ],
            )

    return EnrollmentBatchResult(
        identity=identity,
        passed=True,
        mean_embedding=mean_embedding,
        individual_embeddings=valid_embeddings,
        sample_count=valid_count,
        quality_score=avg_quality,
        per_image_results=per_image_results,
        rejection_reasons=[],
    )
