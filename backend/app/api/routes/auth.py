from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies.rate_limiter import check_registration_rate_limit

from typing import Annotated

from app.api.dependencies.auth import get_authenticated_user
from app.schemas.auth import (
    PasswordChangeRequest,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
)
from app.services.auth_service import (
    AccountPendingError,
    AuthenticationError,
    DuplicateUserError,
    PasswordChangeError,
    authenticate_user,
    change_own_password,
    register_user,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(check_registration_rate_limit)],
)
async def register(user: UserCreate) -> UserResponse:
    try:
        return await register_user(user)
    except DuplicateUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post(
    "/login",
    response_model=TokenResponse,
)
async def login(credentials: UserLogin) -> TokenResponse:
    try:
        return await authenticate_user(
            email=credentials.email,
            password=credentials.password,
        )
    except AccountPendingError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "account_pending", "message": str(exc)},
        ) from exc
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@router.post(
    "/change-password",
    response_model=TokenResponse,
    summary="Change your own password; every earlier token stops working",
)
async def change_password(
    payload: PasswordChangeRequest,
    # Not get_current_user: this is the one route a user who must change their
    # password is allowed to call.
    current_user: Annotated[dict, Depends(get_authenticated_user)],
) -> TokenResponse:
    try:
        return await change_own_password(
            current_user,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except PasswordChangeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
