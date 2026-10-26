"""The go-live reset: test data goes, administrators, approved teachers and the
timetable stay. Names and numbers are made up."""

import pytest

from app.core.uploads import resolve_uploads_root
from app.core.config import settings
from app.database import mongodb
from app.services import organisation_service as org
from app.services import student_deletion
from app.tools import golive_reset
from tests.test_reports import _client, _setup, _take
from tests.test_rounds import fresh_db  # noqa: F401  (same seeded, activated timetable)
from tests.test_teaching import _user


@pytest.fixture(autouse=True)
def no_vision_calls(monkeypatch):
    async def refreshed() -> bool:
        return True

    monkeypatch.setattr(student_deletion, "_refresh_vision_gallery", refreshed)
    monkeypatch.setattr(golive_reset, "_refresh_vision_gallery", refreshed)


async def _pilot_with_test_data():
    admin, teacher, db, students, cn, slots = await _setup()
    await _user("t_pending", "TEACHER", status="PENDING")
    async with _client() as client:
        await client.put("/api/v1/admin/org/teachers/t_cn/classes", headers=admin, json={"class_ids": [cn["class_id"]]})
        await _take(client, teacher, slots[0], {students[0]: ("PRESENT", "PRESENT"), students[1]: ("ABSENT", "ABSENT")})
    photos = resolve_uploads_root() / "student_profiles"
    photos.mkdir(parents=True, exist_ok=True)
    (photos / f"{students[0]}.jpg").write_bytes(b"not a real photo")
    return db, cn


def _run(*args: str) -> int:
    return golive_reset.main(["--database", settings.DATABASE_NAME, *args])


@pytest.mark.anyio
async def test_a_listing_changes_nothing_and_the_reset_keeps_admins_teachers_and_the_timetable(capsys):
    db, cn = await _pilot_with_test_data()
    found = await golive_reset.plan(db)
    slots_before = await db[org.SLOTS].count_documents({})

    assert found["counts"]["student accounts"] == 2 and found["counts"]["sessions"] == 1
    assert found["counts"]["teacher accounts not approved"] == 1 and found["counts"]["photo files"] == 1
    assert await db["users"].count_documents({"role": "STUDENT"}) == 2  # listing only

    await golive_reset.apply(db, found)

    assert await db["users"].count_documents({"role": "STUDENT"}) == 0
    for name in ("student_profiles", "enrolments", "sessions", "session_rosters", "attendance_records", "biometric_profiles"):
        assert await db[name].count_documents({}) == 0, name
    assert not any((resolve_uploads_root() / "student_profiles").iterdir())
    assert await db["users"].count_documents({"role": "ADMIN"}) == 1
    assert await db["users"].find_one({"user_id": "t_cn", "status": "APPROVED"}) is not None
    assert await db["users"].find_one({"user_id": "t_pending"}) is None
    assert "t_cn" in (await db[org.CLASSES].find_one({"class_id": cn["class_id"]}))["teacher_ids"]
    assert await db[org.SLOTS].count_documents({}) == slots_before > 0
    audit = await db["audit_events"].find_one({"action": "GOLIVE_RESET"})
    assert audit["metadata"]["removed"]["student accounts"] == 2


@pytest.mark.anyio
async def test_the_command_refuses_a_wrong_database_or_count(capsys, monkeypatch):
    db, _ = await _pilot_with_test_data()
    # main() runs its own event loop; give it the same database handle.
    monkeypatch.setattr(mongodb, "get_database", lambda: db)
    total = golive_reset.total(await golive_reset.plan(db))

    wrong_db = golive_reset.main(["--database", "not_this_one", "--apply", "--expect", str(total)])
    wrong_count = await _apply_in_thread("--apply", "--expect", str(total + 1))
    listing = await _apply_in_thread()

    assert wrong_db == 2 and wrong_count == 2 and listing == 0
    assert await db["users"].count_documents({"role": "STUDENT"}) == 2
    assert f"--apply --expect {total}" in capsys.readouterr().out


async def _apply_in_thread(*args: str) -> int:
    import asyncio

    return await asyncio.to_thread(_run, *args)
