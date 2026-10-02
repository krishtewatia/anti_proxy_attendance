import pytest

from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.database.mongodb import get_database
from app.database.users import create_user, get_user_by_email
from app.schemas.auth import UserCreate
from app.security.jwt import decode_access_token
from app.security.passwords import hash_password, verify_password
from app.services.auth_service import (
    AuthenticationError,
    DuplicateUserError,
    authenticate_user,
    register_user,
)


@pytest.fixture(autouse=True)
async def clean_users_collection():
    mongodb._client = AsyncMongoMockClient()
    db = get_database()
    await db["users"].delete_many({})
    yield
    await db["users"].delete_many({})


@pytest.mark.anyio
async def test_register_teacher_success():
    req = UserCreate(
        email="Teacher.One@example.com",
        password="securePassword123!",
        role="TEACHER",
    )
    user = await register_user(req)

    assert user.email == "teacher.one@example.com"
    assert user.role == "TEACHER"
    assert user.is_active is True
    assert user.user_id.startswith("user_")
    assert not hasattr(user, "password_hash")


@pytest.mark.anyio
async def test_register_student_success():
    req = UserCreate(
        email="Student.One@example.com",
        password="securePassword123!",
        role="STUDENT",
    )
    user = await register_user(req)

    assert user.email == "student.one@example.com"
    assert user.role == "STUDENT"
    assert user.is_active is True


@pytest.mark.anyio
async def test_registration_stores_lowercase_email_and_bcrypt_hash():
    req = UserCreate(
        email="UpperCase.User@Example.COM",
        password="passwordToHash456",
        role="TEACHER",
    )
    await register_user(req)

    stored = await get_user_by_email("uppercase.user@example.com")
    assert stored is not None
    assert stored["email"] == "uppercase.user@example.com"
    assert stored["password_hash"].startswith("$2b$")
    assert verify_password("passwordToHash456", stored["password_hash"]) is True


@pytest.mark.anyio
async def test_duplicate_email_registration_rejected():
    req = UserCreate(
        email="duplicate@example.com",
        password="password12345",
        role="STUDENT",
    )
    await register_user(req)

    with pytest.raises(DuplicateUserError, match="A user with this email already exists"):
        await register_user(req)


@pytest.mark.anyio
async def test_authenticate_user_success():
    req = UserCreate(
        email="auth.user@example.com",
        password="correctPassword789",
        role="TEACHER",
    )
    registered = await register_user(req)

    token_res = await authenticate_user(
        email="AUTH.USER@example.com",
        password="correctPassword789",
    )

    assert token_res.token_type == "bearer"
    assert token_res.user.user_id == registered.user_id
    assert token_res.user.email == "auth.user@example.com"
    assert token_res.user.role == "TEACHER"

    claims = decode_access_token(token_res.access_token)
    assert claims["sub"] == registered.user_id
    assert claims["role"] == "TEACHER"


@pytest.mark.anyio
async def test_authenticate_user_wrong_password_rejected():
    req = UserCreate(
        email="wrongpass@example.com",
        password="correctPassword123",
        role="STUDENT",
    )
    await register_user(req)

    with pytest.raises(AuthenticationError, match="Invalid email or password"):
        await authenticate_user(
            email="wrongpass@example.com",
            password="incorrectPassword",
        )


@pytest.mark.anyio
async def test_authenticate_user_unknown_email_rejected():
    with pytest.raises(AuthenticationError, match="Invalid email or password"):
        await authenticate_user(
            email="nonexistent@example.com",
            password="somePassword123",
        )


@pytest.mark.anyio
async def test_authenticate_inactive_user_rejected():
    db = get_database()
    pw_hash = hash_password("validPassword123")
    await create_user(
        user_id="user_inactive_001",
        email="inactive@example.com",
        password_hash=pw_hash,
        role="STUDENT",
    )
    # Explicitly set is_active to False
    await db["users"].update_one(
        {"email": "inactive@example.com"},
        {"$set": {"is_active": False}},
    )

    with pytest.raises(AuthenticationError, match="Invalid email or password"):
        await authenticate_user(
            email="inactive@example.com",
            password="validPassword123",
        )
