from fastapi import APIRouter, HTTPException, status

from app.schemas.auth import TokenResponse, UserCreate, UserLogin, UserResponse
from app.services.auth_service import (
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
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
