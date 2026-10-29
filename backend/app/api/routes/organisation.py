"""Administrator routes for the pilot organisation model and timetables.

Structure (branch -> year/semester -> section, plus year-wide group sets), the
subject catalog, classes, and timetable versions: import a sheet as a draft
(or only check it), list versions and their flagged slots, and activate a
version from a date. Every route needs an administrator.
"""

from datetime import date
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.auth import require_admin
from app.database.mongodb import get_database
from app.services import organisation_service as org
from app.services.audit_service import record_audit_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/org", tags=["admin-organisation"])

Admin = Annotated[dict, Depends(require_admin)]


class ActivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_from: date


class TermDatesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: Optional[date] = None
    end_date: Optional[date] = None


class SubjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Optional[str] = Field(default=None, max_length=40)
    name: Optional[str] = Field(default=None, max_length=200)
    code_status: Optional[str] = None
    code_note: Optional[str] = Field(default=None, max_length=500)


class ResolveFlagRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=1, max_length=500)


class CalendarExceptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cohort_id: str
    date: date
    reason: str = Field(min_length=1, max_length=200)
    class_id: Optional[str] = None


class SettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    college_email_domain: Optional[str] = Field(default=None, max_length=100)
    edit_window_hours: Optional[int] = None
    shortage_threshold_percent: Optional[int] = None


def _raise(exc: org.OrganisationError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


async def _audit(admin: dict, action: str, resource_id: str, metadata: dict) -> None:
    try:
        await record_audit_event(
            actor_user_id=admin["user_id"],
            actor_role="ADMIN",
            action=action,
            resource_type="ACADEMIC",
            resource_id=resource_id,
            metadata=metadata,
        )
    except Exception:
        logger.exception("Could not record the %s audit event", action)


@router.post("/seed-pilot", summary="Create or update the pilot's structure and subject catalog")
async def seed_pilot(admin: Admin) -> dict:
    """Idempotent. Never assigns teachers and never touches students or attendance."""
    try:
        result = await org.seed_structure(get_database())
    except org.OrganisationError as exc:
        _raise(exc)
    await _audit(admin, "ORGANISATION_SEEDED", result["cohort_id"], result)
    return result


@router.get(
    "/structure", summary="Branch -> year/semester -> sections, with the year-wide group sets"
)
async def get_structure(admin: Admin) -> dict:
    return await org.structure(get_database())


@router.get("/subjects", summary="The subject catalog, with code flags")
async def list_subjects(admin: Admin) -> list[dict]:
    db = get_database()
    return [doc async for doc in db[org.SUBJECTS].find({}, {"_id": 0}).sort("key", 1)]


@router.get("/classes", summary="Classes (a subject taught to one section or one year-wide group)")
async def list_classes(
    admin: Admin,
    cohort_id: Optional[str] = None,
    section: Optional[str] = None,
    set_code: Optional[str] = None,
    group_code: Optional[str] = None,
    subject_key: Optional[str] = None,
) -> list[dict]:
    query: dict = {}
    if cohort_id:
        query["cohort_id"] = cohort_id
    if section:
        query["audience.kind"] = "SECTION"
        query["audience.section"] = section.upper()
    if set_code:
        query["audience.kind"] = "GROUP"
        query["audience.set_code"] = set_code.upper()
    if group_code:
        query["audience.group_code"] = group_code.upper()
    if subject_key:
        query["subject_key"] = subject_key.upper()
    db = get_database()
    return [doc async for doc in db[org.CLASSES].find(query, {"_id": 0}).sort("class_id", 1)]


@router.get(
    "/timetable/sample.csv",
    summary="A sample timetable sheet: the columns the import reads, with example rows",
)
async def timetable_sample(admin: Admin) -> Response:
    return Response(
        content=org.timetable_sample_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="timetable_sample.csv"'},
    )


@router.post(
    "/timetable/import",
    summary="Check a timetable sheet (CSV) and, unless dry_run, store it as a draft version",
)
async def import_timetable(
    request: Request,
    admin: Admin,
    cohort_id: str = Query(..., description="Cohort the sheet is for"),
    dry_run: bool = Query(True, description="Only check the sheet; store nothing"),
    source_name: str = Query("timetable.csv", max_length=200),
) -> dict:
    body = await request.body()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Send the CSV file as the request body."
        )
    if len(body) > org.MAX_TIMETABLE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="The file is too large."
        )
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="The file must be UTF-8 text."
        )

    db = get_database()
    try:
        if dry_run:
            plan = await org.plan_timetable_import(db, cohort_id, text)
            return {"dry_run": True, **plan.report()}
        version = await org.import_timetable(
            db, cohort_id, text, source_name=source_name, actor_user_id=admin["user_id"]
        )
    except org.OrganisationError as exc:
        if exc.status_code == 422:
            plan = await org.plan_timetable_import(db, cohort_id, text)
            raise HTTPException(
                status_code=422, detail={"message": str(exc), **plan.report()}
            ) from exc
        _raise(exc)
    version.pop("_id", None)
    await _audit(
        admin,
        "TIMETABLE_IMPORTED",
        version["version_id"],
        {
            "cohort_id": cohort_id,
            "slots": version["slots"],
            "flagged_slots": version["flagged_slots"],
            "sha256": version["sha256"],
        },
    )
    return {"dry_run": False, **version}


