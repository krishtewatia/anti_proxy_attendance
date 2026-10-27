"""Students and teachers to and from CSV. Names and numbers are made up."""

import csv
import io

from httpx import ASGITransport, AsyncClient
import pytest

from app.database import mongodb
from app.database.users import create_user
from app.main import app
from app.security.passwords import hash_password
from app.services import enrolment_service as enrolment
from app.services import organisation_service as org
from tests.test_enrolment_requests import COHORT
from tests.test_rounds import fresh_db  # noqa: F401  (same seeded, activated timetable)
from tests.test_teaching import _user

PASSWORD = "Restore123!"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _choices(db) -> dict:
    """The first valid option and group of every group set."""
    out = {}
    async for group_set in db[org.GROUP_SETS].find({"cohort_id": COHORT}):
        option = group_set["options"][0]
        out[group_set["set_code"]] = {"option": option["option_code"], "group": option["groups"][0]}
    return out


async def _people():
    """Two approved students in Section B with a full setup, one approved teacher with a class."""
    db = mongodb.get_database()
    choices = await _choices(db)
    clean, class_ids, cohort = await enrolment.resolve_choices(db, COHORT, "B", choices)
    for n in range(2):
        user_id, identity = f"csv_s{n}", f"stu_csv{n}"
        await create_user(user_id=user_id, email=f"{user_id}@niet.co.in", password_hash=hash_password(PASSWORD), role="STUDENT")
        await db["student_profiles"].insert_one(
            {"user_id": user_id, "identity": identity, "student_id": identity, "name": f"Csv Student {n}",
             "roll_number": f"24013315400{n}", "email": f"{user_id}@niet.co.in"}
        )
        await db["enrolments"].insert_one(
            {"user_id": user_id, "identity": identity, "term_id": cohort["term_id"], "cohort_id": COHORT,
             "section": "B", "choices": clean["groups"], "class_ids": class_ids}
        )
    await db["biometric_profiles"].insert_one({"identity": "stu_csv0", "embedding": [0.0]})
    await create_user(user_id="csv_t", email="csv_t@niet.co.in", password_hash=hash_password(PASSWORD), role="TEACHER")
    await db["teacher_profiles"].insert_one({"user_id": "csv_t", "name": "Csv Teacher", "department": "CSE-DS"})
    cls = await db[org.CLASSES].find_one({"audience.section": "B"})
    await db[org.CLASSES].update_one({"class_id": cls["class_id"]}, {"$addToSet": {"teacher_ids": "csv_t"}})
    return db, class_ids, cls["class_id"]


async def _wipe(db, user_ids: list[str]) -> None:
    await db["users"].delete_many({"user_id": {"$in": user_ids}})
    for name in ("student_profiles", "enrolments", "teacher_profiles"):
        await db[name].delete_many({"user_id": {"$in": user_ids}})
    await db[org.CLASSES].update_many({}, {"$pull": {"teacher_ids": {"$in": user_ids}}})


