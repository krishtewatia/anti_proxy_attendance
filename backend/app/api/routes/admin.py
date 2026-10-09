"""Admin API routes for multi-role management (Students, Teachers, Classes, Sessions)."""

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from app.api.dependencies.auth import require_admin
from app.services import academic_admin_service as catalog
from app.services.academic_admin_service import AcademicAdminError
from app.database.mongodb import get_database
from app.database.sessions import (
    create_session,
    delete_session_in_db,
    get_all_sessions_in_db,
    get_session,
)
from app.database.student_profiles import list_all_students_full
from app.database.teacher_profiles import list_all_teachers
from app.database.users import get_all_users
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
from app.services.account_admin_service import (
    AccountAdminError,
    delete_teacher,
    mark_created_by_admin,
    update_teacher,
)
from app.services.session_enrollment import get_enrolled_roster
from app.services.student_deletion import (
    NotAStudentAccount,
    StudentNotFound,
    delete_student_completely,
)
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


class UpdateClassRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    class_code: Optional[str] = None
    branch: Optional[str] = None
    section: Optional[str] = None
    semester: Optional[int] = None
    clear_semester: bool = False


class AddSubjectRequest(BaseModel):
    name: str
    code: Optional[str] = None
    branch: Optional[str] = None


class UpdateSubjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    code: Optional[str] = None
    branch: Optional[str] = None


