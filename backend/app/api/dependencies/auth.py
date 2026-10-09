from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

from app.core.account_status import is_approved
from app.database.users import get_user_by_id
from app.security.jwt import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


async def get_authenticated_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> dict:
    """The user a valid token belongs to, even if they still have to change their password.

    Only the password-change route depends on this directly; everything else
    uses ``get_current_user``.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await get_user_by_id(user_id)

    if user is None or not user.get("is_active", False) or not is_approved(user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is unavailable",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # A password change or reset raises the user's token version; a token
    # issued before that is no longer accepted.
    if int(payload.get("tv", 0) or 0) != int(user.get("token_version", 0) or 0):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


PASSWORD_CHANGE_REQUIRED_DETAIL = {
    "code": "password_change_required",
    "message": "You must change your password before you can continue.",
}


async def get_current_user(
    user: Annotated[dict, Depends(get_authenticated_user)],
) -> dict:
    # An account created by an administrator, or whose password an
    # administrator reset, can do nothing until its owner has chosen a password.
    if user.get("must_change_password"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PASSWORD_CHANGE_REQUIRED_DETAIL,
        )
    return user


def require_role(required_role: str):
    async def role_dependency(
        current_user: Annotated[dict, Depends(get_current_user)],
    ) -> dict:
        if current_user.get("role") != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )

        return current_user

    return role_dependency


def require_roles(allowed_roles: set[str]):
    async def roles_dependency(
        current_user: Annotated[dict, Depends(get_current_user)],
    ) -> dict:
        if current_user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return roles_dependency


require_teacher = require_role("TEACHER")
require_student = require_role("STUDENT")
require_admin = require_role("ADMIN")
require_teacher_or_admin = require_roles({"TEACHER", "ADMIN"})


async def get_owned_session(
    session_id: str,
    current_user: dict,
) -> dict:
    from app.database.sessions import get_session

    session = await get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    if current_user.get("role") == "ADMIN":
        return session

    if session.get("created_by") != current_user.get("user_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You do not own this session",
        )

    return session
