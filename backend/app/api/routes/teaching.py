"""Teachers on the timetable: class assignment (admin), the teacher's timetable,
and starting a session from a timetable slot."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.auth import require_admin, require_teacher
from app.database.mongodb import get_database
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
