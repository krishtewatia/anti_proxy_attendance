"""Access control on GET /api/v1/students/{student_id}/photo.

A profile photo is biometric data. Allowed: the student themself, admins, and
teachers who teach that student (assigned class, or a roster of one of their
own sessions). No token is 401; everyone else is 403.

Also guards the wider surface: every route must require authentication unless
it is on a short explicit list, and no JSON response may carry a photo or an
embedding to a role that should not have it.
"""

from datetime import datetime, timezone

from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.core.uploads import student_photo_path
from app.database import mongodb
from app.database.mongodb import init_indexes
from app.database.users import create_user
from app.main import app
from tests.conftest import assign_teacher_classes
from app.security.jwt import create_access_token
from app.security.passwords import hash_password

PHOTO_BYTES = b"placeholder photo bytes, not an image of anyone"
STUDENT_ID = "PHOTO001"
OTHER_STUDENT_ID = "PHOTO002"
PHOTO_URL = f"/api/v1/students/{STUDENT_ID}/photo"


@pytest.fixture(autouse=True)
async def seeded():
    """Two students in class DS-B, each with a stored photo."""
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await init_indexes(db)
    for student_id, user_id in ((STUDENT_ID, "user_photo_1"), (OTHER_STUDENT_ID, "user_photo_2")):
        await create_user(
            user_id=user_id,
            email=f"{student_id.lower()}@photo.test",
            password_hash=hash_password("Password123!"),
            role="STUDENT",
        )
        await db["student_profiles"].insert_one(
            {
                "user_id": user_id,
                "identity": student_id,
                "student_id": student_id,
                "name": f"Student {student_id}",
                "class_code": "DS-B",
                "has_biometric": True,
            }
        )
        path = student_photo_path(student_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PHOTO_BYTES + student_id.encode())
    yield
    mongodb._client = AsyncMongoMockClient()


async def _user(user_id: str, role: str) -> dict[str, str]:
    await create_user(
        user_id=user_id,
        email=f"{user_id}@photo.test",
        password_hash=hash_password("Password123!"),
        role=role,
    )
    return _token(user_id, role)


def _token(user_id: str, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id=user_id, role=role)}"}


async def _session(session_id: str, owner: str, roster: list[str]) -> None:
    db = mongodb.get_database()
    now = datetime.now(timezone.utc)
    await db["sessions"].insert_one(
        {
            "session_id": session_id,
            "course_name": "Photo access",
            "classroom_id": "ROOM_101",
            "start_time": now,
            "end_time": now,
            "required_presence_percentage": 100.0,
            "status": "ACTIVE",
            "created_by": owner,
        }
    )
    await db["session_rosters"].insert_one({"session_id": session_id, "identities": roster})


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ------------------------------------------------------------------------------
# No token
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_no_token_is_401():
    async with _client() as client:
        response = await client.get(PHOTO_URL)
    assert response.status_code == 401
    assert PHOTO_BYTES not in response.content


@pytest.mark.anyio
@pytest.mark.parametrize("header", ["Bearer not-a-real-token", "Basic dXNlcjpwYXNz", "Bearer "])
async def test_invalid_token_is_401(header):
    async with _client() as client:
        response = await client.get(PHOTO_URL, headers={"Authorization": header})
    assert response.status_code == 401


@pytest.mark.anyio
async def test_no_token_is_401_for_a_student_that_does_not_exist_too():
    async with _client() as client:
        response = await client.get("/api/v1/students/NOSUCH999/photo")
    assert response.status_code == 401


# ------------------------------------------------------------------------------
# Student
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_student_can_view_their_own_photo():
    async with _client() as client:
        response = await client.get(PHOTO_URL, headers=_token("user_photo_1", "STUDENT"))
    assert response.status_code == 200
    assert response.content == PHOTO_BYTES + STUDENT_ID.encode()
    assert response.headers["content-type"] == "image/jpeg"


@pytest.mark.anyio
async def test_student_cannot_view_another_students_photo():
    async with _client() as client:
        response = await client.get(PHOTO_URL, headers=_token("user_photo_2", "STUDENT"))
    assert response.status_code == 403
    assert PHOTO_BYTES not in response.content


@pytest.mark.anyio
async def test_student_without_a_profile_cannot_view_anyones_photo():
    headers = await _user("user_no_profile", "STUDENT")
    async with _client() as client:
        response = await client.get(PHOTO_URL, headers=headers)
    assert response.status_code == 403