@router.get("/timetable/versions", summary="Timetable versions of a cohort, newest first")
async def list_versions(admin: Admin, cohort_id: Optional[str] = None) -> list[dict]:
    db = get_database()
    query = {"cohort_id": cohort_id} if cohort_id else {}
    return [doc async for doc in db[org.VERSIONS].find(query, {"_id": 0}).sort("created_at", -1)]


@router.get(
    "/timetable/versions/{version_id}/slots",
    summary="Slots of a version, optionally only flagged ones",
)
async def list_slots(
    version_id: str,
    admin: Admin,
    flagged_only: bool = False,
    section: Optional[str] = None,
    set_code: Optional[str] = None,
) -> list[dict]:
    db = get_database()
    if await db[org.VERSIONS].find_one({"version_id": version_id}) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="timetable version not found"
        )
    query: dict = {"version_id": version_id}
    if section:
        query["audience.section"] = section.upper()
    if set_code:
        query["audience.set_code"] = set_code.upper()
    slots = [doc async for doc in db[org.SLOTS].find(query, {"_id": 0})]
    subjects = {doc["key"]: doc async for doc in db[org.SUBJECTS].find({}, {"_id": 0})}
    slots = org.with_current_code_flags(slots, subjects)
    if flagged_only:
        slots = [slot for slot in slots if slot["flags"]]
    order = {day: i for i, day in enumerate(org.DAYS)}
    return sorted(slots, key=lambda s: (order.get(s["day"], 9), s["start_minute"], s["row"]))


@router.post(
    "/timetable/versions/{version_id}/activate", summary="Put a draft version in force from a date"
)
async def activate(version_id: str, payload: ActivateRequest, admin: Admin) -> dict:
    try:
        version = await org.activate_version(
            get_database(), version_id, payload.effective_from, actor_user_id=admin["user_id"]
        )
    except org.OrganisationError as exc:
        _raise(exc)
    await _audit(
        admin,
        "TIMETABLE_ACTIVATED",
        version_id,
        {"cohort_id": version["cohort_id"], "effective_from": version["effective_from"]},
    )
    return version


@router.patch("/terms/{term_id}", summary="Set the term's start and end dates")
async def set_term_dates(term_id: str, payload: TermDatesRequest, admin: Admin) -> dict:
    try:
        term = await org.update_term_dates(
            get_database(), term_id, payload.start_date, payload.end_date
        )
    except org.OrganisationError as exc:
        _raise(exc)
    await _audit(
        admin,
        "TERM_UPDATED",
        term_id,
        {"start_date": term["start_date"], "end_date": term["end_date"]},
    )
    return term


