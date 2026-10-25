"""The pilot organisation model: structure, catalog, classes and timetable versions.

Uses the real CSE-DS 3rd-year Semester V timetable bundled in app/seed.
"""

from datetime import date
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.database import mongodb
from app.database.mongodb import init_indexes
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from app.seed import pilot_catalog
from app.services import organisation_service as org

COHORT = pilot_catalog.COHORT["cohort_id"]
TERM = pilot_catalog.TERM["term_id"]
SHEET = (Path(org.__file__).resolve().parent.parent / "seed" / pilot_catalog.TIMETABLE_FILE).read_text(
    encoding="utf-8-sig"
)
HEADER = ",".join(org.TIMETABLE_COLUMNS)


@pytest.fixture(autouse=True)
async def fresh_db():
    mongodb._client = AsyncMongoMockClient()
    await init_indexes(mongodb.get_database())
    yield
    mongodb._client = AsyncMongoMockClient()


def _db():
    return mongodb.get_database()


async def _seeded():
    db = _db()
    await org.seed_structure(db)
    return db


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _token(user_id: str, role: str) -> dict[str, str]:
    await create_user(
        user_id=user_id, email=f"{user_id}@org.test", password_hash=hash_password("OrgPass123!"), role=role
    )
    return {"Authorization": f"Bearer {create_access_token(user_id=user_id, role=role)}"}


# ------------------------------------------------------------------------------
# Structure and catalog
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_the_structure_is_branch_year_section_with_two_kinds_of_group_sets():
    db = await _seeded()
    tree = await org.structure(db)
    (branch,) = tree["branches"]
    (cohort,) = branch["cohorts"]
    assert branch["code"] == "CSE-DS"
    assert (cohort["year"], cohort["semester"], cohort["term_id"]) == (3, "V", TERM)
    assert cohort["sections"] == ["A", "B", "C", "D"]
    assert [s["set_code"] for s in cohort["elective_sets"]] == ["DE-II", "DE-III"]
    assert [s["set_code"] for s in cohort["workshop_sets"]] == ["DLDA"]


@pytest.mark.anyio
async def test_seeding_twice_changes_nothing_and_keeps_dates_the_admin_set():
    db = await _seeded()
    await db[org.TERMS].update_one({"term_id": TERM}, {"$set": {"start_date": "2026-07-20"}})
    counts = {c: await db[c].count_documents({}) for c in (org.TERMS, org.SECTIONS, org.SUBJECTS, org.GROUP_SETS)}
    await org.seed_structure(db)
    assert {c: await db[c].count_documents({}) for c in counts} == counts
    assert (await db[org.TERMS].find_one({"term_id": TERM}))["start_date"] == "2026-07-20"


@pytest.mark.anyio
async def test_the_catalog_uses_erp_codes_and_flags_the_uncertain_ones():
    db = await _seeded()
    subjects = {s["key"]: s async for s in db[org.SUBJECTS].find({})}
    assert subjects["CN_LAB"]["code"] == "BCSE0552A"
    assert subjects["CN_LAB"]["code_status"] == "MISMATCH" and "BCSE0552B" in subjects["CN_LAB"]["code_note"]
    assert {k for k, s in subjects.items() if s["code_status"] == "INCOMPLETE"} == {"AJAVA", "DP", "AJAVA_LAB"}
    # Outside this system: listed, never counted.
    assert {k for k, s in subjects.items() if not s["tracked"]} == {"PPE", "MOOC"}
    assert subjects["PPE"]["code"] == "BVAC0551"
    # RM Lab slots belong to the Research Methodology subject.
    assert "RM_LAB" in subjects["RM"]["short_names"]


@pytest.mark.anyio
async def test_only_listed_option_and_group_pairs_are_valid():
    db = await _seeded()
    sets = {s["set_code"]: s async for s in db[org.GROUP_SETS].find({})}
    assert org.valid_group_choice(sets["DE-II"], "PA", "G2")
    assert org.valid_group_choice(sets["DE-II"], "AJ", "AJ")
    assert not org.valid_group_choice(sets["DE-II"], "AJ", "G1")
    assert not org.valid_group_choice(sets["DE-II"], "PA", "AJ")
    assert org.valid_group_choice(sets["DE-III"], "DP", "DP")
    assert not org.valid_group_choice(sets["DE-III"], "PROD", "DP")
    assert org.valid_group_choice(sets["DLDA"], "DLDA", "DL4")
    # Workshop groups are not elective groups.
    assert not org.valid_group_choice(sets["DE-II"], "PA", "DL1")


