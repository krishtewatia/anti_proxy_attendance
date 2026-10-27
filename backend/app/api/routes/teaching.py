"""Teachers on the timetable: class assignment (admin), the teacher's timetable,
and starting a session from a timetable slot."""

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.auth import (
    get_owned_session,
    require_admin,
    require_teacher,
    require_teacher_or_admin,
    require_teacher_signed_in,
    require_student,
)
from app.database.mongodb import get_database
from app.services import reports_service as reports
from app.services import rounds_service as rounds
from app.services import teacher_setup_service as setup
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


@router.put(
    "/api/v1/admin/org/classes/{class_id:path}/teachers", summary="Set the teachers of a class"
)
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
    "/api/v1/sessions/{session_id}/rounds/{round_name}/finalize",
    summary="Finalize ENTRY or EXIT: the camera stops for it; hand changes for 24 h",
)
async def finalize_round(
    session_id: str, round_name: str, current_user: Annotated[dict, Depends(require_teacher)]
) -> dict:
    session = await get_owned_session(session_id, current_user)
    try:
        return await rounds.finalize_round(
            get_database(), session, round_name.upper(), actor=current_user
        )
    except rounds.RoundError as exc:
        raise _round_http(exc) from exc


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


# ------------------------------------------------------------------ teachers choose their classes


class ClassChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    class_ids: list[str] = Field(min_length=1, max_length=200)


class AdjustedApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    class_ids: Optional[list[str]] = Field(default=None, max_length=200)


class Rejection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=300)


def _setup_http(exc: setup.TeacherSetupError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get(
    "/api/v1/teachers/setup/options",
    summary="Subjects you can choose, with their sections and groups",
)
async def teacher_setup_options(
    current_user: Annotated[dict, Depends(require_teacher_signed_in)],
) -> dict:
    return await setup.options(get_database())


@router.get("/api/v1/teachers/setup/me", summary="Your approved classes and your latest request")
async def teacher_setup_me(
    current_user: Annotated[dict, Depends(require_teacher_signed_in)],
) -> dict:
    return await setup.my_status(get_database(), current_user)


@router.post(
    "/api/v1/teachers/setup/requests",
    status_code=201,
    summary="Send your subjects and sections for approval",
)
async def teacher_setup_submit(
    payload: ClassChoice, current_user: Annotated[dict, Depends(require_teacher_signed_in)]
) -> dict:
    try:
        return await setup.submit(get_database(), current_user, payload.class_ids)
    except setup.TeacherSetupError as exc:
        raise _setup_http(exc) from exc


@router.delete("/api/v1/teachers/setup/requests/current", summary="Withdraw your waiting request")
async def teacher_setup_withdraw(
    current_user: Annotated[dict, Depends(require_teacher_signed_in)],
) -> dict:
    try:
        return await setup.withdraw(get_database(), current_user)
    except setup.TeacherSetupError as exc:
        raise _setup_http(exc) from exc


@router.get(
    "/api/v1/admin/teacher-requests", summary="Teachers' class requests waiting for approval"
)
async def teacher_requests(current_user: Annotated[dict, Depends(require_admin)]) -> dict:
    return {"requests": await setup.waiting(get_database())}


@router.post(
    "/api/v1/admin/teacher-requests/{request_id}/approve", summary="Approve (optionally adjusted)"
)
async def approve_teacher_request(
    request_id: str,
    payload: AdjustedApproval,
    current_user: Annotated[dict, Depends(require_admin)],
) -> dict:
    try:
        return await setup.approve(get_database(), request_id, current_user, payload.class_ids)
    except setup.TeacherSetupError as exc:
        raise _setup_http(exc) from exc


@router.post("/api/v1/admin/teacher-requests/{request_id}/reject", summary="Reject with a reason")
async def reject_teacher_request(
    request_id: str, payload: Rejection, current_user: Annotated[dict, Depends(require_admin)]
) -> dict:
    try:
        return await setup.reject(get_database(), request_id, current_user, payload.reason)
    except setup.TeacherSetupError as exc:
        raise _setup_http(exc) from exc


@router.get(
    "/api/v1/admin/teacher-requests/options",
    summary="Subjects with their sections and groups (for adjusting)",
)
async def teacher_request_options(current_user: Annotated[dict, Depends(require_admin)]) -> dict:
    return await setup.options(get_database())


# ------------------------------------------------------------------ reports and downloads


def _report_http(exc: reports.ReportError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


def _csv_response(text: str, filename: str) -> Response:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in filename)
    return Response(
        content=text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe}"'},
    )


