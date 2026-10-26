"""Teachers on the timetable: class assignment (admin), the teacher's timetable,
and starting a session from a timetable slot."""

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.auth import (
    get_owned_session,
    require_admin,
    require_teacher,
    require_teacher_or_admin,
)
from app.database.mongodb import get_database
from app.services import rounds_service as rounds
from app.services import teaching_service as teaching

router = APIRouter(tags=["teaching"])


class TeacherList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    teacher_ids: list[str] = Field(default_factory=list, max_length=20)


class ClassList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    class_ids: list[str] = Field(default_factory=list, max_length=200)


class SlotStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_id: str = Field(min_length=1, max_length=64)
    date: Optional[str] = Field(default=None, max_length=10)


def _http(exc: teaching.TeachingError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.put("/api/v1/admin/org/classes/{class_id}/teachers", summary="Set the teachers of a class")
async def set_class_teachers(
    class_id: str, payload: TeacherList, current_user: Annotated[dict, Depends(require_admin)]
) -> dict:
    try:
        return await teaching.set_class_teachers(
            get_database(), class_id, payload.teacher_ids, current_user
        )
    except teaching.TeachingError as exc:
        raise _http(exc) from exc


@router.put(
    "/api/v1/admin/org/teachers/{user_id}/classes", summary="Set all the classes of a teacher"
)
async def set_teacher_classes(
    user_id: str, payload: ClassList, current_user: Annotated[dict, Depends(require_admin)]
) -> dict:
    try:
        return await teaching.set_teacher_classes(
            get_database(), user_id, payload.class_ids, current_user
        )
    except teaching.TeachingError as exc:
        raise _http(exc) from exc


@router.get("/api/v1/teachers/timetable", summary="Your timetable: today's slots and the week")
async def my_timetable(
    current_user: Annotated[dict, Depends(require_teacher)],
    date: Annotated[Optional[str], Query(max_length=10)] = None,
) -> dict:
    try:
        return await teaching.timetable(
            get_database(), current_user["user_id"], teaching.parse_day(date)
        )
    except teaching.TeachingError as exc:
        raise _http(exc) from exc


@router.post(
    "/api/v1/teachers/sessions/from-slot",
    summary="Start (or reopen) the session of a timetable slot",
)
async def start_from_slot(
    payload: SlotStart, current_user: Annotated[dict, Depends(require_teacher)]
) -> dict:
    try:
        session = await teaching.start_from_slot(
            get_database(), current_user, payload.slot_id, teaching.parse_day(payload.date)
        )
    except teaching.TeachingError as exc:
        raise _http(exc) from exc
    return teaching.public_session(session)


# ------------------------------------------------------------------ rounds


class RoundMark(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity: str = Field(min_length=1, max_length=128)
    status: Literal["PRESENT", "ABSENT"]
    reason: str = Field(default="", max_length=500)


def _round_http(exc: rounds.RoundError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


async def _change_round(session_id: str, round_name: str, open_: bool, current_user: dict) -> dict:
    session = await get_owned_session(session_id, current_user)
    try:
        return await rounds.set_round(
            get_database(), session, round_name.upper(), open_=open_, actor=current_user
        )
    except rounds.RoundError as exc:
        raise _round_http(exc) from exc


@router.post(
    "/api/v1/sessions/{session_id}/rounds/{round_name}/open", summary="Open the ENTRY or EXIT round"
)
async def open_round(
    session_id: str, round_name: str, current_user: Annotated[dict, Depends(require_teacher)]
) -> dict:
    return await _change_round(session_id, round_name, True, current_user)


@router.post("/api/v1/sessions/{session_id}/rounds/{round_name}/close", summary="Close the round")
async def close_round(
    session_id: str, round_name: str, current_user: Annotated[dict, Depends(require_teacher)]
) -> dict:
    return await _change_round(session_id, round_name, False, current_user)


@router.post(
    "/api/v1/sessions/{session_id}/rounds/{round_name}/marks",
    summary="Mark a student in a round by hand",
)
async def mark_round(
    session_id: str,
    round_name: str,
    payload: RoundMark,
    current_user: Annotated[dict, Depends(require_teacher_or_admin)],
) -> dict:
    session = await get_owned_session(session_id, current_user)
    try:
        return await rounds.mark_by_hand(
            get_database(),
            session,
            round_name.upper(),
            payload.identity,
            payload.status,
            payload.reason,
            current_user,
        )
    except rounds.RoundError as exc:
        raise _round_http(exc) from exc


@router.post(
    "/api/v1/admin/sessions/{session_id}/unlock",
    summary="Let the teacher correct a closed session again (48 h)",
)
async def unlock_session(
    session_id: str, current_user: Annotated[dict, Depends(require_admin)]
) -> dict:
    session = await get_owned_session(session_id, current_user)
    return await rounds.unlock(get_database(), session, current_user)
