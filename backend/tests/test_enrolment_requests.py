"""Student self-setup and its approval.

A student signs up, signs in at once, chooses section, electives and DLDA
group by code, and sends 2-3 face photos. An administrator approves or
rejects, one by one or in bulk. Until approved the student is on no roster and
their face is not in the gallery. The vision service is stubbed and photos are
placeholder image headers, not pictures of anyone.
"""

from pathlib import Path
import struct
from types import SimpleNamespace

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.core.uploads import enrolment_photo_dir, student_photo_path
from app.database import mongodb
from app.database.mongodb import init_indexes
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from app.seed import pilot_catalog
from app.services import (
    approval_service,
    enrolment_service,
    organisation_service as org,
    student_biometric_service,
    student_deletion,
)
from app.services.registration_rules import CONSENT_NOTICE_VERSION
import base64

PASSWORD = "SetupPass123!"
COHORT = pilot_catalog.COHORT["cohort_id"]
TERM = pilot_catalog.TERM["term_id"]
SHEET = (Path(org.__file__).resolve().parent.parent / "seed" / pilot_catalog.TIMETABLE_FILE).read_text(
    encoding="utf-8-sig"
)
STUDENT = "/api/v1/enrolment"
ADMIN = "/api/v1/admin/enrolment"
CHOICES = {
    "DE-II": {"option": "PA", "group": "G2"},
    "DE-III": {"option": "DP", "group": "DP"},
    "DLDA": {"option": "DLDA", "group": "DL3"},
}


def _photo(label: str) -> str:
    """A PNG header (640x480) followed by a label the vision stub reads."""
    header = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 640, 480)
    return base64.b64encode(header + label.encode()).decode()


