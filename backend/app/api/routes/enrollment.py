from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies.auth import require_admin, require_teacher_or_admin
from app.database.biometric_profiles import get_all_embeddings, list_all_biometric_profiles
from app.schemas.biometric import (
    BiometricEnrollRequest,
    BiometricGalleryResponse,
    BiometricProfileResponse,
)
from app.services.enrollment_service import (
    BiometricProfileNotFoundError,
    DuplicateFaceBiometricError,
    enroll_or_update_biometric_profile,
    remove_biometric_profile,
)

router = APIRouter(
    prefix="/api/v1/enrollment",
    tags=["enrollment"],
)


@router.post(
    "",
    response_model=BiometricProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enroll student face biometric profile",
    description="Registers an ArcFace mean embedding for a student with duplicate cross-checking. Requires TEACHER or ADMIN role.",
)
async def enroll_student_face_endpoint(
    payload: BiometricEnrollRequest,
    current_user: Annotated[dict, Depends(require_teacher_or_admin)],
) -> BiometricProfileResponse:
    try:
        profile = await enroll_or_update_biometric_profile(
            identity=payload.identity,
            mean_embedding=payload.mean_embedding,
            sample_count=payload.sample_count,
            quality_score=payload.quality_score,
            actor_user_id=current_user["user_id"],
            actor_role=current_user.get("role", "TEACHER"),
            is_reenroll=False,
        )
        return profile
    except DuplicateFaceBiometricError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.put(
    "/{identity}",
    response_model=BiometricProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Re-enroll / replace student face biometric profile",
    description="Replaces an existing ArcFace mean embedding with a new template. Requires TEACHER or ADMIN role.",
)
async def reenroll_student_face_endpoint(
    identity: str,
    payload: BiometricEnrollRequest,
    current_user: Annotated[dict, Depends(require_teacher_or_admin)],
) -> BiometricProfileResponse:
    try:
        profile = await enroll_or_update_biometric_profile(
            identity=identity,
            mean_embedding=payload.mean_embedding,
            sample_count=payload.sample_count,
            quality_score=payload.quality_score,
            actor_user_id=current_user["user_id"],
            actor_role=current_user.get("role", "TEACHER"),
            is_reenroll=True,
        )
        return profile
    except DuplicateFaceBiometricError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.delete(
    "/{identity}",
    status_code=status.HTTP_200_OK,
    summary="Delete student face biometric profile",
    description="Deletes an enrolled biometric profile. Requires TEACHER or ADMIN role.",
)
async def delete_student_face_endpoint(
    identity: str,
    current_user: Annotated[dict, Depends(require_teacher_or_admin)],
) -> dict:
    try:
        await remove_biometric_profile(
            identity=identity,
            actor_user_id=current_user["user_id"],
            actor_role=current_user.get("role", "TEACHER"),
        )
        return {
            "status": "success",
            "message": f"Biometric profile for '{identity}' deleted successfully",
            "identity": identity,
        }
    except BiometricProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "",
    response_model=list[BiometricProfileResponse],
    summary="List enrolled biometric profiles (Metadata only)",
    description="Returns public metadata of enrolled students. SECURITY: Embedding vectors are never returned.",
)
async def list_enrolled_profiles_endpoint(
    current_user: Annotated[dict, Depends(require_teacher_or_admin)],
) -> list[BiometricProfileResponse]:
    docs = await list_all_biometric_profiles()
    return [
        BiometricProfileResponse(
            identity=doc["identity"],
            sample_count=doc["sample_count"],
            quality_score=doc["quality_score"],
            enrolled_by=doc["enrolled_by"],
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )
        for doc in docs
    ]


@router.get(
    "/gallery",
    response_model=BiometricGalleryResponse,
    summary="Synchronize biometric gallery",
    description="Restricted endpoint returning active mean embeddings for vision service synchronization. Requires ADMIN role.",
)
async def get_gallery_endpoint(
    current_user: Annotated[dict, Depends(require_admin)],
) -> BiometricGalleryResponse:
    embeddings = await get_all_embeddings()
    return BiometricGalleryResponse(
        count=len(embeddings),
        gallery=embeddings,
    )
