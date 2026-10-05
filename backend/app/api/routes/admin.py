"""Admin API routes for multi-role management (Students, Teachers, Classes, Sessions)."""

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from app.api.dependencies.auth import require_admin
from app.database.academic import add_academic_class, add_subject
from app.database.biometric_profiles import delete_biometric_profile
from app.database.sessions import (
    create_session,
    delete_session_in_db,
    get_all_sessions_in_db,
    get_session,
)
from app.database.student_profiles import (
    delete_student_profile,
    get_student_profile_by_user_id,
    list_all_students_full,
)
from app.database.teacher_profiles import (
    assign_classes_to_teacher,
    delete_teacher_profile,
    list_all_teachers,
)
from app.database.users import delete_user_by_id, get_all_users
from app.schemas.academic import AcademicClass, Subject
from app.schemas.session import SessionCreate, SessionResponse
from app.schemas.student import (
    StudentProfileResponse,
    StudentRegisterRequest,
)
from app.schemas.teacher import (
    TeacherAssignClassesRequest,
    TeacherProfileResponse,
    TeacherRegisterRequest,
)
from app.services.session_enrollment import get_enrolled_roster
from app.services.session_finalization import finalize_session_attendance
from app.services.student_service import register_student_account
from app.services.teacher_service import register_teacher_account

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
)


class AdminUserInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    email: str
    role: str
    name: Optional[str] = None
    student_id: Optional[str] = None
    is_active: bool = True
    created_at: Optional[str] = None


class AddClassRequest(BaseModel):
    class_code: str
    branch: str
    section: str
    semester: Optional[int] = None


class AddSubjectRequest(BaseModel):
    name: str
    code: Optional[str] = None
    branch: Optional[str] = None


# --- 1. USER ACCOUNTS OVERVIEW ---


@router.get(
    "/users",
    response_model=list[AdminUserInfo],
    summary="List all registered platform users",
)
async def list_all_users_endpoint(
    current_user: Annotated[dict, Depends(require_admin)],
    role: Optional[str] = Query(None, description="Filter by role: TEACHER, STUDENT, or ADMIN"),
) -> list[AdminUserInfo]:
    users = await get_all_users(role=role)
    result = []
    for u in users:
        created_at_str = (
            u["created_at"].isoformat()
            if "created_at" in u and hasattr(u["created_at"], "isoformat")
            else str(u.get("created_at", ""))
        )
        result.append(
            AdminUserInfo(
                user_id=u.get("user_id", ""),
                email=u.get("email", ""),
                role=u.get("role", ""),
                name=u.get("name"),
                student_id=u.get("student_id"),
                is_active=u.get("is_active", True),
                created_at=created_at_str,
            )
        )
    return result


# --- 2. STUDENT MANAGEMENT ---


@router.get(
    "/students",
    response_model=list[StudentProfileResponse],
    summary="List all students with academic grouping and biometric registration status",
)
async def admin_list_students(
    current_user: Annotated[dict, Depends(require_admin)],
) -> list[StudentProfileResponse]:
    students = await list_all_students_full()
    return [
        StudentProfileResponse(
            user_id=s["user_id"],
            identity=s.get("identity") or s.get("student_id", s["user_id"]),
            name=s.get("name", "Student"),
            email=s.get("email", ""),
            student_id=s.get("student_id", ""),
            roll_number=s.get("roll_number", ""),
            branch=s.get("branch", ""),
            section=s.get("section", ""),
            class_code=s.get("class_code", ""),
            photo_url=None,
            has_biometric=s.get("has_biometric", False),
            created_at=s.get("created_at"),
        )
        for s in students
    ]


