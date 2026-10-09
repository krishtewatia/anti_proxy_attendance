import logging
from uuid import uuid4

from app.database.users import (
    DuplicateUserRecordError,
    create_user,
    get_user_by_email,
)
from app.schemas.auth import TokenResponse, UserCreate, UserResponse
from app.security.jwt import create_access_token
from app.core.account_status import ACCOUNT_APPROVED, ACCOUNT_PENDING, account_status
from app.security.passwords import hash_password, verify_password
from app.services.audit_service import record_audit_event

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication credentials are invalid."""


class DuplicateUserError(Exception):
    """Raised when a user with the requested email already exists."""


class PasswordChangeError(Exception):
    """The password change was refused (wrong current password, or the same password again)."""


class AccountPendingError(Exception):
    """The credentials are correct but an administrator has not approved the account yet."""


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
            # Public registration: nobody can log in until an administrator approves.
            status=ACCOUNT_PENDING,
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
            metadata={"status": ACCOUNT_PENDING},
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

    # Checked only after the password, so the message cannot be used to find
    # out whether an email is registered.
    if account_status(user) != ACCOUNT_APPROVED:
        raise AccountPendingError(
            "Your registration is awaiting admin approval. You can log in once it has been approved."
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

    return issue_token(user)


def issue_token(user: dict) -> TokenResponse:
    """A token for the user as they are now (current token version)."""
    return TokenResponse(
        access_token=create_access_token(
            user_id=user["user_id"],
            role=user["role"],
            token_version=int(user.get("token_version", 0) or 0),
        ),
        token_type="bearer",  # nosec: B106
        user=UserResponse(
            user_id=user["user_id"],
            email=user["email"],
            role=user["role"],
            is_active=user["is_active"],
        ),
        must_change_password=bool(user.get("must_change_password")),
    )


async def set_password(
    user_id: str, new_password: str, *, must_change_password: bool
) -> dict | None:
    """Store a new password and invalidate every token the user holds.

    The single place a password is replaced: the token version always moves
    with it, in the same document update. Returns the updated user document.
    """
    from pymongo import ReturnDocument

    from app.database.mongodb import get_database

    update: dict = {
        "$set": {"password_hash": hash_password(new_password)},
        "$inc": {"token_version": 1},
    }
    if must_change_password:
        update["$set"]["must_change_password"] = True
    else:
        update["$unset"] = {"must_change_password": ""}
    return await get_database()["users"].find_one_and_update(
        {"user_id": user_id}, update, return_document=ReturnDocument.AFTER
    )


async def change_own_password(
    user: dict, *, current_password: str, new_password: str
) -> TokenResponse:
    """Change the caller's password. Every earlier token stops working; a new one is returned."""
    if not verify_password(current_password, user["password_hash"]):
        raise PasswordChangeError("The current password is not correct")
    if verify_password(new_password, user["password_hash"]):
        raise PasswordChangeError("The new password must be different from the current one")

    updated = await set_password(user["user_id"], new_password, must_change_password=False)
    if updated is None:
        raise PasswordChangeError("The account no longer exists")

    await record_audit_event(
        actor_user_id=user["user_id"],
        actor_role=user["role"],
        action="PASSWORD_CHANGED",
        resource_type="USER",
        resource_id=user["user_id"],
        metadata={"forced": bool(user.get("must_change_password"))},
    )
    return issue_token(updated)
