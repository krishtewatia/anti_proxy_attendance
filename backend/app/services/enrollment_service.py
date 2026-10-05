import math
from typing import Optional

from app.database.biometric_profiles import (
    delete_biometric_profile,
    get_all_embeddings,
    get_biometric_profile,
    upsert_biometric_profile,
)
from app.schemas.biometric import BiometricProfileResponse
from app.services.audit_service import record_audit_event

DUPLICATE_SIMILARITY_THRESHOLD = 0.70


class DuplicateFaceBiometricError(Exception):
    """Raised when an enrolled face matches another student above the similarity threshold."""

    def __init__(self, conflicting_identity: str, similarity: float, threshold: float):
        super().__init__(
            f"DUPLICATE_IDENTITY_DETECTED: Biometric template matches existing identity "
            f"'{conflicting_identity}' (similarity: {similarity:.4f} >= {threshold:.4f})"
        )
        self.conflicting_identity = conflicting_identity
        self.similarity = similarity
        self.threshold = threshold


class BiometricProfileNotFoundError(Exception):
    """Raised when an identity does not have an enrolled biometric profile."""


def compute_cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two 1D vectors."""
    if len(vec_a) != len(vec_b) or not vec_a:
        return 0.0

    dot = 0.0
    norm_a_sq = 0.0
    norm_b_sq = 0.0
    for a, b in zip(vec_a, vec_b):
        dot += a * b
        norm_a_sq += a * a
        norm_b_sq += b * b

    if norm_a_sq <= 0.0 or norm_b_sq <= 0.0:
        return 0.0

    return dot / (math.sqrt(norm_a_sq) * math.sqrt(norm_b_sq))


async def check_cross_student_duplicate(
    identity: str,
    candidate_embedding: list[float],
    threshold: float = DUPLICATE_SIMILARITY_THRESHOLD,
) -> tuple[bool, Optional[str], float]:
    """Check candidate embedding against all other enrolled identities.

    Returns (is_duplicate, conflicting_identity, similarity).
    """
    all_embeddings = await get_all_embeddings()
    for other_id, other_emb in all_embeddings.items():
        if other_id == identity:
            continue
        sim = compute_cosine_similarity(candidate_embedding, other_emb)
        if sim >= threshold:
            return True, other_id, sim

    return False, None, 0.0


async def enroll_or_update_biometric_profile(
    *,
    identity: str,
    mean_embedding: list[float],
    sample_count: int,
    quality_score: float,
    actor_user_id: str,
    actor_role: str,
    is_reenroll: bool = False,
    threshold: float = DUPLICATE_SIMILARITY_THRESHOLD,
) -> BiometricProfileResponse:
    """Enroll or re-enroll a student face profile with duplicate detection and audit logging."""
    # 1. Cross-student duplicate check
    is_dup, conflict_id, sim = await check_cross_student_duplicate(
        identity=identity,
        candidate_embedding=mean_embedding,
        threshold=threshold,
    )
    if is_dup:
        raise DuplicateFaceBiometricError(
            conflicting_identity=conflict_id,
            similarity=sim,
            threshold=threshold,
        )

    # 2. Upsert profile document
    doc, is_new = await upsert_biometric_profile(
        identity=identity,
        mean_embedding=mean_embedding,
        sample_count=sample_count,
        quality_score=quality_score,
        enrolled_by=actor_user_id,
    )

    action = "FACE_REENROLLED" if (is_reenroll or not is_new) else "FACE_ENROLLED"

    # 3. Record audit trail (security: never log embedding in metadata)
    await record_audit_event(
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=action,
        resource_type="BIOMETRIC_PROFILE",
        resource_id=identity,
        metadata={
            "identity": identity,
            "sample_count": sample_count,
            "quality_score": round(quality_score, 4),
            "is_reenroll": (is_reenroll or not is_new),
        },
    )

    return BiometricProfileResponse(
        identity=doc["identity"],
        sample_count=doc["sample_count"],
        quality_score=doc["quality_score"],
        enrolled_by=doc["enrolled_by"],
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


async def remove_biometric_profile(
    *,
    identity: str,
    actor_user_id: str,
    actor_role: str,
) -> bool:
    """Delete a student biometric profile and record audit event."""
    existing = await get_biometric_profile(identity)
    if not existing:
        raise BiometricProfileNotFoundError(f"Biometric profile for '{identity}' not found")

    deleted = await delete_biometric_profile(identity)

    # Record audit event
    await record_audit_event(
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action="FACE_DELETED",
        resource_type="BIOMETRIC_PROFILE",
        resource_id=identity,
        metadata={"identity": identity},
    )

    return deleted
