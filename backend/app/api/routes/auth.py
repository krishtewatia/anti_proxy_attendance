from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.dependencies.rate_limiter import (
    check_registration_identity,
    check_registration_rate_limit,
)
from app.core.client_ip import client_ip
from app.database.mongodb import get_database
from app.services.login_throttle import login_throttle
from app.services.registration_rules import (
    CONSENT_NOTICE,
    RegistrationRuleError,
    college_email_domain,
)

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
    await check_registration_identity(user.email)
    try:
        return await register_user(user)
    except DuplicateUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except RegistrationRuleError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/registration-rules",
    summary="What the sign-up form needs: the college email domain and the photo notice",
)
async def registration_rules() -> dict:
    return {
        # None until the academic structure exists: any address is accepted.
        "college_email_domain": await college_email_domain(get_database()),
        "consent_notice": CONSENT_NOTICE,
    }


@router.post(
    "/login",
    response_model=TokenResponse,
)
async def login(credentials: UserLogin, request: Request) -> TokenResponse:
    # Too many failed sign-ins from this address or for this email: refuse
    # before looking at the password. The answer is the same whether or not
    # the account exists.
    address = client_ip(request)
    wait_seconds = await login_throttle.retry_after(address, credentials.email)
    if wait_seconds:
        minutes = max(1, -(-wait_seconds // 60))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Too many failed sign-in attempts. "
                f"Try again in {minutes} minute{'' if minutes == 1 else 's'}."
            ),
            headers={"Retry-After": str(wait_seconds)},
        )

    try:
        token = await authenticate_user(
            email=credentials.email,
            password=credentials.password,
        )
    except AccountPendingError as exc:
        # The password was right, so this is not a failed guess.
        await login_throttle.record_success(credentials.email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "account_pending", "message": str(exc)},
        ) from exc
    except AuthenticationError as exc:
        await login_throttle.record_failure(address, credentials.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    await login_throttle.record_success(credentials.email)
    return token


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
