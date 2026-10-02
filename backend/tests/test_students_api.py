import pytest
from fastapi import status
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.database.mongodb import init_indexes
from app.main import app
from app.security.jwt import create_access_token


@pytest.fixture(autouse=True)
async def setup_test_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await init_indexes(db)
    await db["users"].delete_many({})
    await db["student_profiles"].delete_many({})

    # Prepopulate a test student, teacher, and admin
    await db["users"].insert_many([
        {
            "user_id": "student_user_1",
            "email": "student1@test.edu",
            "hashed_password": "hashed_password",
            "role": "STUDENT",
            "is_active": True,
        },
        {
            "user_id": "student_user_2",
            "email": "student2@test.edu",
            "hashed_password": "hashed_password",
            "role": "STUDENT",
            "is_active": True,
        },
        {
            "user_id": "teacher_user_1",
            "email": "teacher1@test.edu",
            "hashed_password": "hashed_password",
            "role": "TEACHER",
            "is_active": True,
        },
        {
            "user_id": "admin_user_1",
            "email": "admin1@test.edu",
            "hashed_password": "hashed_password",
            "role": "ADMIN",
            "is_active": True,
        },
    ])

    yield

    await db["users"].delete_many({})
    await db["student_profiles"].delete_many({})


@pytest.fixture
def client():
    return TestClient(app)


def auth_header(user_id: str, role: str) -> dict:
    token = create_access_token(user_id=user_id, role=role)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
async def test_get_profile_not_found_initially(client):
    """A student without a profile receives 404 Not Found."""
    headers = auth_header("student_user_1", "STUDENT")
    response = client.get("/api/v1/students/profile", headers=headers)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_student_bind_and_retrieve_profile(client):
    """Student successfully binds CV identity and retrieves own profile."""
    headers = auth_header("student_user_1", "STUDENT")

    # 1. Bind profile
    bind_response = client.post(
        "/api/v1/students/profile",
        json={"identity": "person_01"},
        headers=headers,
    )
    assert bind_response.status_code == status.HTTP_201_CREATED
    data = bind_response.json()
    assert data["user_id"] == "student_user_1"
    assert data["identity"] == "person_01"

    # 2. Retrieve profile
    get_response = client.get("/api/v1/students/profile", headers=headers)
    assert get_response.status_code == status.HTTP_200_OK
    assert get_response.json() == {"user_id": "student_user_1", "identity": "person_01"}

    # 3. Retrieve via alias /api/v1/students/me
    me_response = client.get("/api/v1/students/me", headers=headers)
    assert me_response.status_code == status.HTTP_200_OK
    assert me_response.json() == {"user_id": "student_user_1", "identity": "person_01"}


@pytest.mark.anyio
async def test_student_duplicate_binding_rejected(client):
    """A student cannot bind a second time (409 Conflict)."""
    headers = auth_header("student_user_1", "STUDENT")

    res1 = client.post(
        "/api/v1/students/profile",
        json={"identity": "person_01"},
        headers=headers,
    )
    assert res1.status_code == status.HTTP_201_CREATED

    # Attempting to bind again
    res2 = client.post(
        "/api/v1/students/profile",
        json={"identity": "person_02"},
        headers=headers,
    )
    assert res2.status_code == status.HTTP_409_CONFLICT
    assert "already has a student profile" in res2.json()["detail"]


@pytest.mark.anyio
async def test_identity_uniqueness_between_students(client):
    """A second student cannot claim an identity already bound to another student."""
    headers1 = auth_header("student_user_1", "STUDENT")
    headers2 = auth_header("student_user_2", "STUDENT")

    # Student 1 binds person_01
    res1 = client.post(
        "/api/v1/students/profile",
        json={"identity": "person_01"},
        headers=headers1,
    )
    assert res1.status_code == status.HTTP_201_CREATED

    # Student 2 tries to claim person_01
    res2 = client.post(
        "/api/v1/students/profile",
        json={"identity": "person_01"},
        headers=headers2,
    )
    assert res2.status_code == status.HTTP_409_CONFLICT
    assert "already bound" in res2.json()["detail"]


@pytest.mark.anyio
async def test_teacher_and_admin_cannot_access_student_endpoints(client):
    """Teacher and Admin are forbidden from student profile endpoints (403)."""
    teacher_headers = auth_header("teacher_user_1", "TEACHER")
    admin_headers = auth_header("admin_user_1", "ADMIN")

    # Teacher forbidden
    t_post = client.post(
        "/api/v1/students/profile",
        json={"identity": "person_01"},
        headers=teacher_headers,
    )
    assert t_post.status_code == status.HTTP_403_FORBIDDEN
    t_get = client.get("/api/v1/students/profile", headers=teacher_headers)
    assert t_get.status_code == status.HTTP_403_FORBIDDEN

    # Admin forbidden
    a_post = client.post(
        "/api/v1/students/profile",
        json={"identity": "person_01"},
        headers=admin_headers,
    )
    assert a_post.status_code == status.HTTP_403_FORBIDDEN
    a_get = client.get("/api/v1/students/profile", headers=admin_headers)
    assert a_get.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_unauthenticated_request_rejected(client):
    """Unauthenticated requests are rejected with 401."""
    res_post = client.post("/api/v1/students/profile", json={"identity": "person_01"})
    assert res_post.status_code == status.HTTP_401_UNAUTHORIZED

    res_get = client.get("/api/v1/students/profile")
    assert res_get.status_code == status.HTTP_401_UNAUTHORIZED
