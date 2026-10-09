"""Teacher service layer for profiles, assigned classes, and dashboard telemetry."""

import logging
from uuid import uuid4

from app.database.attendance import get_attendance_by_session
from app.database.session_roster import get_session_roster
from app.database.sessions import (
    get_active_session_by_teacher,
    get_sessions_by_owner,
)
from app.core.account_status import ACCOUNT_APPROVED, ACCOUNT_PENDING
from app.database.mongodb import get_database
from app.database.teacher_profiles import (
    get_teacher_profile_by_teacher_id,
    get_teacher_profile_by_user_id,
    upsert_teacher_profile,
)
from app.database.users import create_user, get_user_by_email
from app.schemas.teacher import (
    TeacherDashboardResponse,
    TeacherProfileResponse,
    TeacherRegisterRequest,
    TeacherSessionSummaryItem,
)
from app.security.passwords import hash_password

logger = logging.getLogger(__name__)


class DuplicateTeacherError(Exception):
    """Raised when a teacher email or ID already exists."""


async def register_teacher_account(
    req: TeacherRegisterRequest, approved: bool = False
) -> TeacherProfileResponse:
    """Create a teacher account.

    A public registration (``approved=False``) is PENDING and gets no classes:
    whatever the form asked for is kept only as a request for the
    administrator to see. Classes are assigned by an administrator, at
    approval or when the administrator creates the account (``approved=True``).
    """
    existing_user = await get_user_by_email(req.email)
    if existing_user is not None:
        raise DuplicateTeacherError(f"A user with email '{req.email}' already exists")

    existing_profile = await get_teacher_profile_by_teacher_id(req.teacher_id)
    if existing_profile is not None:
        raise DuplicateTeacherError(f"Teacher ID '{req.teacher_id}' is already registered")

    user_id = f"user_{uuid4().hex}"
    pw_hash = hash_password(req.password)
    await create_user(
        user_id=user_id,
        email=req.email,
        password_hash=pw_hash,
        role="TEACHER",
        status=ACCOUNT_APPROVED if approved else ACCOUNT_PENDING,
    )

    assigned_classes = req.assigned_classes if approved else []
    assigned_subjects = req.assigned_subjects if approved else []
    _ = await upsert_teacher_profile(
        user_id=user_id,
        teacher_id=req.teacher_id,
        name=req.name,
        email=req.email,
        department=req.department,
        assigned_classes=assigned_classes,
        assigned_subjects=assigned_subjects,
    )
    if not approved:
        await get_database()["teacher_profiles"].update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "requested_classes": req.assigned_classes,
                    "requested_subjects": req.assigned_subjects,
                }
            },
        )

    return TeacherProfileResponse(
        user_id=user_id,
        teacher_id=req.teacher_id,
        name=req.name,
        email=req.email,
        department=req.department,
        assigned_classes=assigned_classes,
        assigned_subjects=assigned_subjects,
    )


async def get_teacher_profile(user_id: str) -> TeacherProfileResponse:
    """Retrieve teacher profile by user_id; empty values if none has been set up yet."""
    doc = await get_teacher_profile_by_user_id(user_id)
    if not doc:
        # No profile yet (an account approved without one, or created before
        # profiles existed): say so with empty values rather than invented ones.
        user = await get_database()["users"].find_one({"user_id": user_id}, {"email": 1}) or {}
        return TeacherProfileResponse(
            user_id=user_id,
            teacher_id="",
            name="",
            email=user.get("email", ""),
            department="",
            assigned_classes=[],
            assigned_subjects=[],
        )

    return TeacherProfileResponse(
        user_id=doc["user_id"],
        teacher_id=doc.get("teacher_id", ""),
        name=doc.get("name", ""),
        email=doc.get("email", ""),
        department=doc.get("department", ""),
        assigned_classes=doc.get("assigned_classes", []),
        assigned_subjects=doc.get("assigned_subjects", []),
    )


async def _summarize_session(session: dict) -> TeacherSessionSummaryItem:
    """Compute summary stats for a single attendance session."""
    s_id = session["session_id"]
    roster_doc = await get_session_roster(s_id)
    roster_len = len(roster_doc.identities) if roster_doc else 0

    records = await get_attendance_by_session(s_id)
    present_cnt = sum(1 for r in records if r.get("status") == "PRESENT")
    total_cnt = max(roster_len, len(records))

    pct = round((present_cnt / total_cnt * 100), 1) if total_cnt > 0 else 0.0

    return TeacherSessionSummaryItem(
        session_id=s_id,
        course_name=session.get("course_name", "Attendance"),
        class_code=session.get("class_code"),
        subject=session.get("subject"),
        total_students=total_cnt,
        present_count=present_cnt,
        attendance_percentage=pct,
        status=session.get("status", "ACTIVE"),
        created_at=session.get("created_at"),
    )


async def get_teacher_dashboard(user_id: str) -> TeacherDashboardResponse:
    """Generate complete teacher dashboard payload."""
    profile = await get_teacher_profile(user_id)

    # 1. Check if teacher has an active session
    active_doc = await get_active_session_by_teacher(user_id)
    active_summary = await _summarize_session(active_doc) if active_doc else None

    # 2. Retrieve past sessions
    all_sessions = await get_sessions_by_owner(user_id)
    previous_sessions: list[TeacherSessionSummaryItem] = []

    for s in all_sessions:
        # Exclude currently active session from past list
        if active_doc and s["session_id"] == active_doc["session_id"]:
            continue
        summary = await _summarize_session(s)
        previous_sessions.append(summary)

    return TeacherDashboardResponse(
        teacher=profile,
        active_session=active_summary,
        previous_sessions=previous_sessions,
    )
