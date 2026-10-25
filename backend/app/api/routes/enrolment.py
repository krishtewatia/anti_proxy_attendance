"""Student self-setup (section, groups, photos) and its approval by an administrator."""

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.auth import require_admin, require_student
from app.api.dependencies.rate_limiter import check_registration_rate_limit
from app.database.mongodb import get_database
from app.services import enrolment_service as enrolment
from app.services.photo_quality import MAX_PHOTOS

router = APIRouter(tags=["enrolment"])

STUDENT = "/api/v1/enrolment"
ADMIN = "/api/v1/admin/enrolment"

# A photo is personal data fetched with a token: never stored by a shared cache.
PRIVATE_PHOTO_HEADERS = {"Cache-Control": "private, no-store", "Vary": "Authorization"}


class GroupChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option: str = Field(min_length=1, max_length=16)
    group: str = Field(min_length=1, max_length=16)


class SetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cohort_id: str = Field(min_length=1, max_length=64)
    section: str = Field(min_length=1, max_length=8)
    choices: dict[str, GroupChoice] = Field(default_factory=dict)
    photos: list[str] = Field(default_factory=list, max_length=MAX_PHOTOS)
    consent_version: Optional[str] = Field(default=None, max_length=64)


class PhotoCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    photo_base64: str = Field(min_length=1)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Optional[str] = Field(default=None, max_length=300)


class BulkDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject"]
    request_ids: list[str] = Field(min_length=1, max_length=500)
    reason: Optional[str] = Field(default=None, max_length=300)


def _http(exc: enrolment.EnrolmentError) -> HTTPException:
    detail: object = str(exc)
    if exc.details is not None:
        detail = {"message": str(exc), "photos": exc.details}
    return HTTPException(status_code=exc.status_code, detail=detail)


# ------------------------------------------------------------------ student


@router.get(f"{STUDENT}/options", summary="Years, sections and groups to choose from")
async def setup_options(current_user: Annotated[dict, Depends(require_student)]) -> dict:
    return await enrolment.options(get_database())


@router.get(f"{STUDENT}/me", summary="Your approved setup and your latest request")
async def my_setup(current_user: Annotated[dict, Depends(require_student)]) -> dict:
    return await enrolment.my_status(get_database(), current_user)


@router.post(
    f"{STUDENT}/photos/check",
    summary="Check one face photo (nothing is stored)",
    dependencies=[Depends(check_registration_rate_limit)],
)
async def check_photo(
    payload: PhotoCheckRequest, current_user: Annotated[dict, Depends(require_student)]
) -> dict:
    try:
        return (await enrolment.check_one_photo(payload.photo_base64)).public()
    except enrolment.EnrolmentError as exc:
        raise _http(exc) from exc


@router.post(
    f"{STUDENT}/requests",
    status_code=status.HTTP_201_CREATED,
    summary="Send your setup (section, groups, photos) for approval",
)
async def submit_setup(
    payload: SetupRequest, current_user: Annotated[dict, Depends(require_student)]
) -> dict:
    try:
        return await enrolment.submit_request(
            get_database(), current_user, payload.model_dump(mode="json")
        )
    except enrolment.EnrolmentError as exc:
        raise _http(exc) from exc


@router.delete(f"{STUDENT}/requests/current", summary="Withdraw your waiting request")
async def withdraw_setup(current_user: Annotated[dict, Depends(require_student)]) -> dict:
    try:
        return await enrolment.withdraw_request(get_database(), current_user)
    except enrolment.EnrolmentError as exc:
        raise _http(exc) from exc


# ------------------------------------------------------------------ admin


@router.get(f"{ADMIN}/requests", summary="Setup requests, with counts per branch, year and section")
async def list_setup_requests(
    current_user: Annotated[dict, Depends(require_admin)],
    request_status: Annotated[str, Query(alias="status", max_length=16)] = "PENDING",
    cohort_id: Annotated[Optional[str], Query(max_length=64)] = None,
    section: Annotated[Optional[str], Query(max_length=8)] = None,
    set_code: Annotated[Optional[str], Query(max_length=16, pattern=r"^[A-Za-z0-9-]+$")] = None,
    option: Annotated[Optional[str], Query(max_length=16)] = None,
    group: Annotated[Optional[str], Query(max_length=16)] = None,
) -> dict:
    return await enrolment.list_requests(
        get_database(),
        {
            "status": request_status.upper(),
            "cohort_id": cohort_id,
            "section": section,
            "set_code": set_code,
            "option": option,
            "group": group,
        },
    )


@router.get(f"{ADMIN}/requests/{{request_id}}/photos/{{index}}", summary="One photo of a request")
async def setup_request_photo(
    request_id: str, index: int, current_user: Annotated[dict, Depends(require_admin)]
) -> Response:
    try:
        data = await enrolment.photo_bytes(get_database(), request_id, index)
    except enrolment.EnrolmentError as exc:
        raise _http(exc) from exc
    return Response(content=data, media_type="image/jpeg", headers=PRIVATE_PHOTO_HEADERS)


@router.post(f"{ADMIN}/requests/{{request_id}}/approve", summary="Approve one setup request")
async def approve_setup_request(
    request_id: str, current_user: Annotated[dict, Depends(require_admin)]
) -> dict:
    try:
        return await enrolment.decide(
            get_database(), [request_id], action="approve", actor=current_user
        )
    except enrolment.EnrolmentError as exc:
        raise _http(exc) from exc


@router.post(f"{ADMIN}/requests/{{request_id}}/reject", summary="Reject one setup request")
async def reject_setup_request(
    request_id: str,
    payload: DecisionRequest,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    try:
        return await enrolment.decide(
            get_database(), [request_id], action="reject", actor=current_user, reason=payload.reason
        )
    except enrolment.EnrolmentError as exc:
        raise _http(exc) from exc


@router.post(f"{ADMIN}/requests/bulk", summary="Approve or reject several setup requests")
async def bulk_setup_decision(
    payload: BulkDecisionRequest, current_user: Annotated[dict, Depends(require_admin)]
) -> dict:
    try:
        return await enrolment.decide(
            get_database(),
            payload.request_ids,
            action=payload.action,
            actor=current_user,
            reason=payload.reason,
        )
    except enrolment.EnrolmentError as exc:
        raise _http(exc) from exc
