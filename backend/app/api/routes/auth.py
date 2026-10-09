from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies.rate_limiter import check_registration_rate_limit

from app.schemas.auth import TokenResponse, UserCreate, UserLogin, UserResponse
from app.services.auth_service import (
    AccountPendingError,
    AuthenticationError,
    DuplicateUserError,
    authenticate_user,
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
