from app.database.student_profiles import (
    DuplicateStudentProfileRecordError,
    create_student_profile as repo_create_student_profile,
    get_student_profile_by_identity as repo_get_student_profile_by_identity,
    get_student_profile_by_user_id as repo_get_student_profile_by_user_id,
)
from app.schemas.student import StudentProfile


class StudentAuthorizationError(Exception):
    """Raised when an operation requires STUDENT role but another role was provided."""


class DuplicateStudentProfileError(Exception):
    """Raised when a student profile already exists for the user or the identity."""


async def create_student_profile(
    *,
    current_user: dict,
    identity: str,
) -> StudentProfile:
    """Create a student identity binding for an authenticated student user."""
    if current_user.get("role") != "STUDENT":
        raise StudentAuthorizationError(
            "Only users with the STUDENT role can bind a student identity profile"
        )

    user_id = current_user.get("user_id")
    if not user_id:
        raise StudentAuthorizationError("Authenticated user does not have a valid user_id")

    # Service pre-check: User uniqueness
    existing_by_user = await repo_get_student_profile_by_user_id(user_id)
    if existing_by_user is not None:
        raise DuplicateStudentProfileError(
            f"User '{user_id}' already has a student profile bound to '{existing_by_user['identity']}'"
        )

    # Service pre-check: Identity uniqueness
    existing_by_identity = await repo_get_student_profile_by_identity(identity)
    if existing_by_identity is not None:
        raise DuplicateStudentProfileError(
            f"Identity '{identity}' is already bound to another student account"
        )

    try:
        record = await repo_create_student_profile(
            user_id=user_id,
            identity=identity,
        )
    except DuplicateStudentProfileRecordError as exc:
        raise DuplicateStudentProfileError(
            "A student profile for this user_id or identity already exists"
        ) from exc

    return StudentProfile(
        user_id=record["user_id"],
        identity=record["identity"],
    )


async def get_student_profile_by_user(user_id: str) -> StudentProfile | None:
    """Retrieve student profile by user_id."""
    record = await repo_get_student_profile_by_user_id(user_id)
    if record is None:
        return None

    return StudentProfile(
        user_id=record["user_id"],
        identity=record["identity"],
    )


async def get_student_profile_by_cv_identity(identity: str) -> StudentProfile | None:
    """Retrieve student profile by attendance/CV identity."""
    record = await repo_get_student_profile_by_identity(identity)
    if record is None:
        return None

    return StudentProfile(
        user_id=record["user_id"],
        identity=record["identity"],
    )