@router.get(
    "/api/v1/students/attendance/subjects",
    summary="Your attendance per subject, counted in lectures",
)
async def my_subjects(current_user: Annotated[dict, Depends(require_student)]) -> dict:
    try:
        return await reports.student_subjects(get_database(), current_user["user_id"])
    except reports.ReportError as exc:
        raise _report_http(exc) from exc


@router.get(
    "/api/v1/students/attendance/subjects/{subject_key}", summary="Your lectures of one subject"
)
async def my_subject_lectures(
    subject_key: str, current_user: Annotated[dict, Depends(require_student)]
) -> dict:
    try:
        return await reports.student_lectures(get_database(), current_user["user_id"], subject_key)
    except reports.ReportError as exc:
        raise _report_http(exc) from exc


@router.get("/api/v1/teachers/classes", summary="Your classes (all classes for an administrator)")
async def my_classes(
    current_user: Annotated[dict, Depends(require_teacher_or_admin)],
) -> list[dict]:
    return await reports.teacher_classes(get_database(), current_user)


@router.get("/api/v1/teachers/classes/{class_id:path}/students.csv", summary="Class list (CSV)")
async def class_list(
    class_id: str, current_user: Annotated[dict, Depends(require_teacher_or_admin)]
) -> Response:
    db = get_database()
    try:
        cls = await reports.class_for(db, class_id, current_user)
    except reports.ReportError as exc:
        raise _report_http(exc) from exc
    return _csv_response(
        await reports.class_list_csv(db, cls), f"class_list_{cls.get('label') or class_id}.csv"
    )


@router.get(
    "/api/v1/teachers/classes/{class_id:path}/register.csv",
    summary="Register: one column per lecture (CSV)",
)
async def class_register(
    class_id: str,
    current_user: Annotated[dict, Depends(require_teacher_or_admin)],
    from_: Annotated[Optional[str], Query(alias="from", max_length=10)] = None,
    to: Annotated[Optional[str], Query(max_length=10)] = None,
) -> Response:
    db = get_database()
    try:
        cls = await reports.class_for(db, class_id, current_user)
        since = teaching.parse_day(from_) if from_ else None
        until = teaching.parse_day(to) if to else None
    except (reports.ReportError, teaching.TeachingError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _csv_response(
        await reports.register_csv(db, cls, since, until),
        f"register_{cls.get('label') or class_id}.csv",
    )


@router.get(
    "/api/v1/teachers/classes/{class_id:path}/sessions",
    summary="The class's sessions (for their CSVs)",
)
async def class_session_list(
    class_id: str, current_user: Annotated[dict, Depends(require_teacher_or_admin)]
) -> list[dict]:
    db = get_database()
    try:
        cls = await reports.class_for(db, class_id, current_user)
    except reports.ReportError as exc:
        raise _report_http(exc) from exc
    return await reports.class_sessions(db, cls)


@router.get(
    "/api/v1/teachers/classes/{class_id:path}/students",
    summary="The class's students with their attendance in it",
)
async def class_students(
    class_id: str, current_user: Annotated[dict, Depends(require_teacher_or_admin)]
) -> dict:
    db = get_database()
    try:
        cls = await reports.class_for(db, class_id, current_user)
    except reports.ReportError as exc:
        raise _report_http(exc) from exc
    return await reports.class_overview(db, cls)


@router.get(
    "/api/v1/teachers/classes/{class_id:path}/sessions/{session_id}",
    summary="One session of the class: each student's rounds and lectures",
)
async def class_session_sheet(
    class_id: str,
    session_id: str,
    current_user: Annotated[dict, Depends(require_teacher_or_admin)],
) -> dict:
    db = get_database()
    try:
        cls = await reports.class_for(db, class_id, current_user)
        return await reports.session_sheet(db, cls, session_id)
    except reports.ReportError as exc:
        raise _report_http(exc) from exc
