"""Student service layer for profile management, registration, and attendance analytics."""

import logging
from uuid import uuid4

from app.database.attendance import compute_student_attendance_metrics
from app.database.student_profiles import (
    DuplicateStudentProfileRecordError,
    create_student_profile as repo_create_student_profile,
    get_student_profile_by_identity as repo_get_student_profile_by_identity,
    get_student_profile_by_user_id as repo_get_student_profile_by_user_id,
    normalize_class_code,
    upsert_student_profile,
)
from app.database.users import create_user, get_user_by_email
from app.schemas.student import (
    StudentAttendanceDashboardResponse,
    StudentAttendanceHistoryItem,
    StudentProfile,
    StudentProfileResponse,
    StudentRegisterRequest,
    SubjectAttendanceItem,
)
from app.security.passwords import hash_password
from app.services.student_biometric_service import extract_and_register_student_photo

logger = logging.getLogger(__name__)


class StudentAuthorizationError(Exception):
    """Raised when an operation requires STUDENT role but another role was provided."""


class DuplicateStudentProfileError(Exception):
    """Raised when a student profile already exists for the user or the identity."""


async def create_student_profile(
    *,
    current_user: dict,
    identity: str,
) -> StudentProfile:
    """Create a student identity binding for an authenticated student user (legacy)."""
    if current_user.get("role") != "STUDENT":
        raise StudentAuthorizationError(
            "Only users with the STUDENT role can bind a student identity profile"
        )

    user_id = current_user.get("user_id")
    if not user_id:
        raise StudentAuthorizationError("Authenticated user does not have a valid user_id")

    existing_by_user = await repo_get_student_profile_by_user_id(user_id)
    if existing_by_user is not None:
        raise DuplicateStudentProfileError(
            f"User '{user_id}' already has a student profile bound to '{existing_by_user['identity']}'"
        )

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


async def register_student_account(
    req: StudentRegisterRequest,
    enrolled_by: str = "self",
) -> StudentProfileResponse:
    """Register a new student account, create academic profile, and process biometric photo."""
    # 1. Check existing user email
    existing_user = await get_user_by_email(req.email)
    if existing_user is not None:
        raise DuplicateStudentProfileError(f"A user with email '{req.email}' already exists")

    # 2. Check existing student ID
    existing_profile = await repo_get_student_profile_by_identity(req.student_id)
    if existing_profile is not None:
        raise DuplicateStudentProfileError(f"Student ID '{req.student_id}' is already registered")

    # 3. Compute class code
    class_code = normalize_class_code(req.branch, req.section)

    # 4. Extract and store the biometric embedding if a photo was provided. This
    #    runs before the account is created: if no face is found the request
    #    fails without leaving an account that blocks a retry with a better photo.
    has_biometric = False
    photo_url = None
    if req.photo_base64:
        ok, msg = await extract_and_register_student_photo(
            identity=req.student_id,
            photo_base64=req.photo_base64,
            enrolled_by=enrolled_by,
            student_name=req.name,
            student_id=req.student_id,
        )
        if not ok:
            logger.error("Biometric enrollment rejected for %s: %s", req.student_id, msg)
            raise ValueError(msg)
        has_biometric = True
        photo_url = f"/api/v1/students/{req.student_id}/photo"
        logger.info("Biometric registration for %s: %s", req.student_id, msg)

    # 5. Create User account
    user_id = f"user_{uuid4().hex}"
    pw_hash = hash_password(req.password)
    await create_user(
        user_id=user_id,
        email=req.email,
        password_hash=pw_hash,
        role="STUDENT",
    )

    # 6. Upsert student profile
    profile_doc = await upsert_student_profile(
        user_id=user_id,
        identity=req.student_id,
        name=req.name,
        email=req.email,
        student_id=req.student_id,
        roll_number=req.roll_number,
        branch=req.branch,
        section=req.section,
        class_code=class_code,
        photo_base64=req.photo_base64,
        photo_url=photo_url,
        has_biometric=has_biometric,
    )

    return StudentProfileResponse(
        user_id=user_id,
        identity=req.student_id,
        name=req.name,
        email=req.email,
        student_id=req.student_id,
        roll_number=req.roll_number,
        branch=req.branch,
        section=req.section,
        class_code=class_code,
        photo_url=photo_url,
        has_biometric=has_biometric,
        created_at=profile_doc.get("created_at"),
    )


async def get_student_profile_response(user_id: str) -> StudentProfileResponse | None:
    """Retrieve full student profile for a given user_id."""
    doc = await repo_get_student_profile_by_user_id(user_id)
    if not doc:
        return None

    stu_id = doc.get("student_id") or doc.get("identity") or user_id
    photo_url = doc.get("photo_url")
    if not photo_url:
        from app.core.uploads import student_photo_path

        try:
            photo_on_disk = student_photo_path(str(stu_id)).exists()
        except ValueError:
            photo_on_disk = False

        if photo_on_disk or doc.get("photo_base64") or doc.get("has_biometric"):
            photo_url = f"/api/v1/students/{stu_id}/photo"

    return StudentProfileResponse(
        user_id=doc["user_id"],
        identity=doc.get("identity") or stu_id,
        name=doc.get("name", "Student"),
        email=doc.get("email", ""),
        student_id=doc.get("student_id", ""),
        roll_number=doc.get("roll_number", ""),
        branch=doc.get("branch", ""),
        section=doc.get("section", ""),
        class_code=doc.get("class_code", ""),
        photo_url=photo_url,
        has_biometric=doc.get("has_biometric", False),
        created_at=doc.get("created_at"),
    )


async def get_student_dashboard(user_id: str) -> StudentAttendanceDashboardResponse:
    """Compute and compile complete student attendance dashboard analytics."""
    profile = await get_student_profile_response(user_id)
    if profile is None:
        raise ValueError(f"Student profile not found for user {user_id}")

    metrics = await compute_student_attendance_metrics(
        identity=profile.identity,
        class_code=profile.class_code,
    )

    subjects = [
        SubjectAttendanceItem(
            subject=s["subject"],
            present=s["present"],
            total=s["total"],
            percentage=s["percentage"],
        )
        for s in metrics["subjects"]
    ]

    history = [
        StudentAttendanceHistoryItem(
            session_id=h["session_id"],
            course_name=h["course_name"],
            subject=h["subject"],
            class_code=h["class_code"],
            date_str=h["date_str"],
            status=h["status"],
        )
        for h in metrics["history"]
    ]

    return StudentAttendanceDashboardResponse(
        profile=profile,
        overall_present=metrics["overall_present"],
        overall_total=metrics["overall_total"],
        overall_percentage=metrics["overall_percentage"],
        subjects=subjects,
        history=history,
    )


async def get_student_profile_by_user(user_id: str) -> StudentProfile | None:
    """Retrieve legacy student profile by user_id."""
    record = await repo_get_student_profile_by_user_id(user_id)
    if record is None:
        return None

    return StudentProfile(
        user_id=record["user_id"],
        identity=record.get("identity") or record.get("student_id", user_id),
    )


async def get_student_profile_by_cv_identity(identity: str) -> StudentProfile | None:
    """Retrieve legacy student profile by attendance/CV identity."""
    record = await repo_get_student_profile_by_identity(identity)
    if record is None:
        return None

    return StudentProfile(
        user_id=record["user_id"],
        identity=record.get("identity") or record.get("student_id", identity),
    )
