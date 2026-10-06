import csv
from datetime import datetime, timezone
import io
import logging
import os
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.api.dependencies.auth import get_owned_session, require_teacher
from app.database.attendance import (
    get_attendance_by_session,
    upsert_attendance,
)
from app.database.mongodb import get_database
from app.database.session_roster import get_session_roster
from app.schemas.attendance import (
    AttendanceRecord,
    MarkAttendanceRequest,
    MarkAttendanceResponse,
)
from app.schemas.attendance_response import (
    AttendanceSessionResponse,
    AttendanceSummaryItem,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/attendance",
    tags=["attendance"],
)


DEFAULT_STUDENT_CATALOG: dict[str, dict[str, str]] = {
    "student1": {"student_id": "DS202601", "name": "Rahul Sharma"},
    "student2": {"student_id": "DS202602", "name": "Aman Kumar"},
    "student3": {"student_id": "DS202603", "name": "Priya Singh"},
    "student4": {"student_id": "DS202604", "name": "Krish Tewatia"},
    "person_01": {"student_id": "DS202601", "name": "Rahul Sharma"},
    "person_02": {"student_id": "DS202602", "name": "Aman Kumar"},
    "person_03": {"student_id": "DS202603", "name": "Priya Singh"},
    "person_04": {"student_id": "DS202604", "name": "Krish Tewatia"},
}


async def _resolve_student_info(db) -> dict[str, dict]:
    """Return map of identity -> { student_id, name } with catalog fallback."""
    mapping = {k: dict(v) for k, v in DEFAULT_STUDENT_CATALOG.items()}
    cursor = db["student_profiles"].find({})
    docs = await cursor.to_list(length=None)
    for doc in docs:
        ident = doc.get("identity") or doc.get("biometric_identity")
        if ident:
            stu_id = doc.get("student_id") or mapping.get(ident, {}).get("student_id", ident)
            name = (
                doc.get("name") or doc.get("full_name") or mapping.get(ident, {}).get("name", ident)
            )
            mapping[ident] = {
                "student_id": stu_id,
                "name": name,
            }
    return mapping


@router.get(
    "/active-session",
    summary="Get currently active attendance session metadata",
)
async def get_active_session_info():
    """Retrieve metadata of the current active attendance session for camera/vision integration."""
    db = get_database()
    active_sess = await db["sessions"].find_one({"status": "ACTIVE"}, sort=[("created_at", -1)])
    if not active_sess:
        return {"has_active_session": False, "session_id": None}
    return {
        "has_active_session": True,
        "session_id": active_sess["session_id"],
        "class_code": active_sess.get("class_code"),
        "subject": active_sess.get("subject"),
        "course_name": active_sess.get("course_name"),
    }


@router.get(
    "/vision-gallery",
    summary="Fetch all enrolled biometric profiles and identities for vision service sync",
)
async def get_vision_gallery_endpoint():
    """Returns all enrolled student biometric profiles with identities, names, and mean embeddings for vision matching."""
    db = get_database()
    student_map = await _resolve_student_info(db)
    cursor = db["biometric_profiles"].find({})
    bio_docs = await cursor.to_list(length=None)
    items = []
    for doc in bio_docs:
        ident = doc.get("identity")
        emb = doc.get("mean_embedding")
        if not ident or not emb:
            continue
        s_info = student_map.get(ident, {})
        items.append(
            {
                "identity": ident,
                "student_id": s_info.get("student_id", ident),
                "name": s_info.get("name", ident),
                "embedding": emb,
            }
        )
    return {"count": len(items), "gallery": items}


