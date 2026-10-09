"""Teacher API routes for Dashboard, Profile, and Assigned Classes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies.rate_limiter import check_registration_rate_limit
from app.api.dependencies.auth import require_teacher
from app.schemas.teacher import (
    TeacherDashboardResponse,
    TeacherProfileResponse,
    TeacherRegisterRequest,
)
from app.services.teacher_service import (
    DuplicateTeacherError,
    get_teacher_dashboard,
    get_teacher_profile,
    register_teacher_account,
)

router = APIRouter(
    prefix="/api/v1/teachers",
    tags=["teachers"],
)


@router.post(
    "/register",
    response_model=TeacherProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new teacher account",
    dependencies=[Depends(check_registration_rate_limit)],
)
async def register_teacher_endpoint(
    payload: TeacherRegisterRequest,
) -> TeacherProfileResponse:
    try:
        return await register_teacher_account(payload)
    except DuplicateTeacherError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Registration failed: {exc}",
        ) from exc


@router.get(
    "/dashboard",
    response_model=TeacherDashboardResponse,
    summary="Teacher dashboard with profile, assigned classes, active session, and previous sessions",
)
async def get_teacher_dashboard_endpoint(
    current_user: Annotated[dict, Depends(require_teacher)],
) -> TeacherDashboardResponse:
    return await get_teacher_dashboard(current_user["user_id"])


@router.get(
    "/profile",
    response_model=TeacherProfileResponse,
    summary="Get current authenticated teacher's profile",
)
async def get_teacher_profile_endpoint(
    current_user: Annotated[dict, Depends(require_teacher)],
) -> TeacherProfileResponse:
    return await get_teacher_profile(current_user["user_id"])