# ------------------------------------------------------------------------------
# Admin
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_can_view_any_students_photo():
    headers = await _user("admin_photo", "ADMIN")
    async with _client() as client:
        first = await client.get(PHOTO_URL, headers=headers)
        second = await client.get(f"/api/v1/students/{OTHER_STUDENT_ID}/photo", headers=headers)
    assert first.status_code == 200 and first.content == PHOTO_BYTES + STUDENT_ID.encode()
    assert second.status_code == 200 and second.content == PHOTO_BYTES + OTHER_STUDENT_ID.encode()


@pytest.mark.anyio
async def test_admin_gets_404_for_a_student_with_no_photo():
    headers = await _user("admin_photo", "ADMIN")
    async with _client() as client:
        response = await client.get("/api/v1/students/NOSUCH999/photo", headers=headers)
    assert response.status_code == 404


# ------------------------------------------------------------------------------
# Teacher
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_teacher_with_the_student_on_a_session_roster_can_view_the_photo():
    headers = await _user("teacher_roster", "TEACHER")
    await _session("sess_photo_1", "teacher_roster", [STUDENT_ID])

    async with _client() as client:
        allowed = await client.get(PHOTO_URL, headers=headers)
        other = await client.get(f"/api/v1/students/{OTHER_STUDENT_ID}/photo", headers=headers)

    assert allowed.status_code == 200
    assert allowed.content == PHOTO_BYTES + STUDENT_ID.encode()
    # Only the students on the roster, not the whole class
    assert other.status_code == 403


@pytest.mark.anyio
async def test_teacher_assigned_to_the_students_class_can_view_the_photo():
    headers = await _user("teacher_assigned", "TEACHER")
    await mongodb.get_database()["teacher_profiles"].insert_one(
        {"user_id": "teacher_assigned", "teacher_id": "T-1", "assigned_classes": ["ds-b"]}
    )

    async with _client() as client:
        response = await client.get(PHOTO_URL, headers=headers)

    assert response.status_code == 200


@pytest.mark.anyio
async def test_teacher_assigned_to_a_different_class_cannot_view_the_photo():
    headers = await _user("teacher_other_class", "TEACHER")
    await mongodb.get_database()["teacher_profiles"].insert_one(
        {"user_id": "teacher_other_class", "teacher_id": "T-2", "assigned_classes": ["CS-A"]}
    )

    async with _client() as client:
        response = await client.get(PHOTO_URL, headers=headers)

    assert response.status_code == 403
    assert PHOTO_BYTES not in response.content


@pytest.mark.anyio
async def test_teacher_with_no_connection_to_the_student_cannot_view_the_photo():
    headers = await _user("teacher_unrelated", "TEACHER")
    async with _client() as client:
        response = await client.get(PHOTO_URL, headers=headers)
    assert response.status_code == 403


@pytest.mark.anyio
async def test_another_teachers_roster_does_not_grant_access():
    await _user("teacher_owner", "TEACHER")
    headers = await _user("teacher_outsider", "TEACHER")
    await _session("sess_photo_2", "teacher_owner", [STUDENT_ID])

    async with _client() as client:
        response = await client.get(PHOTO_URL, headers=headers)

    assert response.status_code == 403


@pytest.mark.anyio
async def test_teacher_whose_roster_holds_only_other_students_cannot_view_the_photo():
    headers = await _user("teacher_other_roster", "TEACHER")
    await _session("sess_photo_3", "teacher_other_roster", [OTHER_STUDENT_ID])

    async with _client() as client:
        response = await client.get(PHOTO_URL, headers=headers)

    assert response.status_code == 403


# ------------------------------------------------------------------------------
# No enumeration, no shared caching
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_refused_request_does_not_reveal_whether_the_student_exists():
    teacher = await _user("teacher_probe", "TEACHER")
    async with _client() as client:
        existing = await client.get(PHOTO_URL, headers=teacher)
        missing = await client.get("/api/v1/students/NOSUCH999/photo", headers=teacher)
        own_view = await client.get("/api/v1/students/NOSUCH999/photo", headers=_token("user_photo_2", "STUDENT"))

    assert existing.status_code == missing.status_code == own_view.status_code == 403
    assert existing.json() == missing.json()


@pytest.mark.anyio
async def test_photo_is_never_publicly_cacheable():
    async with _client() as client:
        response = await client.get(PHOTO_URL, headers=_token("user_photo_1", "STUDENT"))

    cache_control = response.headers["cache-control"]
    assert "public" not in cache_control
    assert "private" in cache_control and "no-store" in cache_control
    assert "authorization" in response.headers["vary"].lower()


# ------------------------------------------------------------------------------
# The wider surface
# ------------------------------------------------------------------------------