def _catalog_refused(exc: AcademicAdminError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


async def _refuse_unavailable_assignments(classes: list[str], subjects: list[str]) -> None:
    """A new teacher can be given only classes and subjects that exist and are active."""
    db = get_database()
    codes = {str(c).strip().upper() for c in classes if str(c).strip()}
    unknown = []
    for code in sorted(codes):
        if not catalog.is_active(await catalog.find_class(db, code)):
            unknown.append(code)
    if unknown and await db["academic_classes"].count_documents({}) > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown or archived class: {', '.join(unknown)}",
        )
    refused = await catalog.unavailable_subjects(db, [s for s in subjects if s and s.strip()])
    if refused:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown or archived subject: {', '.join(refused)}",
        )


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
            class_code=s.get("class_code") or "",
            photo_url=(
                s.get("photo_url")
                or (
                    f"/api/v1/students/{s.get('identity') or s.get('student_id')}/photo"
                    if (s.get("identity") or s.get("student_id"))
                    else None
                )
            ),
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
        created = await register_student_account(
            payload, enrolled_by=current_user["user_id"], approved=True
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    # The administrator typed the first password: the student must replace it.
    await mark_created_by_admin(
        get_database(), created.user_id, role="STUDENT", created_by=current_user
    )
    return created


@router.delete(
    "/students/{user_id}",
    summary="Admin delete a student and everything held about them",
)
async def admin_delete_student(
    user_id: str,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    """Remove everything held about a student and record one audit entry.

    Account, profile, face template, stored photo, attendance records and
    their corrections, doorway events and roster entries all go. Only student
    accounts can be deleted here.
    """
    try:
        result = await delete_student_completely(get_database(), user_id, deleted_by=current_user)
    except StudentNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Student '{user_id}' not found"
        )
    except NotAStudentAccount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account is not a student account and cannot be deleted here.",
        )
    return {
        "status": "deleted",
        "user_id": user_id,
        "student_id": result.student_id,
        "removed": result.counts(),
    }


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
    await _refuse_unavailable_assignments(payload.assigned_classes, payload.assigned_subjects)
    try:
        created = await register_teacher_account(payload, approved=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    await mark_created_by_admin(
        get_database(), created.user_id, role="TEACHER", created_by=current_user
    )
    return created


@router.delete(
    "/teachers/{user_id}",
    summary="Admin delete a teacher account",
)
async def admin_delete_teacher(
    user_id: str,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    """Remove the teacher's account and profile and record one audit entry.

    The sessions and attendance they recorded are kept. Refused while one of
    their sessions is in progress. Only teacher accounts can be deleted here.
    """
    account = await get_database()["users"].find_one({"user_id": user_id}, {"role": 1})
    if account is not None and account.get("role") != "TEACHER":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account is not a teacher account and cannot be deleted here.",
        )
    try:
        return await delete_teacher(get_database(), user_id, deleted_by=current_user)
    except AccountAdminError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


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
    # Same rules and audit entry as editing the teacher: only active classes
    # and subjects can be added.
    db = get_database()
    profile = await db["teacher_profiles"].find_one(
        {"$or": [{"teacher_id": teacher_id}, {"user_id": teacher_id}]}, {"user_id": 1}
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Teacher '{teacher_id}' not found",
        )
    try:
        await update_teacher(
            db,
            profile["user_id"],
            updated_by=current_user,
            assigned_classes=payload.assigned_classes,
            assigned_subjects=payload.assigned_subjects,
        )
    except AccountAdminError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    updated = await db["teacher_profiles"].find_one({"user_id": profile["user_id"]}, {"_id": 0})
    return TeacherProfileResponse(**updated)


# --- 4. ACADEMIC STRUCTURE MANAGEMENT ---


@router.get(
    "/academic/classes",
    summary="Every class, archived ones included, with what refers to each",
)
async def admin_list_classes(
    current_user: Annotated[dict, Depends(require_admin)],
) -> list[dict]:
    return await catalog.list_classes_for_admin(get_database())


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
    try:
        doc = await catalog.create_class(
            get_database(),
            class_code=payload.class_code,
            branch=payload.branch,
            section=payload.section,
            semester=payload.semester,
            created_by=current_user,
        )
    except AcademicAdminError as exc:
        raise _catalog_refused(exc) from exc
    return AcademicClass(**doc)


@router.patch(
    "/academic/classes/{class_code}",
    summary="Edit a class; its code, branch and section are fixed once it is in use",
)
async def admin_update_class(
    class_code: str,
    payload: UpdateClassRequest,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    try:
        return await catalog.update_class(
            get_database(),
            class_code,
            updated_by=current_user,
            new_class_code=payload.class_code,
            branch=payload.branch,
            section=payload.section,
            semester=payload.semester,
            clear_semester=payload.clear_semester,
        )
    except AcademicAdminError as exc:
        raise _catalog_refused(exc) from exc


@router.post(
    "/academic/classes/{class_code}/archive",
    summary="Hide a class from registration, new sessions and new assignments",
)
async def admin_archive_class(
    class_code: str,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    try:
        return await catalog.set_class_archived(
            get_database(), class_code, archived=True, changed_by=current_user
        )
    except AcademicAdminError as exc:
        raise _catalog_refused(exc) from exc


@router.post(
    "/academic/classes/{class_code}/unarchive",
    summary="Make an archived class available again",
)
async def admin_unarchive_class(
    class_code: str,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    try:
        return await catalog.set_class_archived(
            get_database(), class_code, archived=False, changed_by=current_user
        )
    except AcademicAdminError as exc:
        raise _catalog_refused(exc) from exc


@router.delete(
    "/academic/classes/{class_code}",
    summary="Delete a class that nothing refers to",
)
async def admin_delete_class(
    class_code: str,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    try:
        return await catalog.delete_class(get_database(), class_code, deleted_by=current_user)
    except AcademicAdminError as exc:
        raise _catalog_refused(exc) from exc


@router.get(
    "/academic/subjects",
    summary="Every subject, archived ones included, with what refers to each",
)
async def admin_list_subjects(
    current_user: Annotated[dict, Depends(require_admin)],
) -> list[dict]:
    return await catalog.list_subjects_for_admin(get_database())


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
    try:
        doc = await catalog.create_subject(
            get_database(),
            name=payload.name,
            code=payload.code,
            branch=payload.branch,
            created_by=current_user,
        )
    except AcademicAdminError as exc:
        raise _catalog_refused(exc) from exc
    return Subject(**doc)


@router.patch(
    "/academic/subjects/{subject_id}",
    summary="Edit a subject; its name is fixed once it is in use",
)
async def admin_update_subject(
    subject_id: str,
    payload: UpdateSubjectRequest,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    try:
        return await catalog.update_subject(
            get_database(),
            subject_id,
            updated_by=current_user,
            name=payload.name,
            code=payload.code,
            branch=payload.branch,
        )
    except AcademicAdminError as exc:
        raise _catalog_refused(exc) from exc


@router.post(
    "/academic/subjects/{subject_id}/archive",
    summary="Hide a subject from new sessions and new assignments",
)
async def admin_archive_subject(
    subject_id: str,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    try:
        return await catalog.set_subject_archived(
            get_database(), subject_id, archived=True, changed_by=current_user
        )
    except AcademicAdminError as exc:
        raise _catalog_refused(exc) from exc


@router.post(
    "/academic/subjects/{subject_id}/unarchive",
    summary="Make an archived subject available again",
)
async def admin_unarchive_subject(
    subject_id: str,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    try:
        return await catalog.set_subject_archived(
            get_database(), subject_id, archived=False, changed_by=current_user
        )
    except AcademicAdminError as exc:
        raise _catalog_refused(exc) from exc


@router.delete(
    "/academic/subjects/{subject_id}",
    summary="Delete a subject that nothing refers to",
)
async def admin_delete_subject(
    subject_id: str,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    try:
        return await catalog.delete_subject(get_database(), subject_id, deleted_by=current_user)
    except AcademicAdminError as exc:
        raise _catalog_refused(exc) from exc


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
    try:
        await catalog.refuse_archived_session_target(
            get_database(), class_code=session.class_code, subject=session.subject
        )
    except AcademicAdminError as exc:
        raise _catalog_refused(exc) from exc
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
