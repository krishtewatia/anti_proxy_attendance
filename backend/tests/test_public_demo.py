"""The public demo: one-click demo accounts that only ever see the demo copy of the data."""

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.api.dependencies.rate_limiter import demo_login_rate_limiter
from app.core.config import settings
from app.database import mongodb
from app.database.mongodb import DEMO_PREFIX, init_indexes
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token, decode_access_token
from app.security.passwords import hash_password
from app.services import demo_service

DEMO = "/api/v1/auth/demo"
pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
async def fresh_db(monkeypatch):
    mongodb._client = AsyncMongoMockClient()
    await init_indexes(mongodb.get_database())
    monkeypatch.setattr(settings, "PUBLIC_DEMO_ENABLED", True)
    demo_login_rate_limiter._history.clear()
    yield
    mongodb._client = AsyncMongoMockClient()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _demo_headers(client: AsyncClient, role: str) -> dict[str, str]:
    response = await client.post(DEMO, json={"role": role})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_demo_sign_in_gives_a_demo_token_for_each_role():
    async with _client() as client:
        for role in ("ADMIN", "TEACHER", "STUDENT"):
            response = await client.post(DEMO, json={"role": role})
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["user"]["role"] == role
            assert body["must_change_password"] is False
            assert decode_access_token(body["access_token"])["demo"] is True


async def test_demo_is_off_unless_enabled(monkeypatch):
    async with _client() as client:
        headers = await _demo_headers(client, "ADMIN")
        monkeypatch.setattr(settings, "PUBLIC_DEMO_ENABLED", False)
        assert (await client.get(DEMO)).json() == {"enabled": False}
        assert (await client.post(DEMO, json={"role": "ADMIN"})).status_code == 404
        # A demo token handed out earlier stops working too.
        assert (await client.get("/api/v1/admin/teachers", headers=headers)).status_code == 401


async def test_unknown_role_is_refused():
    async with _client() as client:
        assert (await client.post(DEMO, json={"role": "ROOT"})).status_code == 422


async def test_demo_data_lives_only_in_demo_collections():
    real = mongodb.real_database()
    async with _client() as client:
        await _demo_headers(client, "ADMIN")
    names = await real.list_collection_names()
    assert f"{DEMO_PREFIX}users" in names
    # Nothing was written to the organisation's own collections.
    assert await real["users"].count_documents({}) == 0
    assert await real["org_classes"].count_documents({}) == 0
    assert await real[f"{DEMO_PREFIX}org_classes"].count_documents({}) > 0


async def test_demo_admin_cannot_see_real_accounts_and_real_admin_cannot_see_demo():
    await create_user(
        user_id="real_admin",
        email="admin@niet.co.in",
        password_hash=hash_password("RealAdmin123!"),
        role="ADMIN",
    )
    real_headers = {
        "Authorization": f"Bearer {create_access_token(user_id='real_admin', role='ADMIN')}"
    }
    async with _client() as client:
        demo_headers = await _demo_headers(client, "ADMIN")
        demo_teachers = (await client.get("/api/v1/admin/teachers", headers=demo_headers)).json()
        real_teachers = (await client.get("/api/v1/admin/teachers", headers=real_headers)).json()
    assert [t["email"] for t in demo_teachers] == [demo_service.DEMO_ACCOUNTS["TEACHER"]["email"]]
    assert real_teachers == []


async def test_a_real_account_cannot_be_reached_with_a_demo_token():
    """A demo token naming a real user id finds nobody: users are looked up in the demo copy."""
    await create_user(
        user_id="real_admin",
        email="admin@niet.co.in",
        password_hash=hash_password("RealAdmin123!"),
        role="ADMIN",
    )
    forged = create_access_token(user_id="real_admin", role="ADMIN", demo=True)
    async with _client() as client:
        response = await client.get(
            "/api/v1/admin/teachers", headers={"Authorization": f"Bearer {forged}"}
        )
    assert response.status_code == 401


async def test_demo_accounts_cannot_have_their_password_changed():
    async with _client() as client:
        headers = await _demo_headers(client, "ADMIN")
        response = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "x", "new_password": "NewPassword123!"},
            headers=headers,
        )
        assert response.status_code == 403
        teacher = await mongodb.real_database()[f"{DEMO_PREFIX}users"].find_one({"role": "TEACHER"})
        response = await client.post(
            f"/api/v1/admin/users/{teacher['user_id']}/reset-password",
            json={"password": "NewPassword123!"},
            headers=headers,
        )
        assert response.status_code == 403


async def test_demo_sign_in_is_repeatable_and_restores_deleted_accounts():
    async with _client() as client:
        first = (await client.post(DEMO, json={"role": "TEACHER"})).json()["user"]["user_id"]
        again = (await client.post(DEMO, json={"role": "TEACHER"})).json()["user"]["user_id"]
        assert first == again
        # A visitor deletes the demo student the way an administrator would.
        real = mongodb.real_database()
        email = demo_service.DEMO_ACCOUNTS["STUDENT"]["email"]
        student = await real[f"{DEMO_PREFIX}users"].find_one({"email": email})
        await real[f"{DEMO_PREFIX}users"].delete_one({"user_id": student["user_id"]})
        await real[f"{DEMO_PREFIX}student_profiles"].delete_one({"user_id": student["user_id"]})
        assert (await client.post(DEMO, json={"role": "STUDENT"})).status_code == 200


async def test_demo_teacher_has_classes_and_students_are_enrolled():
    async with _client() as client:
        await _demo_headers(client, "TEACHER")
    real = mongodb.real_database()
    teacher = await real[f"{DEMO_PREFIX}users"].find_one({"role": "TEACHER"})
    taught = await real[f"{DEMO_PREFIX}org_classes"].count_documents(
        {"teacher_ids": teacher["user_id"]}
    )
    assert taught == demo_service.DEMO_TEACHER_CLASSES
    enrolled = await real[f"{DEMO_PREFIX}enrolments"].count_documents({})
    assert enrolled == len(demo_service.DEMO_CLASSMATES) + 1


async def test_reset_drops_only_demo_collections():
    real = mongodb.real_database()
    await real["users"].insert_one({"user_id": "keep_me", "email": "keep@niet.co.in"})
    async with _client() as client:
        await _demo_headers(client, "ADMIN")
    dropped = await demo_service.reset_demo()
    assert dropped > 0
    names = await real.list_collection_names()
    assert not [n for n in names if n.startswith(DEMO_PREFIX)]
    assert await real["users"].find_one({"user_id": "keep_me"})


async def test_site_info_tells_the_landing_page_about_the_demo_and_the_contact(monkeypatch):
    monkeypatch.setattr(settings, "CONTACT_EMAIL", "sales@example.com")
    async with _client() as client:
        assert (await client.get("/api/v1/site")).json() == {
            "demo_enabled": True,
            "contact_email": "sales@example.com",
        }
        monkeypatch.setattr(settings, "PUBLIC_DEMO_ENABLED", False)
        monkeypatch.setattr(settings, "CONTACT_EMAIL", "")
        assert (await client.get("/api/v1/site")).json() == {
            "demo_enabled": False,
            "contact_email": None,
        }