# Routes that are meant to work without any credential.
PUBLIC_ROUTES = {
    ("GET", "/"),
    ("GET", "/health"),
    ("GET", "/ready"),
    ("GET", "/api/v1/health"),
    ("POST", "/auth/login"),
    ("POST", "/auth/register"),
    ("POST", "/api/v1/students/register"),
    ("POST", "/api/v1/teachers/register"),
    # The registration form lists the active classes before anyone has an account.
    ("GET", "/api/v1/academic/public/classes"),
}
# get_authenticated_user is the token check itself; get_current_user builds on it.
AUTH_DEPENDENCIES = {
    "get_authenticated_user",
    "get_current_user",
    "require_service_key",
    "require_camera_auth",
}


def _api_routes(routes):
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _api_routes(route.original_router.routes)
        elif hasattr(route, "routes"):
            yield from _api_routes(route.routes)


def _dependency_names(dependant, found=None) -> set[str]:
    found = set() if found is None else found
    for dependency in dependant.dependencies:
        found.add(getattr(dependency.call, "__name__", type(dependency.call).__name__))
        _dependency_names(dependency, found)
    return found


@pytest.mark.anyio
async def test_every_route_requires_authentication_unless_explicitly_public():
    routes = list(_api_routes(app.routes))
    assert len(routes) > 50, "route discovery found too few routes to be trusted"

    unauthenticated = set()
    for route in routes:
        if not (_dependency_names(route.dependant) & AUTH_DEPENDENCIES):
            for method in route.methods:
                unauthenticated.add((method, route.path))

    assert unauthenticated == PUBLIC_ROUTES, (
        f"unexpectedly unauthenticated: {sorted(unauthenticated - PUBLIC_ROUTES)}; "
        f"listed as public but not found: {sorted(PUBLIC_ROUTES - unauthenticated)}"
    )
    assert ("GET", "/api/v1/students/{student_id}/photo") not in unauthenticated


@pytest.mark.anyio
async def test_no_static_file_mount_serves_uploads():
    mounted = [getattr(r, "path", "") for r in app.routes if type(r).__name__ == "Mount"]
    assert mounted == []


def _contains_biometric_field(value) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"photo_base64", "embedding", "mean_embedding", "embeddings", "gallery"} and item:
                return True
            if _contains_biometric_field(item):
                return True
    elif isinstance(value, list):
        return any(_contains_biometric_field(item) for item in value)
    return False


@pytest.mark.anyio
async def test_listing_routes_do_not_return_photos_or_embeddings():
    """Directories and profiles return a photo URL at most, never the image or the vector."""
    db = mongodb.get_database()
    await db["student_profiles"].update_many({}, {"$set": {"photo_base64": "cGhvdG8="}})
    await db["biometric_profiles"].insert_one(
        {
            "identity": STUDENT_ID,
            "mean_embedding": [0.1] * 512,
            "sample_count": 1,
            "quality_score": 0.9,
            "enrolled_by": "self",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
    )
    admin = await _user("admin_listing", "ADMIN")
    teacher = await _user("teacher_listing", "TEACHER")
    await assign_teacher_classes("teacher_listing", ("DS-B",))
    student = _token("user_photo_1", "STUDENT")

    checks = [
        ("/api/v1/students/me", student),
        ("/api/v1/students/profile", student),
        ("/api/v1/students/dashboard", student),
        # The class list is for administrators and that class's teachers only
        # (a student gets 403: see test_catalog_access_rules.py).
        ("/api/v1/academic/classes/DS-B/students", admin),
        ("/api/v1/academic/classes/DS-B/students", teacher),
        ("/api/v1/students/directory", teacher),
        ("/api/v1/enrollment", teacher),
        ("/api/v1/admin/students", admin),
        ("/api/v1/admin/users", admin),
    ]
    async with _client() as client:
        for path, headers in checks:
            response = await client.get(path, headers=headers)
            assert response.status_code == 200, (path, response.status_code)
            assert not _contains_biometric_field(response.json()), f"{path} returns biometric data"


@pytest.mark.anyio
async def test_embeddings_are_only_served_to_an_admin_or_the_internal_service(service_key_headers):
    teacher = await _user("teacher_embed", "TEACHER")
    admin = await _user("admin_embed", "ADMIN")
    student = _token("user_photo_1", "STUDENT")

    async with _client() as client:
        for headers in ({}, student, teacher):
            gallery = await client.get("/api/v1/enrollment/gallery", headers=headers)
            assert gallery.status_code in (401, 403)
        assert (await client.get("/api/v1/enrollment/gallery", headers=admin)).status_code == 200

        for headers in ({}, student, teacher, admin):
            internal = await client.get("/api/v1/attendance/vision-gallery", headers=headers)
            assert internal.status_code == 401
        allowed = await client.get("/api/v1/attendance/vision-gallery", headers=service_key_headers)
        assert allowed.status_code == 200
