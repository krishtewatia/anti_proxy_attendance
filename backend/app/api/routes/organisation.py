"""Administrator routes for the pilot organisation model and timetables.

Structure (branch -> year/semester -> section, plus year-wide group sets), the
subject catalog, classes, and timetable versions: import a sheet as a draft
(or only check it), list versions and their flagged slots, and activate a
version from a date. Every route needs an administrator.
"""

from datetime import date
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

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
    if flagged_only:
        query["flags.0"] = {"$exists": True}
    if section:
        query["audience.section"] = section.upper()
    if set_code:
        query["audience.set_code"] = set_code.upper()
    slots = [doc async for doc in db[org.SLOTS].find(query, {"_id": 0})]
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
