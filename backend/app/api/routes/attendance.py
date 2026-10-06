import csv
import io
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.dependencies.auth import get_owned_session, require_teacher
from app.api.dependencies.camera_auth import require_service_key
from app.api.dependencies.rate_limiter import (
    frame_session_rate_limiter,
    frame_teacher_rate_limiter,
)
from app.core.config import settings
from app.database.attendance import (
    get_attendance_by_session,
    upsert_attendance,
)
from app.database.mongodb import get_database
from app.database.session_roster import get_session_roster
from app.schemas.attendance import AttendanceRecord
from app.schemas.attendance_response import (
    AttendanceSessionResponse,
    AttendanceSummaryItem,
)
from app.services.recognition_service import verify_and_mark
from app.services.vision_client import VisionServiceUnavailable, forward_frame_to_vision

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
    summary="Get currently active attendance session metadata (service key required)",
    dependencies=[Depends(require_service_key)],
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
    summary="Biometric gallery for the vision service (service key required)",
    dependencies=[Depends(require_service_key)],
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


def _public_face(face: dict) -> dict:
    """Copy of a vision face result that is safe to return to the browser."""
    return {k: v for k, v in face.items() if k != "recognition"}


@router.post(
    "/{session_id}/process-frame",
    summary="Recognize faces in one camera frame and mark verified students present",
)
async def process_attendance_frame(
    session_id: str,
    request: Request,
    current_user: Annotated[dict, Depends(require_teacher)],
) -> dict:
    """The only way a recognition marks attendance.

    The browser sends a frame with the teacher's JWT. The backend checks
    ownership and that the session is ACTIVE, forwards the frame to the
    internal vision service, verifies each signed recognition result, and
    marks rostered students present. The browser never asserts an identity.
    Frame contents are not stored or logged.
    """
    session = await get_owned_session(session_id, current_user)

    if session.get("status") != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attendance can only be marked while the session is active.",
        )

    await frame_session_rate_limiter.check(f"session:{session_id}")
    await frame_teacher_rate_limiter.check(f"teacher:{current_user['user_id']}")

    declared_length = request.headers.get("content-length")
    if declared_length and declared_length.isdigit():
        if int(declared_length) > settings.FRAME_MAX_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Frame is too large.",
            )
    body = await request.body()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty frame.",
        )
    if len(body) > settings.FRAME_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Frame is too large.",
        )

    content_type = request.headers.get("content-type", "image/jpeg")

    try:
        vision_result = await forward_frame_to_vision(body, content_type, session_id)
    except VisionServiceUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vision service unavailable. Please retry.",
            headers={"Retry-After": "2"},
        )

    db = get_database()
    raw_faces = vision_result.get("faces")
    faces: list[dict] = []

    for raw_face in raw_faces if isinstance(raw_faces, list) else []:
        if not isinstance(raw_face, dict):
            continue
        face = _public_face(raw_face)

        if raw_face.get("status") == "recognized":
            result = await verify_and_mark(db, session, raw_face.get("recognition"))
            face["mark_status"] = result.status
            if result.status == "rejected":
                face["mark_reason"] = result.reason
                if result.reason != "not_on_roster":
                    # An unverifiable result is never shown as a recognized student
                    face["status"] = "unverified"
                    face["identity"] = None
                    face["student_id"] = None
                    face["name"] = "UNKNOWN"
        faces.append(face)

    accepted = [f for f in faces if f.get("mark_status") in {"marked", "already_present"}]
    top = max(accepted, key=lambda f: f.get("similarity") or 0.0) if accepted else None
    primary = top or (faces[0] if faces else None)

    return {
        "status": "ok",
        "session_id": session_id,
        "detected_faces": len(faces),
        "recognized": top is not None,
        "identity": top.get("identity") if top else None,
        "student_name": top.get("name") if top else None,
        "student_id": top.get("student_id") if top else None,
        "similarity": (primary.get("similarity") or 0.0) if primary else 0.0,
        "box": primary.get("bbox") if primary else None,
        "frame_width": vision_result.get("frame_width"),
        "frame_height": vision_result.get("frame_height"),
        "faces": faces,
    }
