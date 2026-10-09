"""Admin API routes for managing accounts: edit, reset password, administrators."""

from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.auth import require_admin
from app.database.mongodb import get_database
from app.services import account_admin_service as accounts
from app.services.account_admin_service import AccountAdminError

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin-accounts"],
)


class StudentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=2, max_length=128)
    email: Optional[str] = Field(default=None, min_length=3, max_length=254)
    student_id: Optional[str] = Field(default=None, min_length=2, max_length=64)
    roll_number: Optional[str] = Field(default=None, min_length=2, max_length=64)
    branch: Optional[str] = Field(default=None, min_length=1, max_length=64)
    section: Optional[str] = Field(default=None, min_length=1, max_length=16)
    class_code: Optional[str] = Field(default=None, min_length=2, max_length=20)


class TeacherUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=2, max_length=128)
    email: Optional[str] = Field(default=None, min_length=3, max_length=254)
    teacher_id: Optional[str] = Field(default=None, min_length=2, max_length=64)
    department: Optional[str] = Field(default=None, min_length=2, max_length=128)
    assigned_classes: Optional[list[str]] = None
    assigned_subjects: Optional[list[str]] = None


class AdminCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=128)
    email: str = Field(min_length=3, max_length=254)
    # The first password; its owner must replace it at first login.
    password: str = Field(min_length=12, max_length=128)


def _refused(exc: AccountAdminError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.patch("/students/{user_id}", summary="Edit a student's name, email, ID or class")
async def admin_update_student(
    user_id: str,
    payload: StudentUpdateRequest,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict[str, Any]:
    try:
        result = await accounts.update_student(
            get_database(), user_id, updated_by=current_user, **payload.model_dump()
        )
    except AccountAdminError as exc:
        raise _refused(exc) from exc
    return {"status": "updated", "user_id": user_id, **result}


@router.patch(
    "/teachers/{user_id}",
    summary="Edit a teacher's name, email, teacher ID, department, classes or subjects",
)
async def admin_update_teacher(
    user_id: str,
    payload: TeacherUpdateRequest,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict[str, Any]:
    try:
        result = await accounts.update_teacher(
            get_database(), user_id, updated_by=current_user, **payload.model_dump()
        )
    except AccountAdminError as exc:
        raise _refused(exc) from exc
    return {"status": "updated", "user_id": user_id, **result}


@router.post(
    "/users/{user_id}/reset-password",
    summary="Give an account a temporary password that must be changed at the next login",
)
async def admin_reset_password(
    user_id: str,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict[str, Any]:
    """The temporary password is returned once, here, and never again."""
    try:
        return await accounts.reset_password(get_database(), user_id, reset_by=current_user)
    except AccountAdminError as exc:
        raise _refused(exc) from exc


@router.get("/admins", summary="List administrator accounts")
async def admin_list_admins(
    current_user: Annotated[dict, Depends(require_admin)],
) -> list[dict[str, Any]]:
    return await accounts.list_admins(get_database())


@router.post("/admins", status_code=201, summary="Create another administrator account")
async def admin_create_admin(
    payload: AdminCreateRequest,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict[str, Any]:
    try:
        return await accounts.create_admin(
            get_database(),
            email=payload.email,
            password=payload.password,
            name=payload.name,
            created_by=current_user,
        )
    except AccountAdminError as exc:
        raise _refused(exc) from exc


@router.delete("/admins/{user_id}", summary="Delete another administrator account")
async def admin_delete_admin(
    user_id: str,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict[str, Any]:
    try:
        return await accounts.delete_admin(get_database(), user_id, deleted_by=current_user)
    except AccountAdminError as exc:
        raise _refused(exc) from exc
