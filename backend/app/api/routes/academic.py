"""Academic API routes for classes, subjects, and roster lookups."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies.auth import get_current_user
from app.database.academic import (
    get_academic_structure,
    list_all_classes,
    list_all_subjects,
)
from app.database.student_profiles import get_students_by_class
from app.schemas.academic import AcademicClass, AcademicStructureResponse, Subject

router = APIRouter(
    prefix="/api/v1/academic",
    tags=["academic"],
)


@router.get(
    "/structure",
    response_model=AcademicStructureResponse,
    summary="Get complete academic hierarchy (branches, sections, classes, subjects)",
)
async def get_academic_structure_endpoint(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> AcademicStructureResponse:
    """Returns branches with their sections, standard classes (e.g. DS-B), and available subjects."""
    struct = await get_academic_structure()
    return AcademicStructureResponse(
        branches=struct["branches"],
        classes=[AcademicClass(**c) for c in struct["classes"]],
        subjects=[Subject(**s) for s in struct["subjects"]],
    )


@router.get(
    "/public/classes",
    summary="Classes a new student or teacher can choose when registering (no sign-in)",
)
async def list_public_classes_endpoint() -> list[dict]:
    """The active classes, for the registration form. Codes and names only."""
    return [
        {
            "class_code": c["class_code"],
            "branch": c.get("branch", ""),
            "section": c.get("section", ""),
        }
        for c in await list_all_classes()
    ]


@router.get(
    "/classes",
    response_model=list[AcademicClass],
    summary="List all academic classes",
)
async def list_classes_endpoint(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> list[AcademicClass]:
    classes = await list_all_classes()
    return [AcademicClass(**c) for c in classes]


@router.get(
    "/subjects",
    response_model=list[Subject],
    summary="List all subjects offered",
)
async def list_subjects_endpoint(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> list[Subject]:
    subjects = await list_all_subjects()
    return [Subject(**s) for s in subjects]


@router.get(
    "/classes/{class_code}/students",
    summary="Retrieve all enrolled students belonging to an academic class",
)
async def get_class_roster_endpoint(
    class_code: str,
    current_user: Annotated[dict, Depends(get_current_user)],
) -> list[dict]:
    """Auto-roster lookup: returns all students where class_code matches."""
    students = await get_students_by_class(class_code=class_code)
    return [
        {
            "user_id": s.get("user_id"),
            "identity": s.get("identity") or s.get("student_id"),
            "student_id": s.get("student_id"),
            "name": s.get("name"),
            "roll_number": s.get("roll_number"),
            "branch": s.get("branch"),
            "section": s.get("section"),
            "class_code": s.get("class_code"),
            "has_biometric": s.get("has_biometric", False),
        }
        for s in students
    ]
