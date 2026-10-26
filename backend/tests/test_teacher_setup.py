"""Teachers choose their own subjects and sections; an administrator approves.

Names are made up.
"""

from datetime import timedelta

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.database import mongodb
from app.database.mongodb import init_indexes
from app.main import app
from app.services import organisation_service as org
from tests.test_enrolment_requests import COHORT, SHEET
from tests.test_teaching import DAYS, MONDAY, _user

BASE = "/api/v1/teachers/setup"
ADMIN = "/api/v1/admin/teacher-requests"


@pytest.fixture(autouse=True)
async def fresh_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await init_indexes(db)
    await org.seed_structure(db)
    version = await org.import_timetable(db, COHORT, SHEET, source_name="ds3.csv", actor_user_id="seed")
    await org.activate_version(db, version["version_id"], MONDAY, actor_user_id="seed")
    yield
    mongodb._client = AsyncMongoMockClient()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _class_ids(options: dict, subject_key: str, labels: set[str]) -> list[str]:
    subject = next(s for s in options["cohorts"][0]["subjects"] if s["subject_key"] == subject_key)
    return [t["class_id"] for t in subject["targets"] if t["label"] in labels]


@pytest.mark.anyio
async def test_a_waiting_teacher_chooses_subjects_and_sections_and_nothing_else():
    teacher = await _user("t_wait", "TEACHER", status="PENDING")
    async with _client() as client:
        options = (await client.get(f"{BASE}/options", headers=teacher)).json()
        cn = next(s for s in options["cohorts"][0]["subjects"] if s["subject_key"] == "CN")
        pred = next(s for s in options["cohorts"][0]["subjects"] if s["subject_key"] == "PRED")
        wanted = _class_ids(options, "CN", {"Section A", "Section B"}) + _class_ids(options, "PRED", {"DE-II PA G1"})
        empty = await client.post(f"{BASE}/requests", headers=teacher, json={"class_ids": ["nope"]})
        sent = await client.post(f"{BASE}/requests", headers=teacher, json={"class_ids": wanted})
        twice = await client.post(f"{BASE}/requests", headers=teacher, json={"class_ids": wanted})
        status = (await client.get(f"{BASE}/me", headers=teacher)).json()
        still_refused = await client.get("/api/v1/teachers/dashboard", headers=teacher)
    assert [t["label"] for t in cn["targets"]] == ["Section A", "Section B", "Section C", "Section D"]
    assert {t["label"] for t in pred["targets"]} == {"DE-II PA G1", "DE-II PA G2", "DE-II PA G3"}
    assert len(wanted) == 3
    assert empty.status_code == 404 and sent.status_code == 201 and twice.status_code == 409
    assert status["approved"] is False and status["classes"] == [] and status["latest_request"]["status"] == "PENDING"
    assert still_refused.status_code == 403 and still_refused.json()["detail"]["code"] == "teacher_pending"


@pytest.mark.anyio
async def test_approving_gives_the_classes_and_the_timetable():
    admin = await _user("admin_s", "ADMIN")
    teacher = await _user("t_new", "TEACHER", status="PENDING")
    db = mongodb.get_database()
    async with _client() as client:
        options = (await client.get(f"{BASE}/options", headers=teacher)).json()
        wanted = _class_ids(options, "CN", {"Section B"})
        await client.post(f"{BASE}/requests", headers=teacher, json={"class_ids": wanted})
        listed = (await client.get(ADMIN, headers=admin)).json()["requests"]
        approved = await client.post(f"{ADMIN}/{listed[0]['request_id']}/approve", headers=admin, json={})
        status = (await client.get(f"{BASE}/me", headers=teacher)).json()
        dashboard = await client.get("/api/v1/teachers/dashboard", headers=teacher)
        slot = await db[org.SLOTS].find_one({"class_id": wanted[0]})
        day = MONDAY + timedelta(days=DAYS.index(slot["day"]))
        started = await client.post("/api/v1/teachers/sessions/from-slot", headers=teacher, json={"slot_id": slot["slot_id"], "date": day.isoformat()})
        counts = (await client.get("/api/v1/admin/approvals/count", headers=admin)).json()
    assert listed[0]["classes"][0]["target"] == "Section B" and listed[0]["change"] is False
    assert approved.status_code == 200 and approved.json()["adjusted"] is False
    assert status["approved"] is True and [c["class_id"] for c in status["classes"]] == wanted
    assert dashboard.status_code == 200 and started.status_code == 200
    assert counts["teacher_requests"] == 0
    assert await db["audit_events"].count_documents({"action": "TEACHER_CLASSES_APPROVED"}) == 1


@pytest.mark.anyio
async def test_adjust_reject_and_a_change_that_waits():
    admin = await _user("admin_s", "ADMIN")
    teacher = await _user("t_adj", "TEACHER", status="PENDING")
    db = mongodb.get_database()
    async with _client() as client:
        options = (await client.get(f"{BASE}/options", headers=teacher)).json()
        cn_a = _class_ids(options, "CN", {"Section A"})
        cn_b = _class_ids(options, "CN", {"Section B"})
        await client.post(f"{BASE}/requests", headers=teacher, json={"class_ids": cn_a + cn_b})
        rid = (await client.get(ADMIN, headers=admin)).json()["requests"][0]["request_id"]
        adjusted = await client.post(f"{ADMIN}/{rid}/approve", headers=admin, json={"class_ids": cn_a})
        # A change: the approved classes stay until it is decided.
        await client.post(f"{BASE}/requests", headers=teacher, json={"class_ids": cn_b})
        while_waiting = (await client.get(f"{BASE}/me", headers=teacher)).json()
        change = (await client.get(ADMIN, headers=admin)).json()["requests"][0]
        no_reason = await client.post(f"{ADMIN}/{change['request_id']}/reject", headers=admin, json={"reason": " "})
        rejected = await client.post(f"{ADMIN}/{change['request_id']}/reject", headers=admin, json={"reason": "You teach Section A only"})
        after = (await client.get(f"{BASE}/me", headers=teacher)).json()
        withdraw_nothing = await client.delete(f"{BASE}/requests/current", headers=teacher)
        as_teacher = await client.get(ADMIN, headers=teacher)
    assert adjusted.json()["adjusted"] is True
    assert [c["class_id"] for c in while_waiting["classes"]] == cn_a and change["change"] is True
    assert no_reason.status_code == 400 and rejected.status_code == 200
    assert after["latest_request"]["status"] == "REJECTED" and after["latest_request"]["reason"] == "You teach Section A only"
    assert [c["class_id"] for c in after["classes"]] == cn_a
    assert withdraw_nothing.status_code == 404 and as_teacher.status_code == 403
    assert (await db["users"].find_one({"user_id": "t_adj"}))["status"] == "APPROVED"
