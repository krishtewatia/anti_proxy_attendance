from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies.auth import require_student
from app.schemas.student import StudentProfile, StudentProfileBind
from app.services.student_service import (
    DuplicateStudentProfileError,
    StudentAuthorizationError,
    create_student_profile,
    get_student_profile_by_user,
)

router = APIRouter(
    prefix="/api/v1/students",
    tags=["students"],
)


@router.post(
    "/profile",
    response_model=StudentProfile,
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/bind",
    response_model=StudentProfile,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def bind_student_identity_endpoint(
    payload: StudentProfileBind,
    current_user: Annotated[dict, Depends(require_student)],
) -> StudentProfile:
    """Bind authenticated student account to a CV identity."""
    try:
        profile = await create_student_profile(
            current_user=current_user,
            identity=payload.identity,
        )
        return profile
    except DuplicateStudentProfileError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except StudentAuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.get(
    "/profile",
    response_model=StudentProfile,
)
@router.get(
    "/me",
    response_model=StudentProfile,
    include_in_schema=False,
)
async def get_my_student_profile_endpoint(
    current_user: Annotated[dict, Depends(require_student)],
) -> StudentProfile:
    """Retrieve the authenticated student's profile."""
    profile = await get_student_profile_by_user(current_user["user_id"])

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student profile not found",
        )

    return profile