# ------------------------------------------------------------------------------
# Importing the real timetable
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_the_real_timetable_imports_without_errors():
    db = await _seeded()
    report = (await org.plan_timetable_import(db, COHORT, SHEET)).report()
    assert report["errors"] == []
    assert (report["rows"], report["slots"]) == (92, 92)
    assert (report["classes"], report["section_classes"], report["group_classes"]) == (42, 26, 16)
    assert report["flag_counts"] == {"CONFIRM": 17, "INCOMPLETE_CODE": 7, "CODE_MISMATCH": 8, "NO_ROOM": 2}


@pytest.mark.anyio
async def test_year_wide_rows_become_group_classes_shared_by_every_section():
    db = await _seeded()
    plan = await org.plan_timetable_import(db, COHORT, SHEET)
    groups = {c["class_id"] for c in plan.classes.values() if c["audience"]["kind"] == "GROUP"}
    assert f"{TERM}:{COHORT}:DE-II/PA/G1:PRED" in groups
    assert f"{TERM}:{COHORT}:DE-II/PA/G1:PRED_LAB" in groups
    assert f"{TERM}:{COHORT}:DE-II/AJ/AJ:AJAVA_LAB" in groups
    assert f"{TERM}:{COHORT}:DE-III/DP/DP:DP" in groups
    assert f"{TERM}:{COHORT}:DLDA/DLDA/DL3:DLDA" in groups
    # Predictive Analytics G1 and Product Analytics G1 are different groups.
    assert f"{TERM}:{COHORT}:DE-III/PROD/G1:PROD" in groups
    assert not any(":A:" in c or ":B:" in c for c in groups)


@pytest.mark.anyio
async def test_section_rows_become_section_classes_and_rm_lab_counts_as_rm():
    db = await _seeded()
    plan = await org.plan_timetable_import(db, COHORT, SHEET)
    section_b = sorted(c["subject_key"] for c in plan.classes.values() if c["audience"].get("section") == "B")
    assert section_b == ["CN", "CN_LAB", "DCC", "DCC_LAB", "DT", "INTERN", "RM"]
    # Sections C and D have no DevOps lab slot in the sheet.
    for section in ("C", "D"):
        assert "DCC_LAB" not in {c["subject_key"] for c in plan.classes.values() if c["audience"].get("section") == section}


@pytest.mark.anyio
async def test_rows_whose_note_says_confirm_are_imported_and_flagged():
    db = await _seeded()
    plan = await org.plan_timetable_import(db, COHORT, SHEET)
    confirm_rows = sorted(s["row"] for s in plan.slots if any(f["kind"] == "CONFIRM" for f in s["flags"]))
    assert confirm_rows == [13, 17, 40, 41, 47, 48, 59, 60, 62, 63, 74, 75, 88, 90, 91, 92, 93]
    row_88 = next(s for s in plan.slots if s["row"] == 88)
    assert row_88["subject_key"] == "DCC" and "confirm subject" in row_88["flags"][0]["text"]


@pytest.mark.anyio
async def test_double_periods_are_kept():
    db = await _seeded()
    plan = await org.plan_timetable_import(db, COHORT, SHEET)
    dlda = [s for s in plan.slots if s["subject_key"] == "DLDA"]
    assert len(dlda) == 4 and all(s["periods"] == 2 for s in dlda)
    single_labs = [s["row"] for s in plan.slots if s["subject_key"] == "DCC_LAB" and s["periods"] == 1]
    assert single_labs == [52, 57]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "row, message",
    [
        ("B,,SUN,09:10,10:00,1,CN,Computer Networks,B310,", "unknown day"),
        ("B,,MON,10:00,09:10,1,CN,Computer Networks,B310,", "not a valid range"),
        ("B,,MON,09:10,10:00,4,CN,Computer Networks,B310,", "periods must be"),
        ("B,,MON,09:10,10:00,1,XYZ,Unknown,B310,", "not in the catalog"),
        ("B,,MON,09:10,10:00,1,PPE,Professional Practice,B310,", "not tracked"),
        ("E,,MON,09:10,10:00,1,CN,Computer Networks,B310,", "does not exist"),
        ("B,G1,MON,09:10,10:00,1,CN,Computer Networks,B310,", "group column empty"),
        ("B,,MON,09:10,10:00,1,PRED,Predictive Analytics,B310,", "year-wide groups"),
        ("ALL,G1,MON,09:10,10:00,1,CN,Computer Networks,B310,", "not a year-wide group subject"),
        ("ALL,AJ,MON,09:10,10:00,1,PRED,Predictive Analytics,B310,", "not a group of"),
        ("ALL,DL1,MON,09:10,10:00,1,PROD,Product Analytics,B310,", "not a group of"),
    ],
)
async def test_bad_rows_are_errors_with_their_row_number(row, message):
    db = await _seeded()
    report = (await org.plan_timetable_import(db, COHORT, f"{HEADER}\n{row}\n")).report()
    assert len(report["errors"]) == 1
    assert report["errors"][0]["row"] == 2 and message in report["errors"][0]["message"]