@router.get(
    "/{session_id}",
    response_model=AttendanceSessionResponse,
)
async def get_session_attendance(
    session_id: str,
    current_user: Annotated[dict, Depends(require_teacher)],
) -> AttendanceSessionResponse:
    """Return clean one-time attendance records for a session."""
    session = await get_owned_session(session_id, current_user)
    db = get_database()
    student_map = await _resolve_student_info(db)

    # 1. Fetch existing attendance records
    existing_records = await get_attendance_by_session(session_id)
    records_by_ident = {r["identity"]: r for r in existing_records}

    # 2. If roster has students not yet in attendance collection, initialize them as ABSENT
    roster_doc = await get_session_roster(session_id)
    roster_identities = (
        list(roster_doc.identities) if (roster_doc and roster_doc.identities) else []
    )
    for rec_ident in records_by_ident.keys():
        if rec_ident not in roster_identities:
            roster_identities.append(rec_ident)
    if not roster_identities:
        roster_identities = list(student_map.keys())

    summary_items: list[AttendanceSummaryItem] = []
    present_count = 0

    for ident in roster_identities:
        s_info = student_map.get(ident, {})
        stu_id = s_info.get("student_id", ident)
        stu_name = s_info.get("name", ident)

        rec = records_by_ident.get(ident)
        if rec:
            current_status = rec.get("status", "ABSENT")
        else:
            # Create initial ABSENT record in DB so state is persistent
            new_rec = AttendanceRecord(
                attendance_id=f"att_{session_id}_{ident}",
                session_id=session_id,
                identity=ident,
                student_id=stu_id,
                student_name=stu_name,
                status="ABSENT",
            )
            await upsert_attendance(new_rec)
            current_status = "ABSENT"

        if current_status == "PRESENT":
            present_count += 1

        summary_items.append(
            AttendanceSummaryItem(
                attendance_id=rec.get("attendance_id")
                if (rec and rec.get("attendance_id"))
                else f"att_{session_id}_{ident}",
                identity=ident,
                student_id=stu_id,
                student_name=stu_name,
                status=current_status,
                presence_duration_seconds=float(rec.get("presence_duration_seconds", 0.0))
                if rec
                else 0.0,
                presence_percentage=float(rec.get("presence_percentage", 0.0)) if rec else 0.0,
                required_presence_percentage=float(rec.get("required_presence_percentage", 0.0))
                if rec
                else 0.0,
                manually_corrected=bool(rec.get("manually_corrected", False)) if rec else False,
                requires_review=bool(rec.get("requires_review", False)) if rec else False,
                anomalies=rec.get("anomalies", []) if rec else [],
            )
        )

    return AttendanceSessionResponse(
        session_id=session_id,
        course_name=session.get("course_name"),
        total_students=len(summary_items),
        present_count=present_count,
        records=summary_items,
    )


@router.post(
    "/{session_id}/mark",
    response_model=MarkAttendanceResponse,
)
@router.post(
    "/mark",
    response_model=MarkAttendanceResponse,
)
async def mark_student_attendance(
    payload: MarkAttendanceRequest,
    session_id: Optional[str] = None,
) -> MarkAttendanceResponse:
    """One-Time Attendance Marker:

    Recognized student face -> Mark PRESENT.
    If already present -> Return 'already_present' without duplicate events or resets.
    """
    db = get_database()
    target_session_id = session_id or payload.session_id

    # If no session_id provided, find the active session
    if not target_session_id:
        active_sess = await db["sessions"].find_one({"status": "ACTIVE"}, sort=[("created_at", -1)])
        if not active_sess:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active attendance session found to mark attendance.",
            )
        target_session_id = active_sess["session_id"]

    ident = payload.identity
    if not ident or ident == "UNKNOWN":
        return MarkAttendanceResponse(
            status="error",
            identity="UNKNOWN",
            message="Cannot mark unconfirmed or UNKNOWN face",
        )

    student_map = await _resolve_student_info(db)
    s_info = student_map.get(ident, {})
    stu_id = s_info.get("student_id", ident)
    stu_name = s_info.get("name", ident)

    # Check existing attendance record in MongoDB
    rec = await db["attendance_records"].find_one(
        {"session_id": target_session_id, "identity": ident}
    )

    if rec and rec.get("status") == "PRESENT":
        return MarkAttendanceResponse(
            status="already_present",
            identity=ident,
            student_id=stu_id,
            student_name=stu_name,
            message=f"{stu_name} is already marked present",
        )

    # Mark as PRESENT
    now = datetime.now(timezone.utc)
    updated_record = AttendanceRecord(
        attendance_id=f"att_{target_session_id}_{ident}",
        session_id=target_session_id,
        identity=ident,
        student_id=stu_id,
        student_name=stu_name,
        status="PRESENT",
        marked_at=now,
    )
    await upsert_attendance(updated_record)

    # Ensure student is included in the session's roster
    await db["session_rosters"].update_one(
        {"session_id": target_session_id},
        {"$addToSet": {"identities": ident}},
        upsert=True,
    )

    logger.info(
        "Student marked PRESENT: %s (%s) for session %s",
        stu_name,
        stu_id,
        target_session_id,
    )

    return MarkAttendanceResponse(
        status="marked",
        identity=ident,
        student_id=stu_id,
        student_name=stu_name,
        message=f"✓ {stu_name} marked PRESENT",
    )


