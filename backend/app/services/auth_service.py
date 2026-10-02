import logging
from uuid import uuid4

from app.database.users import (
    DuplicateUserRecordError,
    create_user,
    get_user_by_email,
)
from app.schemas.auth import TokenResponse, UserCreate, UserResponse
from app.security.jwt import create_access_token
from app.security.passwords import hash_password, verify_password
from app.services.audit_service import record_audit_event

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication credentials are invalid."""


class DuplicateUserError(Exception):
    """Raised when a user with the requested email already exists."""


async def register_user(user: UserCreate) -> UserResponse:
    existing_user = await get_user_by_email(user.email)

    if existing_user is not None:
        raise DuplicateUserError("A user with this email already exists")

    user_id = f"user_{uuid4().hex}"

    password_hash = hash_password(user.password)

    try:
        created_user = await create_user(
            user_id=user_id,
            email=user.email,
            password_hash=password_hash,
            role=user.role,
        )
    except DuplicateUserRecordError as exc:
        raise DuplicateUserError("A user with this email already exists") from exc

    # Record audit event (resilient to audit logging failure)
    try:
        await record_audit_event(
            actor_user_id=created_user["user_id"],
            actor_role=created_user["role"],
            action="USER_REGISTERED",
            resource_type="USER",
            resource_id=created_user["user_id"],
            metadata={"email": created_user["email"]},
        )
    except Exception as exc:
        logger.error("Failed to record audit event for USER_REGISTERED: %s", exc)

    return UserResponse(
        user_id=created_user["user_id"],
        email=created_user["email"],
        role=created_user["role"],
        is_active=created_user["is_active"],
    )


async def authenticate_user(
    *,
    email: str,
    password: str,
) -> TokenResponse:
    user = await get_user_by_email(email)

    if user is None:
        raise AuthenticationError("Invalid email or password")

    if not user.get("is_active", False):
        raise AuthenticationError("Invalid email or password")

    if not verify_password(password, user["password_hash"]):
        raise AuthenticationError("Invalid email or password")

    access_token = create_access_token(
        user_id=user["user_id"],
        role=user["role"],
    )

    user_response = UserResponse(
        user_id=user["user_id"],
        email=user["email"],
        role=user["role"],
        is_active=user["is_active"],
    )

    # Record audit event (resilient to audit logging failure)
    try:
        await record_audit_event(
            actor_user_id=user["user_id"],
            actor_role=user["role"],
            action="USER_LOGIN",
            resource_type="USER",
            resource_id=user["user_id"],
            metadata={"email": user["email"]},
        )
    except Exception as exc:
        logger.error("Failed to record audit event for USER_LOGIN: %s", exc)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=user_response,
    )