def _unit(index: int) -> list[float]:
    vector = [0.0] * 512
    vector[index] = 1.0
    return vector


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Vision:
    """Answers /extract-embedding by the label in the photo bytes."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, content=b"", **kwargs):
        if not url.endswith("/extract-embedding"):
            return _Response({"status": "ok"})
        label = content.split(b"IHDR", 1)[1][8:].decode()
        if label.startswith("noface"):
            return _Response({"status": "no_face", "message": "No face"})
        person = 1 if label.startswith("other") else 0
        box = [300, 200, 340, 240] if label.startswith("small") else [150, 80, 470, 420]
        score = 0.3 if label.startswith("blurry") else 0.92
        return _Response({"status": "ok", "embedding": _unit(person), "det_score": score, "bbox": box})


@pytest.fixture(autouse=True)
async def fresh_db(monkeypatch):
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await init_indexes(db)
    await org.seed_structure(db)
    await org.import_timetable(db, COHORT, SHEET, source_name="ds3.csv", actor_user_id="seed")
    refreshes = []

    async def fake_refresh() -> bool:
        refreshes.append("reload")
        return True

    monkeypatch.setattr(student_deletion, "_refresh_vision_gallery", fake_refresh)
    monkeypatch.setattr(approval_service, "_refresh_vision_gallery", fake_refresh)
    monkeypatch.setattr(student_biometric_service, "httpx", SimpleNamespace(AsyncClient=_Vision))
    yield refreshes
    mongodb._client = AsyncMongoMockClient()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _admin() -> dict[str, str]:
    await create_user(
        user_id="admin_setup", email="admin@niet.co.in", password_hash=hash_password(PASSWORD), role="ADMIN"
    )
    return {"Authorization": f"Bearer {create_access_token(user_id='admin_setup', role='ADMIN')}"}


async def _student(client: AsyncClient, roll: str, email: str) -> tuple[str, dict[str, str]]:
    registered = await client.post(
        "/api/v1/students/register",
        json={"name": f"Student {roll}", "email": email, "password": PASSWORD, "roll_number": roll},
    )
    assert registered.status_code == 201, registered.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return registered.json()["user_id"], {"Authorization": f"Bearer {login.json()['access_token']}"}


def _setup(section="B", choices=None, photos=("a1", "a2"), consent=True) -> dict:
    body = {"cohort_id": COHORT, "section": section, "choices": choices or CHOICES, "photos": [_photo(p) for p in photos]}
    if consent:
        body["consent_version"] = CONSENT_NOTICE_VERSION
    return body


@pytest.mark.anyio
async def test_a_new_student_signs_in_at_once_but_is_not_eligible(service_key_headers):
    admin = await _admin()
    async with _client() as client:
        user_id, student = await _student(client, "2401331540101", "s101@niet.co.in")
        me = await client.get("/api/v1/students/me", headers=student)
        dashboard = await client.get("/api/v1/students/dashboard", headers=student)
        status = (await client.get(f"{STUDENT}/me", headers=student)).json()
        directory = (await client.get("/api/v1/admin/students", headers=admin)).json()
        old_photo_route = await client.post("/api/v1/students/photo", headers=student, json={"photo_base64": _photo("a1")})
        teacher_only = await client.get("/api/v1/teachers/dashboard", headers=student)
    assert me.status_code == 200 and me.json()["roll_number"] == "2401331540101"
    assert me.json()["class_code"] == "" and me.json()["section"] == ""
    assert dashboard.status_code == 200 and dashboard.json()["overall_total"] == 0
    assert status == {"eligible": False, "enrolment": None, "latest_request": None}
    assert user_id not in [s["user_id"] for s in directory]
    assert old_photo_route.status_code == 403 and old_photo_route.json()["detail"]["code"] == "setup_pending"
    assert teacher_only.status_code == 403


@pytest.mark.anyio
async def test_the_options_list_every_section_with_its_core_classes_and_the_group_codes():
    async with _client() as client:
        _, student = await _student(client, "2401331540102", "s102@niet.co.in")
        options = (await client.get(f"{STUDENT}/options", headers=student)).json()
    cohort = options["cohorts"][0]
    assert [s["code"] for s in cohort["sections"]] == ["A", "B", "C", "D"]
    section_b = next(s for s in cohort["sections"] if s["code"] == "B")
    assert all(c["class_id"].startswith(f"{TERM}:{COHORT}:B:") for c in section_b["core_classes"])
    assert "CN" in {c["subject_key"] for c in section_b["core_classes"]}
    sets = {s["set_code"]: s for s in cohort["group_sets"]}
    assert list(sets) == ["DE-II", "DE-III", "DLDA"]
    assert {o["option_code"]: o["groups"] for o in sets["DE-II"]["options"]} == {"PA": ["G1", "G2", "G3"], "AJ": ["AJ"]}
    assert {o["option_code"]: o["groups"] for o in sets["DE-III"]["options"]} == {"PROD": ["G1", "G2", "G3"], "DP": ["DP"]}
    assert sets["DLDA"]["options"][0]["groups"] == ["DL1", "DL2", "DL3", "DL4"]
    # Codes only: no teacher appears anywhere in the options.
    assert "teacher" not in str(options).lower()
    assert {s["name"] for s in options["not_counted"]} >= {"MOOC"} or options["not_counted"]


@pytest.mark.anyio
async def test_choices_must_be_listed_pairs_for_every_set():
    async with _client() as client:
        _, student = await _student(client, "2401331540103", "s103@niet.co.in")
        wrong_pair = await client.post(f"{STUDENT}/requests", headers=student, json=_setup(choices={**CHOICES, "DE-II": {"option": "AJ", "group": "G1"}}))
        missing = await client.post(f"{STUDENT}/requests", headers=student, json=_setup(choices={k: v for k, v in CHOICES.items() if k != "DLDA"}))
        unknown_set = await client.post(f"{STUDENT}/requests", headers=student, json=_setup(choices={**CHOICES, "DE-IX": {"option": "X", "group": "Y"}}))
        bad_section = await client.post(f"{STUDENT}/requests", headers=student, json=_setup(section="Z"))
    assert [r.status_code for r in (wrong_pair, missing, unknown_set, bad_section)] == [400, 400, 400, 400]
    assert "not a DE-II group" in wrong_pair.json()["detail"]
    assert await mongodb.get_database()[enrolment_service.REQUESTS].count_documents({}) == 0


@pytest.mark.anyio
async def test_photos_are_checked_and_need_the_notice():
    async with _client() as client:
        _, student = await _student(client, "2401331540104", "s104@niet.co.in")
        one_photo = await client.post(f"{STUDENT}/requests", headers=student, json=_setup(photos=("a1",)))
        no_notice = await client.post(f"{STUDENT}/requests", headers=student, json=_setup(consent=False))
        bad = await client.post(f"{STUDENT}/requests", headers=student, json=_setup(photos=("a1", "small", "blurry")))
        two_people = await client.post(f"{STUDENT}/requests", headers=student, json=_setup(photos=("a1", "other")))
        no_face = await client.post(f"{STUDENT}/photos/check", headers=student, json={"photo_base64": _photo("noface")})
        good = await client.post(f"{STUDENT}/photos/check", headers=student, json={"photo_base64": _photo("a1")})
    assert (one_photo.status_code, no_notice.status_code, two_people.status_code) == (400, 400, 400)
    assert "notice" in no_notice.json()["detail"]
    assert bad.status_code == 400
    assert [p["ok"] for p in bad.json()["detail"]["photos"]] == [True, False, False]
    assert "same person" in two_people.json()["detail"]
    assert no_face.json()["ok"] is False and good.json() == {**good.json(), "ok": True, "problems": []}
    assert "embedding" not in good.text


@pytest.mark.anyio
async def test_approving_the_first_request_makes_the_student_eligible(fresh_db, service_key_headers):
    admin = await _admin()
    db = mongodb.get_database()
    async with _client() as client:
        user_id, student = await _student(client, "2401331540105", "s105@niet.co.in")
        sent = await client.post(f"{STUDENT}/requests", headers=student, json=_setup(photos=("a1", "a2", "a3")))
        assert sent.status_code == 201, sent.text
        request_id = sent.json()["request_id"]
        identity = (await db["student_profiles"].find_one({"user_id": user_id}))["identity"]

        twice = await client.post(f"{STUDENT}/requests", headers=student, json=_setup())
        gallery_before = (await client.get("/api/v1/attendance/vision-gallery", headers=service_key_headers)).json()
        listed = (await client.get(f"{ADMIN}/requests", headers=admin)).json()
        photo = await client.get(listed["requests"][0]["photo_urls"][2], headers=admin)
        photo_as_student = await client.get(listed["requests"][0]["photo_urls"][0], headers=student)

        approved = await client.post(f"{ADMIN}/requests/{request_id}/approve", headers=admin)
        gallery_after = (await client.get("/api/v1/attendance/vision-gallery", headers=service_key_headers)).json()
        status = (await client.get(f"{STUDENT}/me", headers=student)).json()
        directory = (await client.get("/api/v1/admin/students", headers=admin)).json()

    assert twice.status_code == 409
    assert identity not in [g["identity"] for g in gallery_before["gallery"]]
    assert listed["counts"][0]["years"][0]["sections"] == {"B": 1}
    request = listed["requests"][0]
    assert (request["roll_number"], request["section"], request["choices"]) == ("2401331540105", "B", CHOICES)
    assert photo.status_code == 200 and photo.headers["cache-control"] == "private, no-store"
    assert photo_as_student.status_code == 403

    assert approved.status_code == 200 and fresh_db == ["reload"]
    assert identity in [g["identity"] for g in gallery_after["gallery"]]
    assert status["eligible"] is True and status["latest_request"]["status"] == "APPROVED"
    enrolment = status["enrolment"]
    assert enrolment["section"] == "B" and enrolment["choices"] == CHOICES
    assert f"{TERM}:{COHORT}:B:CN" in enrolment["class_ids"]
    assert f"{TERM}:{COHORT}:DE-II/PA/G2:PRED" in enrolment["class_ids"]
    assert f"{TERM}:{COHORT}:DLDA/DLDA/DL3:DLDA" in enrolment["class_ids"]
    assert not any(":A:" in c or "/G1:" in c for c in enrolment["class_ids"])
    template = await db["biometric_profiles"].find_one({"identity": identity})
    assert template["review_status"] == "ACTIVE" and template["sample_count"] == 3
    assert student_photo_path(identity).is_file() and not enrolment_photo_dir(request_id).exists()
    assert user_id in [s["user_id"] for s in directory]
    assert (await db["users"].find_one({"user_id": user_id}))["status"] == "APPROVED"
    assert await db["audit_events"].count_documents({"action": "ENROLMENT_APPROVED"}) == 1


@pytest.mark.anyio
async def test_a_change_keeps_the_approved_setup_until_it_is_approved():
    admin = await _admin()
    db = mongodb.get_database()
    async with _client() as client:
        user_id, student = await _student(client, "2401331540106", "s106@niet.co.in")
        first = (await client.post(f"{STUDENT}/requests", headers=student, json=_setup())).json()
        await client.post(f"{ADMIN}/requests/{first['request_id']}/approve", headers=admin)
        template_before = (await db["biometric_profiles"].find_one({}))["mean_embedding"]

        change = await client.post(
            f"{STUDENT}/requests", headers=student,
            json={"cohort_id": COHORT, "section": "B", "choices": {**CHOICES, "DLDA": {"option": "DLDA", "group": "DL1"}}},
        )
        while_waiting = (await client.get(f"{STUDENT}/me", headers=student)).json()
        await client.post(f"{ADMIN}/requests/{change.json()['request_id']}/approve", headers=admin)
        after = (await client.get(f"{STUDENT}/me", headers=student)).json()

    assert change.status_code == 201 and change.json()["kind"] == "CHANGE"
    assert while_waiting["enrolment"]["choices"]["DLDA"]["group"] == "DL3"
    assert while_waiting["latest_request"]["status"] == "PENDING" and while_waiting["eligible"] is True
    assert after["enrolment"]["choices"]["DLDA"]["group"] == "DL1"
    # No new photos in the change: the face template is untouched.
    assert (await db["biometric_profiles"].find_one({}))["mean_embedding"] == template_before
    statuses = [r["status"] async for r in db[enrolment_service.REQUESTS].find({"user_id": user_id}).sort("submitted_at", 1)]
    assert statuses == ["SUPERSEDED", "APPROVED"]


@pytest.mark.anyio
async def test_rejecting_keeps_the_account_and_shows_the_reason(fresh_db):
    admin = await _admin()
    db = mongodb.get_database()
    async with _client() as client:
        user_id, student = await _student(client, "2401331540107", "s107@niet.co.in")
        sent = (await client.post(f"{STUDENT}/requests", headers=student, json=_setup())).json()
        no_reason = await client.post(f"{ADMIN}/requests/{sent['request_id']}/reject", headers=admin, json={"reason": " "})
        rejected = await client.post(
            f"{ADMIN}/requests/{sent['request_id']}/reject", headers=admin, json={"reason": "Photo 2 shows two people"}
        )
        status = (await client.get(f"{STUDENT}/me", headers=student)).json()
        again = await client.post(f"{STUDENT}/requests", headers=student, json=_setup())
        withdrawn = await client.delete(f"{STUDENT}/requests/current", headers=student)
        nothing_left = await client.delete(f"{STUDENT}/requests/current", headers=student)
    assert no_reason.status_code == 400 and rejected.status_code == 200
    assert status["latest_request"]["status"] == "REJECTED"
    assert status["latest_request"]["reason"] == "Photo 2 shows two people"
    assert status["eligible"] is False and not enrolment_photo_dir(sent["request_id"]).exists()
    assert await db["users"].find_one({"user_id": user_id}) is not None
    assert again.status_code == 201 and withdrawn.status_code == 200 and nothing_left.status_code == 404
    assert not enrolment_photo_dir(again.json()["request_id"]).exists()
    assert fresh_db == []


@pytest.mark.anyio
async def test_bulk_decisions_by_section_and_by_group(fresh_db):
    admin = await _admin()
    db = mongodb.get_database()
    async with _client() as client:
        ids = {}
        for roll, section, group in (("2401331540111", "A", "G1"), ("2401331540112", "A", "G2"), ("2401331540113", "C", "G1")):
            _, student = await _student(client, roll, f"s{roll[-3:]}@niet.co.in")
            sent = await client.post(
                f"{STUDENT}/requests", headers=student,
                json=_setup(section=section, choices={**CHOICES, "DE-II": {"option": "PA", "group": group}}),
            )
            ids[roll] = sent.json()["request_id"]
        section_a = (await client.get(f"{ADMIN}/requests", headers=admin, params={"section": "A"})).json()
        group_g1 = (await client.get(f"{ADMIN}/requests", headers=admin, params={"set_code": "DE-II", "option": "PA", "group": "G1"})).json()
        approve_a = await client.post(
            f"{ADMIN}/requests/bulk", headers=admin,
            json={"action": "approve", "request_ids": [r["request_id"] for r in section_a["requests"]]},
        )
        reject_without_reason = await client.post(
            f"{ADMIN}/requests/bulk", headers=admin, json={"action": "reject", "request_ids": [ids["2401331540113"]]}
        )
        reject_c = await client.post(
            f"{ADMIN}/requests/bulk", headers=admin,
            json={"action": "reject", "request_ids": [ids["2401331540113"]], "reason": "Wrong section"},
        )
        repeat = await client.post(
            f"{ADMIN}/requests/bulk", headers=admin, json={"action": "approve", "request_ids": [ids["2401331540111"]]}
        )
        teacher_like = await client.post(f"{ADMIN}/requests/bulk", json={"action": "approve", "request_ids": ["x"]})
    assert sorted(r["roll_number"] for r in section_a["requests"]) == ["2401331540111", "2401331540112"]
    assert sorted(r["roll_number"] for r in group_g1["requests"]) == ["2401331540111", "2401331540113"]
    assert approve_a.status_code == 200 and len(approve_a.json()["done"]) == 2
    assert fresh_db == ["reload"]  # one gallery refresh for the whole batch
    assert reject_without_reason.status_code == 400 and reject_c.status_code == 200
    assert repeat.status_code == 409 and teacher_like.status_code == 401
    assert await db["audit_events"].count_documents({"action": "ENROLMENT_APPROVED"}) == 2
    assert await db["audit_events"].count_documents({"action": "ENROLMENT_REJECTED"}) == 1


@pytest.mark.anyio
async def test_a_student_waiting_with_a_request_is_not_purged():
    from datetime import datetime, timedelta, timezone

    db = mongodb.get_database()
    async with _client() as client:
        waiting, student = await _student(client, "2401331540121", "s121@niet.co.in")
        await client.post(f"{STUDENT}/requests", headers=student, json=_setup())
        idle, _ = await _student(client, "2401331540122", "s122@niet.co.in")
    old = datetime.now(timezone.utc) - timedelta(days=30)
    await db["users"].update_many({}, {"$set": {"created_at": old}})
    purged = await approval_service.purge_stale_registrations(db)
    assert purged == [idle]
    assert await db["users"].find_one({"user_id": waiting}) is not None


@pytest.mark.anyio
async def test_pilot_sign_up_takes_no_class_or_photo_and_deleting_removes_the_setup():
    admin = await _admin()
    db = mongodb.get_database()
    async with _client() as client:
        with_photo = await client.post(
            "/api/v1/students/register",
            json={"name": "Photo Student", "email": "p@niet.co.in", "password": PASSWORD, "roll_number": "2401331540131",
                  "photo_base64": _photo("a1"), "consent_version": CONSENT_NOTICE_VERSION},
        )
        user_id, student = await _student(client, "2401331540132", "s132@niet.co.in")
        sent = (await client.post(f"{STUDENT}/requests", headers=student, json=_setup())).json()
        deleted = await client.delete(f"/api/v1/admin/students/{user_id}", headers=admin)
    assert with_photo.status_code == 400 and "setup" in with_photo.json()["detail"]
    assert deleted.status_code == 200
    assert await db[enrolment_service.REQUESTS].count_documents({"user_id": user_id}) == 0
    assert not enrolment_photo_dir(sent["request_id"]).exists()