@pytest.mark.anyio
async def test_overlaps_for_the_same_audience_are_errors_and_section_group_clashes_are_flagged():
    db = await _seeded()
    sheet = "\n".join(
        [
            HEADER,
            "B,,MON,09:10,10:50,2,CN_LAB,CN Lab,B310,",
            "B,,MON,10:00,10:50,1,CN,Computer Networks,B310,",
            "ALL,G1,MON,10:00,10:50,1,PRED,Predictive Analytics,E203,",
            "ALL,G2,MON,10:00,10:50,1,PRED,Predictive Analytics,E204,",
        ]
    )
    plan = await org.plan_timetable_import(db, COHORT, sheet)
    assert [e["row"] for e in plan.errors] == [3]
    flagged = {s["row"]: [f["kind"] for f in s["flags"]] for s in plan.slots}
    assert "CLASH" in flagged[4] and "CLASH" in flagged[2]
    # Two groups of the same set at the same time is normal.
    assert not any("row 5" in f["text"] for s in plan.slots if s["row"] == 4 for f in s["flags"])


@pytest.mark.anyio
async def test_a_sheet_without_the_expected_columns_is_refused():
    db = await _seeded()
    with pytest.raises(org.OrganisationError, match="missing the column"):
        await org.plan_timetable_import(db, COHORT, "scope,day\nB,MON\n")


# ------------------------------------------------------------------------------
# Versions
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_an_import_with_errors_stores_nothing():
    db = await _seeded()
    with pytest.raises(org.OrganisationError) as raised:
        await org.import_timetable(
            db, COHORT, f"{HEADER}\nB,,SUN,09:10,10:00,1,CN,CN,B310,\n", source_name="x", actor_user_id="a"
        )
    assert raised.value.status_code == 422
    assert await db[org.VERSIONS].count_documents({}) == 0
    assert await db[org.CLASSES].count_documents({}) == 0


@pytest.mark.anyio
async def test_classes_have_no_teachers_and_survive_a_second_version():
    db = await _seeded()
    first = await org.import_timetable(db, COHORT, SHEET, source_name="v1.csv", actor_user_id="a")
    assert first["status"] == "DRAFT" and first["slots"] == 92 and first["flagged_slots"] == 32
    assert await db[org.CLASSES].count_documents({}) == 42
    assert await db[org.CLASSES].count_documents({"teacher_ids": {"$ne": []}}) == 0
    await db[org.CLASSES].update_one(
        {"class_id": f"{TERM}:{COHORT}:B:CN"}, {"$set": {"teacher_ids": ["teacher_x"]}}
    )
    await org.import_timetable(db, COHORT, SHEET, source_name="v2.csv", actor_user_id="a")
    assert await db[org.CLASSES].count_documents({}) == 42
    kept = await db[org.CLASSES].find_one({"class_id": f"{TERM}:{COHORT}:B:CN"})
    assert kept["teacher_ids"] == ["teacher_x"]
    assert await db[org.SLOTS].count_documents({}) == 184


@pytest.mark.anyio
async def test_a_later_version_never_changes_the_timetable_of_earlier_dates():
    db = await _seeded()
    first = await org.import_timetable(db, COHORT, SHEET, source_name="v1.csv", actor_user_id="a")
    second = await org.import_timetable(db, COHORT, SHEET, source_name="v2.csv", actor_user_id="a")
    assert await org.version_in_force(db, COHORT, date(2026, 11, 2)) is None  # nothing active yet
    await org.activate_version(db, first["version_id"], date(2026, 11, 2), actor_user_id="a")
    await org.activate_version(db, second["version_id"], date(2026, 12, 1), actor_user_id="a")

    assert (await org.version_in_force(db, COHORT, date(2026, 11, 30)))["version_id"] == first["version_id"]
    assert (await org.version_in_force(db, COHORT, date(2026, 12, 1)))["version_id"] == second["version_id"]
    assert await org.version_in_force(db, COHORT, date(2026, 11, 1)) is None