@pytest.mark.anyio
async def test_students_and_teachers_come_back_from_their_csv_and_sign_in_as_before():
    db, class_ids, teacher_class = await _people()
    admin = await _user("admin_csv", "ADMIN")
    async with _client() as client:
        students_csv = (await client.get("/api/v1/admin/registry/students.csv", headers=admin)).text
        teachers_csv = (await client.get("/api/v1/admin/registry/teachers.csv", headers=admin)).text
        await _wipe(db, ["csv_s0", "csv_s1", "csv_t"])
        check = (await client.post("/api/v1/admin/registry/students/import", headers=admin, content=students_csv.encode())).json()
        nothing_yet = await db["users"].count_documents({"user_id": {"$in": ["csv_s0", "csv_s1"]}})
        done = (await client.post("/api/v1/admin/registry/students/import?apply=true", headers=admin, content=students_csv.encode())).json()
        teachers = (await client.post("/api/v1/admin/registry/teachers/import?apply=true", headers=admin, content=teachers_csv.encode())).json()
        again = (await client.post("/api/v1/admin/registry/students/import", headers=admin, content=students_csv.encode())).json()
        student_login = await client.post("/api/v1/auth/login", json={"email": "csv_s1@niet.co.in", "password": PASSWORD})
        teacher_login = await client.post("/api/v1/auth/login", json={"email": "csv_t@niet.co.in", "password": PASSWORD})

    rows = list(csv.DictReader(io.StringIO(students_csv)))
    assert {r["user_id"] for r in rows} == {"csv_s0", "csv_s1"}
    assert all(r["password_hash"].startswith("$2") and r["section"] == "B" for r in rows)
    assert not any("embedding" in key or "template" in key for key in rows[0])  # no face data
    assert check["to_create"] == 2 and check["errors"] == [] and nothing_yet == 0  # a check changes nothing
    assert done["created"] == 2 and teachers["created"] == 1
    assert again["to_create"] == 0 and again["existing"] == 2  # never created twice
    restored = await db["enrolments"].find_one({"user_id": "csv_s0"})
    assert sorted(restored["class_ids"]) == sorted(class_ids) and restored["identity"] == "stu_csv0"
    assert (await db["student_profiles"].find_one({"user_id": "csv_s0"}))["has_biometric"] is True
    assert (await db["student_profiles"].find_one({"user_id": "csv_s1"}))["has_biometric"] is False
    assert "csv_t" in (await db[org.CLASSES].find_one({"class_id": teacher_class}))["teacher_ids"]
    assert student_login.status_code == 200 and teacher_login.status_code == 200
    assert await db["audit_events"].count_documents({"action": "PEOPLE_CSV_IMPORTED"}) == 2


@pytest.mark.anyio
async def test_a_file_with_errors_is_reported_by_line_and_not_loaded():
    db, _, _ = await _people()
    admin = await _user("admin_csv2", "ADMIN")
    header = "user_id,identity,roll_number,name,email,status,cohort_id,section,DE-II,DE-III,DLDA,password_hash\n"
    bad = header + "\n".join([
        f"new1,stu_new1,2401331599901,New One,new1@niet.co.in,APPROVED,{COHORT},Z,,,,",  # no section Z
        "new2,stu_new2,12ab,New Two,new2@niet.co.in,APPROVED,,,,,,not-a-hash",  # bad roll number and hash
        "new3,stu_csv0,2401331599903,New Three,new3@niet.co.in,APPROVED,,,,,,",  # identity taken
        "new4,stu_new4,2401331599904,New Four,new1@niet.co.in,APPROVED,,,,,,",  # email twice in the file
    ])
    async with _client() as client:
        check = (await client.post("/api/v1/admin/registry/students/import", headers=admin, content=bad.encode())).json()
        refused = await client.post("/api/v1/admin/registry/students/import?apply=true", headers=admin, content=bad.encode())
        wrong_columns = await client.post("/api/v1/admin/registry/teachers/import", headers=admin, content=b"a,b\n1,2\n")
        teacher_bad = await client.post(
            "/api/v1/admin/registry/teachers/import", headers=admin,
            content=b"user_id,name,email,department,status,class_ids,password_hash\nt9,Tee Nine,t9@niet.co.in,CSE,APPROVED,NOPE,\n",
        )
    by_line = {e["line"]: " ".join(e["errors"]) for e in check["errors"]}
    assert "section" in by_line[2].lower()
    assert "roll_number" in by_line[3] and "bcrypt" in by_line[3]
    assert "identity belongs to another account" in by_line[4]
    assert "email appears twice" in by_line[5]
    assert refused.status_code == 409 and await db["users"].count_documents({"user_id": {"$regex": "^new"}}) == 0
    assert wrong_columns.status_code == 400 and "Missing columns" in wrong_columns.json()["detail"]
    assert "unknown class: NOPE" in teacher_bad.json()["errors"][0]["errors"][0]


@pytest.mark.anyio
async def test_only_an_administrator_may_download_or_load():
    await _people()
    teacher = await _user("t_csv_other", "TEACHER")
    async with _client() as client:
        download = await client.get("/api/v1/admin/registry/students.csv", headers=teacher)
        load = await client.post("/api/v1/admin/registry/teachers/import", headers=teacher, content=b"x")
        anonymous = await client.get("/api/v1/admin/registry/teachers.csv")
    assert download.status_code == 403 and load.status_code == 403 and anonymous.status_code == 401