@router.get(
    "/{session_id}/export",
    summary="Export attendance as clean CSV file",
)
async def export_session_attendance_csv(
    session_id: str,
    current_user: Annotated[dict, Depends(require_teacher)],
):
    """Export one-time attendance list as a CSV file for download."""
    session = await get_owned_session(session_id, current_user)
    db = get_database()
    student_map = await _resolve_student_info(db)

    records = await get_attendance_by_session(session_id)
    records_by_ident = {r["identity"]: r for r in records}

    roster_doc = await get_session_roster(session_id)
    roster_identities = (
        list(roster_doc.identities) if (roster_doc and roster_doc.identities) else []
    )
    for rec_ident in records_by_ident.keys():
        if rec_ident not in roster_identities:
            roster_identities.append(rec_ident)
    if not roster_identities:
        roster_identities = list(student_map.keys())

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student ID", "Student Name", "Status"])

    for ident in roster_identities:
        s_info = student_map.get(ident, {})
        stu_id = s_info.get("student_id", ident)
        stu_name = s_info.get("name", ident)
        rec = records_by_ident.get(ident)
        st = rec.get("status", "ABSENT") if rec else "ABSENT"
        writer.writerow([stu_id, stu_name, st])

    csv_data = output.getvalue()
    import re

    course_raw = session.get("course_name", "attendance")
    course_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", course_raw)
    filename = f"{course_slug}_attendance_{session_id}.csv"

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class AttendanceStatusCorrectionRequest(BaseModel):
    status: Optional[str] = None
    new_status: Optional[str] = None
    new_presence_seconds: Optional[float] = 0.0
    reason: Optional[str] = None


@router.patch(
    "/{session_id}/records/{attendance_id}",
    summary="Teacher manual correction of attendance (PRESENT <-> ABSENT)",
)
async def update_student_attendance_status(
    session_id: str,
    attendance_id: str,
    payload: AttendanceStatusCorrectionRequest,
    current_user: Annotated[dict, Depends(require_teacher)],
) -> dict:
    """Allows teacher to manually toggle or correct attendance for students in their session."""
    from app.database.attendance import get_attendance_record, update_attendance_status
    from app.services.attendance_correction import correct_attendance

    _ = await get_owned_session(session_id, current_user)
    target_st = (payload.new_status or payload.status or "").upper().strip()
    if target_st not in ("PRESENT", "ABSENT"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Status must be either 'PRESENT' or 'ABSENT'",
        )

    # If this is a formal correction with new_status / reason, route through audit correction service
    if payload.new_status is not None:
        rec = await get_attendance_record(attendance_id)
        if not rec:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attendance record not found",
            )
        corr = await correct_attendance(
            attendance_id=attendance_id,
            new_status=target_st,
            new_presence_seconds=payload.new_presence_seconds or 0.0,
            reason=payload.reason or "Manual correction via ERP dashboard",
            corrected_by=current_user["user_id"],
        )
        return corr.model_dump()

    # Simple toggle flow
    updated = await update_attendance_status(attendance_id, target_st)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attendance record not found",
        )

    return {
        "attendance_id": attendance_id,
        "session_id": session_id,
        "status": updated["status"],
        "message": f"Attendance updated to {updated['status']}",
    }


@router.post(
    "/{session_id}/process-frame",
    summary="Process browser-captured camera frame for live face recognition",
)
@router.post(
    "/process-frame",
    summary="Process browser-captured camera frame for live face recognition",
)
async def process_attendance_frame(
    request: Request,
    session_id: Optional[str] = None,
):
    """Forward browser camera frame to Vision Service for SCRFD + ArcFace inference."""
    body = await request.body()
    content_type = request.headers.get("content-type", "image/jpeg")

    vision_url = os.getenv("VISION_SERVICE_URL", "http://127.0.0.1:8088")
    if os.getenv("APP_ENV") == "production" and "127.0.0.1" in vision_url:
        vision_url = "http://vision-service:8088"

    headers = {"Content-Type": content_type}
    if session_id:
        headers["X-Session-Id"] = session_id

    try:
        import httpx

        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                f"{vision_url.rstrip('/')}/process-frame",
                content=body,
                headers=headers,
                params={"session_id": session_id} if session_id else None,
            )
            return resp.json()
    except Exception as exc:
        logger.warning("Vision service process-frame forward failed: %s", exc)
        return {
            "status": "error",
            "message": f"Vision service unreachable: {exc}",
            "recognized": False,
        }