@pytest.mark.anyio
async def test_activation_rules():
    db = await _seeded()
    first = await org.import_timetable(db, COHORT, SHEET, source_name="v1.csv", actor_user_id="a")
    second = await org.import_timetable(db, COHORT, SHEET, source_name="v2.csv", actor_user_id="a")
    await org.activate_version(db, first["version_id"], date(2026, 11, 2), actor_user_id="a")
    with pytest.raises(org.OrganisationError, match="only a draft"):
        await org.activate_version(db, first["version_id"], date(2026, 12, 1), actor_user_id="a")
    # Not on or before the date of the version already in force.
    with pytest.raises(org.OrganisationError, match="later effective date"):
        await org.activate_version(db, second["version_id"], date(2026, 11, 2), actor_user_id="a")
    with pytest.raises(org.OrganisationError, match="not found"):
        await org.activate_version(db, "ttv_missing", date(2026, 12, 1), actor_user_id="a")


# ------------------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_the_admin_routes_end_to_end():
    admin = await _token("admin_org", "ADMIN")
    async with _client() as client:
        seeded = await client.post("/api/v1/admin/org/seed-pilot", headers=admin)
        assert seeded.status_code == 200, seeded.text

        tree = (await client.get("/api/v1/admin/org/structure", headers=admin)).json()
        assert tree["branches"][0]["cohorts"][0]["sections"] == ["A", "B", "C", "D"]

        dry = await client.post(
            "/api/v1/admin/org/timetable/import",
            params={"cohort_id": COHORT},
            content=SHEET.encode("utf-8"),
            headers={**admin, "Content-Type": "text/csv"},
        )
        assert dry.status_code == 200 and dry.json()["dry_run"] is True and dry.json()["classes"] == 42
        assert await _db()[org.VERSIONS].count_documents({}) == 0

        stored = await client.post(
            "/api/v1/admin/org/timetable/import",
            params={"cohort_id": COHORT, "dry_run": "false", "source_name": "ds3.csv"},
            content=SHEET.encode("utf-8"),
            headers={**admin, "Content-Type": "text/csv"},
        )
        assert stored.status_code == 200, stored.text
        version_id = stored.json()["version_id"]

        flagged = (
            await client.get(
                f"/api/v1/admin/org/timetable/versions/{version_id}/slots",
                params={"flagged_only": "true", "section": "B"},
                headers=admin,
            )
        ).json()
        assert [s["row"] for s in flagged] == [53, 54, 58, 59, 60, 62, 63]

        classes = (await client.get("/api/v1/admin/org/classes", params={"set_code": "DLDA"}, headers=admin)).json()
        assert [c["audience"]["group_code"] for c in classes] == ["DL1", "DL2", "DL3", "DL4"]

        activated = await client.post(
            f"/api/v1/admin/org/timetable/versions/{version_id}/activate",
            json={"effective_from": "2026-11-02"},
            headers=admin,
        )
        assert activated.status_code == 200 and activated.json()["status"] == "ACTIVE"

        bad = await client.post(
            "/api/v1/admin/org/timetable/import",
            params={"cohort_id": COHORT, "dry_run": "false"},
            content=f"{HEADER}\nB,,SUN,09:10,10:00,1,CN,CN,B310,\n".encode(),
            headers={**admin, "Content-Type": "text/csv"},
        )
        assert bad.status_code == 422 and bad.json()["detail"]["errors"][0]["row"] == 2

    actions = {doc["action"] async for doc in _db()["audit_events"].find({})}
    assert {"ORGANISATION_SEEDED", "TIMETABLE_IMPORTED", "TIMETABLE_ACTIVATED"} <= actions


@pytest.mark.anyio
async def test_only_administrators_reach_the_organisation_routes():
    teacher = await _token("teacher_org", "TEACHER")
    student = await _token("student_org", "STUDENT")
    async with _client() as client:
        for headers in ({}, teacher, student):
            for method, path in (
                ("POST", "/api/v1/admin/org/seed-pilot"),
                ("GET", "/api/v1/admin/org/structure"),
                ("GET", "/api/v1/admin/org/subjects"),
                ("GET", "/api/v1/admin/org/classes"),
                ("GET", "/api/v1/admin/org/timetable/versions"),
            ):
                response = await client.request(method, path, headers=headers)
                assert response.status_code in (401, 403), (method, path, response.status_code)
