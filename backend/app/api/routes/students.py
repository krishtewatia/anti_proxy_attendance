"""Student API routes for Registration, Profile, Biometrics, and Dashboard Analytics."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies.auth import (
    require_student,
    require_teacher_or_admin,
)
from app.database.biometric_profiles import list_all_biometric_profiles
from app.database.mongodb import get_database
from app.database.users import get_all_users
from app.schemas.student import (
    StudentAttendanceDashboardResponse,
    StudentProfile,
    StudentProfileBind,
    StudentProfileResponse,
    StudentRegisterRequest,
)
from app.services.student_biometric_service import extract_and_register_student_photo
from app.services.student_service import (
    DuplicateStudentProfileError,
    StudentAuthorizationError,
    create_student_profile,
    get_student_dashboard,
    get_student_profile_by_user,
    get_student_profile_response,
    register_student_account,
)

router = APIRouter(
    prefix="/api/v1/students",
    tags=["students"],
)


class PhotoUploadRequest(BaseModel):
    photo_base64: str


@router.post(
    "/register",
    response_model=StudentProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Self-service student account registration with academic profile and biometric photo",
)
async def register_student_endpoint(
    payload: StudentRegisterRequest,
) -> StudentProfileResponse:
    """Register student account, assign to academic class (branch/section), and generate face embedding."""
    try:
        profile = await register_student_account(payload, enrolled_by="self")
        return profile
    except DuplicateStudentProfileError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Registration failed: {exc}",
        ) from exc


@router.get(
    "/me",
    response_model=StudentProfileResponse,
    summary="Get current authenticated student's full profile",
)
async def get_my_full_profile_endpoint(
    current_user: Annotated[dict, Depends(require_student)],
) -> StudentProfileResponse:
    """Retrieve personal info, roll number, academic class, and biometric status."""
    profile = await get_student_profile_response(current_user["user_id"])
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student profile not found",
        )
    return profile


@router.get(
    "/dashboard",
    response_model=StudentAttendanceDashboardResponse,
    summary="Student attendance dashboard with overall %, subject breakdown, and history",
)
async def get_student_dashboard_endpoint(
    current_user: Annotated[dict, Depends(require_student)],
) -> StudentAttendanceDashboardResponse:
    """Computes overall attendance %, subject-wise attendance breakdown, and session history."""
    try:
        return await get_student_dashboard(current_user["user_id"])
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/{student_id}/photo",
    summary="Serve student profile photograph",
)
async def get_student_photo_endpoint(student_id: str):
    """Serve student profile photograph from persistent storage or database."""
    import base64
    from fastapi.responses import Response

    from app.core.uploads import student_photo_path

    try:
        file_path = student_photo_path(student_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found")

    if file_path.exists():
        content = file_path.read_bytes()
        return Response(
            content=content,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # Check MongoDB student_profiles collection for photo_base64
    db = get_database()
    doc = await db["student_profiles"].find_one(
        {"$or": [{"student_id": student_id}, {"identity": student_id}]}
    )
    photo_b64 = doc.get("photo_base64") if doc else None
    if not photo_b64:
        bio_doc = await db["biometric_profiles"].find_one({"identity": student_id})
        if bio_doc and bio_doc.get("photo_base64"):
            photo_b64 = bio_doc["photo_base64"]

    if photo_b64:
        raw_b64 = photo_b64.strip()
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]
        try:
            content = base64.b64decode(raw_b64)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(content)
            return Response(
                content=content,
                media_type="image/jpeg",
                headers={"Cache-Control": "public, max-age=86400"},
            )
        except Exception:
            pass

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Student photograph not found"
    )


@router.post(
    "/photo",
    summary="Upload or update student biometric photograph",
)
async def upload_student_photo_endpoint(
    payload: PhotoUploadRequest,
    current_user: Annotated[dict, Depends(require_student)],
) -> dict:
    """Upload photo, run face detection & ArcFace embedding extraction, and update biometric gallery."""
    profile = await get_student_profile_response(current_user["user_id"])
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student profile not found",
        )

    ok, msg = await extract_and_register_student_photo(
        identity=profile.identity,
        photo_base64=payload.photo_base64,
        enrolled_by=current_user["user_id"],
        student_name=profile.name,
        student_id=profile.student_id,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg,
        )

    photo_url = f"/api/v1/students/{profile.student_id}/photo"
    db = get_database()
    await db["student_profiles"].update_one(
        {"user_id": current_user["user_id"]},
        {
            "$set": {
                "photo_base64": payload.photo_base64,
                "photo_url": photo_url,
                "has_biometric": True,
            }
        },
    )

    return {"status": "success", "message": msg, "has_biometric": True, "photo_url": photo_url}


# --- Legacy Endpoints for Backward Compatibility ---


@router.post(
    "/profile",
    response_model=StudentProfile,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@router.post(
    "/bind",
    response_model=StudentProfile,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def bind_student_identity_endpoint(
    payload: StudentProfileBind,
    current_user: Annotated[dict, Depends(require_student)],
) -> StudentProfile:
    """Bind authenticated student account to a CV identity (legacy)."""
    try:
        profile = await create_student_profile(
            current_user=current_user,
            identity=payload.identity,
        )
        return profile
    except DuplicateStudentProfileError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except StudentAuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.get(
    "/profile",
    response_model=StudentProfile,
    include_in_schema=False,
)
async def get_my_student_profile_legacy_endpoint(
    current_user: Annotated[dict, Depends(require_student)],
) -> StudentProfile:
    """Legacy profile endpoint returning {user_id, identity}."""
    profile = await get_student_profile_by_user(current_user["user_id"])
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student profile not found",
        )
    return profile


@router.get(
    "/directory",
    summary="List available students for session rosters",
)
async def get_students_directory(
    current_user: Annotated[dict, Depends(require_teacher_or_admin)],
) -> list[dict]:
    """Returns directory of students with biometric status."""
    student_users = await get_all_users(role="STUDENT")
    bio_profiles = await list_all_biometric_profiles()
    db = get_database()
    student_profiles_cursor = db["student_profiles"].find({}, {"_id": 0})
    student_profiles = await student_profiles_cursor.to_list(length=None)
    profile_map = {p["user_id"]: p for p in student_profiles}
    bio_idents = {b["identity"] for b in bio_profiles}

    candidates: dict[str, dict] = {}
    for u in student_users:
        prof = profile_map.get(u["user_id"], {})
        ident = prof.get("identity") or prof.get("student_id") or u["email"].split("@")[0]
        candidates[ident] = {
            "identity": ident,
            "name": prof.get("name")
            or u.get("name")
            or u["email"].split("@")[0].replace(".", " ").title(),
            "email": u["email"],
            "student_id": prof.get("student_id") or ident,
            "roll_number": prof.get("roll_number", ""),
            "branch": prof.get("branch", ""),
            "section": prof.get("section", ""),
            "class_code": prof.get("class_code", ""),
            "has_biometric": (ident in bio_idents) or prof.get("has_biometric", False),
        }

    for bio in bio_profiles:
        ident = bio["identity"]
        if ident in candidates:
            candidates[ident]["has_biometric"] = True
        else:
            candidates[ident] = {
                "identity": ident,
                "name": ident.replace("_", " ").title(),
                "email": f"{ident}@campus.edu",
                "student_id": ident,
                "roll_number": "",
                "branch": "",
                "section": "",
                "class_code": "",
                "has_biometric": True,
            }

    return sorted(list(candidates.values()), key=lambda x: str(x["name"]))