@router.patch("/subjects/{key}", summary="Correct a subject's ERP code, name or code status")
async def update_subject(key: str, payload: SubjectUpdateRequest, admin: Admin) -> dict:
    db = get_database()
    before = await db[org.SUBJECTS].find_one({"key": key}, {"_id": 0}) or {}
    try:
        subject = await org.update_subject(db, key, payload.model_dump(exclude_none=True))
    except org.OrganisationError as exc:
        _raise(exc)
    changed = {
        k: {"from": before.get(k), "to": subject.get(k)}
        for k in ("code", "name", "code_status")
        if before.get(k) != subject.get(k)
    }
    if changed:
        await _audit(admin, "SUBJECT_UPDATED", key, {"changes": changed})
    return subject


@router.post(
    "/timetable/slots/{slot_id}/flags/{kind}/resolve",
    summary="Mark a timetable flag as checked, with a note",
)
async def resolve_flag(slot_id: str, kind: str, payload: ResolveFlagRequest, admin: Admin) -> dict:
    try:
        slot = await org.resolve_flag(
            get_database(), slot_id, kind.upper(), payload.note, actor_user_id=admin["user_id"]
        )
    except org.OrganisationError as exc:
        _raise(exc)
    await _audit(
        admin, "TIMETABLE_FLAG_RESOLVED", slot_id, {"kind": kind.upper(), "row": slot.get("row")}
    )
    return slot


@router.get("/calendar", summary="Holidays and cancelled classes of a cohort")
async def list_calendar(admin: Admin, cohort_id: Optional[str] = None) -> list[dict]:
    db = get_database()
    query = {"cohort_id": cohort_id} if cohort_id else {}
    return [doc async for doc in db[org.CALENDAR].find(query, {"_id": 0}).sort("date", 1)]


@router.post(
    "/calendar",
    status_code=status.HTTP_201_CREATED,
    summary="Record a holiday or a cancelled class",
)
async def add_calendar(payload: CalendarExceptionRequest, admin: Admin) -> dict:
    try:
        doc = await org.add_calendar_exception(
            get_database(),
            cohort_id=payload.cohort_id,
            on=payload.date,
            reason=payload.reason,
            class_id=payload.class_id,
            actor_user_id=admin["user_id"],
        )
    except org.OrganisationError as exc:
        _raise(exc)
    await _audit(
        admin,
        "CALENDAR_UPDATED",
        doc["exception_id"],
        {"date": doc["date"], "class_id": doc["class_id"], "added": True},
    )
    doc.pop("_id", None)
    return doc


@router.delete("/calendar/{exception_id}", summary="Remove a holiday or cancelled class")
async def delete_calendar(exception_id: str, admin: Admin) -> dict:
    db = get_database()
    doc = await db[org.CALENDAR].find_one({"exception_id": exception_id})
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="calendar entry not found"
        )
    await db[org.CALENDAR].delete_one({"exception_id": exception_id})
    await _audit(
        admin,
        "CALENDAR_UPDATED",
        exception_id,
        {"date": doc["date"], "class_id": doc.get("class_id"), "added": False},
    )
    return {"deleted": exception_id}


@router.get("/settings", summary="Pilot settings")
async def get_settings(admin: Admin) -> dict:
    return await org.get_settings(get_database())


@router.put("/settings", summary="Change pilot settings")
async def put_settings(payload: SettingsRequest, admin: Admin) -> dict:
    db = get_database()
    before = await org.get_settings(db)
    try:
        after = await org.update_settings(db, payload.model_dump(exclude_none=True))
    except org.OrganisationError as exc:
        _raise(exc)
    changed = {k: {"from": before[k], "to": after[k]} for k in after if before[k] != after[k]}
    if changed:
        await _audit(admin, "SETTINGS_UPDATED", org.SETTINGS_ID, {"changes": changed})
    return after
