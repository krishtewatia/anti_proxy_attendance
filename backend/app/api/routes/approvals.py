"""Admin routes for reviewing registrations and photo changes."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.auth import require_admin
from app.core.uploads import pending_photo_path
from app.database.mongodb import get_database
from app.services.approval_service import (
    ApprovalError,
    approve_photo_change,
    approve_registration,
    list_pending,
    reject_photo_change,
    reject_registration,
)

router = APIRouter(prefix="/api/v1/admin/approvals", tags=["admin-approvals"])

PRIVATE_PHOTO_HEADERS = {"Cache-Control": "private, no-store", "Vary": "Authorization"}


class ApproveRegistrationRequest(BaseModel):
    """What the administrator decides at approval.

    A teacher needs ``assigned_classes``. For a student, ``branch`` and
    ``section`` confirm (or correct) the class they registered for.
    """

    model_config = ConfigDict(extra="forbid")

    assigned_classes: Optional[list[str]] = Field(default=None, max_length=50)
    assigned_subjects: Optional[list[str]] = Field(default=None, max_length=100)
    branch: Optional[str] = Field(default=None, max_length=128)
    section: Optional[str] = Field(default=None, max_length=16)
    # A student's class can also be confirmed by its code.
    class_code: Optional[str] = Field(default=None, max_length=20)


def _http(exc: ApprovalError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("", summary="Registrations and photo changes waiting for approval")
async def list_pending_approvals(
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    return await list_pending(get_database())


@router.get("/count", summary="How many items are waiting for approval")
async def count_pending_approvals(
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    return (await list_pending(get_database()))["counts"]


@router.post("/{user_id}/approve", summary="Approve a pending registration")
async def approve_registration_endpoint(
    user_id: str,
    current_user: Annotated[dict, Depends(require_admin)],
    payload: Optional[ApproveRegistrationRequest] = None,
) -> dict:
    body = payload or ApproveRegistrationRequest()
    try:
        return await approve_registration(
            get_database(),
            user_id,
            approved_by=current_user,
            assigned_classes=body.assigned_classes,
            assigned_subjects=body.assigned_subjects,
            branch=body.branch,
            section=body.section,
            class_code=body.class_code,
        )
    except ApprovalError as exc:
        raise _http(exc) from exc


@router.post(
    "/{user_id}/reject", summary="Reject a pending registration and remove everything it created"
)
async def reject_registration_endpoint(
    user_id: str,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    try:
        return await reject_registration(get_database(), user_id, rejected_by=current_user)
    except ApprovalError as exc:
        raise _http(exc) from exc


@router.get("/photos/{identity}/image", summary="The replacement photo waiting for review")
async def pending_photo_image(
    identity: str,
    current_user: Annotated[dict, Depends(require_admin)],
) -> Response:
    try:
        path = pending_photo_path(identity)
    except ValueError:
        raise HTTPException(status_code=404, detail="Photo not found")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Photo not found")
    return Response(
        content=path.read_bytes(), media_type="image/jpeg", headers=PRIVATE_PHOTO_HEADERS
    )


@router.post("/photos/{identity}/approve", summary="Approve a student's replacement photo")
async def approve_photo_change_endpoint(
    identity: str,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    try:
        return await approve_photo_change(get_database(), identity, approved_by=current_user)
    except ApprovalError as exc:
        raise _http(exc) from exc


@router.post("/photos/{identity}/reject", summary="Reject a student's replacement photo")
async def reject_photo_change_endpoint(
    identity: str,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    try:
        return await reject_photo_change(get_database(), identity, rejected_by=current_user)
    except ApprovalError as exc:
        raise _http(exc) from exc
