"""Academic database operations for Branches, Sections, Classes, and Subjects."""

from datetime import datetime, timezone
from typing import Any

from app.database.mongodb import get_database

ACADEMIC_CLASSES_COLLECTION = "academic_classes"
SUBJECTS_COLLECTION = "subjects"

DEFAULT_CLASSES = [
    {
        "class_id": "cls_ds_a",
        "class_code": "DS-A",
        "branch": "Data Science",
        "section": "A",
        "semester": 6,
    },
    {
        "class_id": "cls_ds_b",
        "class_code": "DS-B",
        "branch": "Data Science",
        "section": "B",
        "semester": 6,
    },
    {
        "class_id": "cls_ds_c",
        "class_code": "DS-C",
        "branch": "Data Science",
        "section": "C",
        "semester": 6,
    },
    {
        "class_id": "cls_cs_a",
        "class_code": "CS-A",
        "branch": "Computer Science",
        "section": "A",
        "semester": 6,
    },
    {
        "class_id": "cls_cs_b",
        "class_code": "CS-B",
        "branch": "Computer Science",
        "section": "B",
        "semester": 6,
    },
    {
        "class_id": "cls_cs_c",
        "class_code": "CS-C",
        "branch": "Computer Science",
        "section": "C",
        "semester": 6,
    },
    {
        "class_id": "cls_aiml_a",
        "class_code": "AIML-A",
        "branch": "AI & ML",
        "section": "A",
        "semester": 4,
    },
    {
        "class_id": "cls_aiml_b",
        "class_code": "AIML-B",
        "branch": "AI & ML",
        "section": "B",
        "semester": 4,
    },
]

DEFAULT_SUBJECTS = [
    {
        "subject_id": "sub_ml",
        "name": "Machine Learning",
        "code": "DS-301",
        "branch": "Data Science",
    },
    {"subject_id": "sub_dl", "name": "Deep Learning", "code": "DS-302", "branch": "Data Science"},
    {"subject_id": "sub_dbms", "name": "DBMS", "code": "CS-201", "branch": "Computer Science"},
    {
        "subject_id": "sub_cn",
        "name": "Computer Networks",
        "code": "CS-302",
        "branch": "Computer Science",
    },
    {"subject_id": "sub_devops", "name": "DevOps", "code": "CS-401", "branch": "Computer Science"},
    {
        "subject_id": "sub_dsa",
        "name": "Data Structures",
        "code": "CS-101",
        "branch": "Computer Science",
    },
    {
        "subject_id": "sub_ai",
        "name": "Artificial Intelligence",
        "code": "AI-201",
        "branch": "AI & ML",
    },
]


async def seed_academic_data_if_empty() -> None:
    """Ensure baseline academic classes and subjects exist in MongoDB."""
    db = get_database()
    cls_coll = db[ACADEMIC_CLASSES_COLLECTION]
    sub_coll = db[SUBJECTS_COLLECTION]

    if await cls_coll.count_documents({}) == 0:
        for c in DEFAULT_CLASSES:
            doc = dict(c)
            doc["created_at"] = datetime.now(timezone.utc)
            await cls_coll.update_one({"class_code": c["class_code"]}, {"$set": doc}, upsert=True)

    if await sub_coll.count_documents({}) == 0:
        for s in DEFAULT_SUBJECTS:
            doc = dict(s)
            doc["created_at"] = datetime.now(timezone.utc)
            await sub_coll.update_one({"subject_id": s["subject_id"]}, {"$set": doc}, upsert=True)


async def list_all_classes() -> list[dict[str, Any]]:
    """Retrieve all academic classes."""
    await seed_academic_data_if_empty()
    db = get_database()
    cursor = db[ACADEMIC_CLASSES_COLLECTION].find({}, {"_id": 0}).sort("class_code", 1)
    return await cursor.to_list(length=None)


async def list_all_subjects() -> list[dict[str, Any]]:
    """Retrieve all academic subjects."""
    await seed_academic_data_if_empty()
    db = get_database()
    cursor = db[SUBJECTS_COLLECTION].find({}, {"_id": 0}).sort("name", 1)
    return await cursor.to_list(length=None)


async def get_academic_structure() -> dict[str, Any]:
    """Retrieve structured academic hierarchy (branches with sections, classes, and subjects)."""
    classes = await list_all_classes()
    subjects = await list_all_subjects()

    branch_map: dict[str, set[str]] = {}
    for c in classes:
        b = c["branch"]
        s = c["section"]
        if b not in branch_map:
            branch_map[b] = set()
        branch_map[b].add(s)

    branches_list = [
        {"name": b, "sections": sorted(list(secs))} for b, secs in sorted(branch_map.items())
    ]

    return {
        "branches": branches_list,
        "classes": classes,
        "subjects": subjects,
    }


async def add_academic_class(
    class_code: str, branch: str, section: str, semester: int | None = None
) -> dict[str, Any]:
    """Admin function to create a new academic class."""
    db = get_database()
    doc = {
        "class_id": f"cls_{class_code.lower().replace('-', '_')}",
        "class_code": class_code.upper().strip(),
        "branch": branch.strip(),
        "section": section.upper().strip(),
        "semester": semester,
        "created_at": datetime.now(timezone.utc),
    }
    await db[ACADEMIC_CLASSES_COLLECTION].update_one(
        {"class_code": doc["class_code"]},
        {"$set": doc},
        upsert=True,
    )
    return doc


async def add_subject(
    name: str, code: str | None = None, branch: str | None = None
) -> dict[str, Any]:
    """Admin function to create a new academic course/subject."""
    db = get_database()
    sub_id = f"sub_{name.lower().replace(' ', '_')}"
    doc = {
        "subject_id": sub_id,
        "name": name.strip(),
        "code": code.strip() if code else None,
        "branch": branch.strip() if branch else None,
        "created_at": datetime.now(timezone.utc),
    }
    await db[SUBJECTS_COLLECTION].update_one(
        {"subject_id": sub_id},
        {"$set": doc},
        upsert=True,
    )
    return doc