@router.post(
    "/students",
    response_model=StudentProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin create a new student account with biometric profile",
)
async def admin_create_student(
    payload: StudentRegisterRequest,
    current_user: Annotated[dict, Depends(require_admin)],
) -> StudentProfileResponse:
    try:
        return await register_student_account(payload, enrolled_by=current_user["user_id"])
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.delete(
    "/students/{user_id}",
    summary="Admin delete a student account and biometric record",
)
async def admin_delete_student(
    user_id: str,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    prof = await get_student_profile_by_user_id(user_id)
    if prof:
        await delete_biometric_profile(prof.get("identity") or prof.get("student_id"))
    await delete_student_profile(user_id)
    await delete_user_by_id(user_id)
    return {"status": "deleted", "user_id": user_id}


# --- 3. TEACHER MANAGEMENT ---


@router.get(
    "/teachers",
    response_model=list[TeacherProfileResponse],
    summary="List all teachers and their assigned classes and subjects",
)
async def admin_list_teachers(
    current_user: Annotated[dict, Depends(require_admin)],
) -> list[TeacherProfileResponse]:
    teachers = await list_all_teachers()
    return [TeacherProfileResponse(**t) for t in teachers]


@router.post(
    "/teachers",
    response_model=TeacherProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin create a new teacher account",
)
async def admin_create_teacher(
    payload: TeacherRegisterRequest,
    current_user: Annotated[dict, Depends(require_admin)],
) -> TeacherProfileResponse:
    try:
        return await register_teacher_account(payload)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.delete(
    "/teachers/{user_id}",
    summary="Admin delete a teacher account",
)
async def admin_delete_teacher(
    user_id: str,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    await delete_teacher_profile(user_id)
    await delete_user_by_id(user_id)
    return {"status": "deleted", "user_id": user_id}


@router.post(
    "/teachers/{teacher_id}/assign",
    response_model=TeacherProfileResponse,
    summary="Assign classes and subjects to a teacher",
)
async def admin_assign_teacher_classes(
    teacher_id: str,
    payload: TeacherAssignClassesRequest,
    current_user: Annotated[dict, Depends(require_admin)],
) -> TeacherProfileResponse:
    updated = await assign_classes_to_teacher(
        teacher_id=teacher_id,
        assigned_classes=payload.assigned_classes,
        assigned_subjects=payload.assigned_subjects,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Teacher '{teacher_id}' not found",
        )
    return TeacherProfileResponse(**updated)


# --- 4. ACADEMIC STRUCTURE MANAGEMENT ---


@router.post(
    "/academic/classes",
    response_model=AcademicClass,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new academic class cohort",
)
async def admin_add_class(
    payload: AddClassRequest,
    current_user: Annotated[dict, Depends(require_admin)],
) -> AcademicClass:
    doc = await add_academic_class(
        class_code=payload.class_code,
        branch=payload.branch,
        section=payload.section,
        semester=payload.semester,
    )
    return AcademicClass(**doc)


@router.post(
    "/academic/subjects",
    response_model=Subject,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new academic course/subject",
)
async def admin_add_subject(
    payload: AddSubjectRequest,
    current_user: Annotated[dict, Depends(require_admin)],
) -> Subject:
    doc = await add_subject(
        name=payload.name,
        code=payload.code,
        branch=payload.branch,
    )
    return Subject(**doc)


# --- 5. SESSION MONITORING ---


@router.get(
    "/sessions",
    response_model=list[SessionResponse],
    summary="List attendance sessions across teachers with optional filters",
)
async def list_all_sessions_endpoint(
    current_user: Annotated[dict, Depends(require_admin)],
    branch: Optional[str] = Query(None, description="Filter by branch"),
    section: Optional[str] = Query(None, description="Filter by section"),
    subject: Optional[str] = Query(None, description="Filter by subject"),
    teacher: Optional[str] = Query(None, description="Filter by teacher ID or user_id"),
    status: Optional[str] = Query(
        None, description="Filter by status: ACTIVE, FINALIZED, SCHEDULED"
    ),
) -> list[SessionResponse]:
    sessions = await get_all_sessions_in_db()

    filtered = []
    for s in sessions:
        if branch and s.get("branch") and s["branch"].lower() != branch.lower():
            continue
        if section and s.get("section") and s["section"].upper() != section.upper():
            continue
        if subject and s.get("subject") and subject.lower() not in s["subject"].lower():
            continue
        if teacher and s.get("created_by") != teacher:
            continue
        if status and s.get("status") and s["status"].upper() != status.upper():
            continue

        filtered.append(
            SessionResponse(
                session_id=s["session_id"],
                course_name=s["course_name"],
                classroom_id=s["classroom_id"],
                start_time=s["start_time"],
                end_time=s["end_time"],
                class_code=s.get("class_code"),
                subject=s.get("subject"),
                branch=s.get("branch"),
                section=s.get("section"),
                required_presence_percentage=s["required_presence_percentage"],
                status=s["status"],
                created_by=s["created_by"],
            )
        )
    return filtered


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=201,
    summary="Create a new attendance session as Administrator",
)
async def admin_create_session_endpoint(
    session: SessionCreate,
    current_user: Annotated[dict, Depends(require_admin)],
    assigned_teacher_id: Optional[str] = Query(
        None, description="Optional teacher ID to assign this session to"
    ),
) -> SessionResponse:
    created_by = assigned_teacher_id if assigned_teacher_id else current_user["user_id"]
    created_session = await create_session(session, created_by=created_by)

    return SessionResponse(
        session_id=created_session["session_id"],
        course_name=created_session["course_name"],
        classroom_id=created_session["classroom_id"],
        start_time=created_session["start_time"],
        end_time=created_session["end_time"],
        class_code=created_session.get("class_code"),
        subject=created_session.get("subject"),
        branch=created_session.get("branch"),
        section=created_session.get("section"),
        required_presence_percentage=created_session["required_presence_percentage"],
        status=created_session["status"],
        created_by=created_session["created_by"],
    )


@router.delete(
    "/sessions/{session_id}",
    summary="Delete any attendance session as Administrator",
)
async def admin_delete_session_endpoint(
    session_id: str,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    deleted = await delete_session_in_db(session_id)
    return {"deleted": deleted, "session_id": session_id}


@router.post(
    "/sessions/{session_id}/finalize",
    summary="Finalize and lock any attendance session as Administrator",
)
async def admin_finalize_session_endpoint(
    session_id: str,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    roster = await get_enrolled_roster(session_id)
    if roster is None:
        raise HTTPException(status_code=404, detail="Session roster not found")

    records = await finalize_session_attendance(
        session_id=session_id,
        session_start=session["start_time"],
        session_end=session["end_time"],
        required_presence_percentage=session["required_presence_percentage"],
        roster=roster,
    )

    return {
        "session_id": session_id,
        "status": "FINALIZED",
        "records_finalized": len(records),
    }
