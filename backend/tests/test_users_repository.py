import pytest

from app.database.mongodb import get_database
from app.database.users import (
    create_user,
    get_user_by_email,
    get_user_by_id,
)


@pytest.mark.anyio
async def test_user_repository():
    db = get_database()

    await db["users"].delete_many({})

    created = await create_user(
        user_id="user_001",
        email="Teacher@Example.com",
        password_hash="hashed_password",
        role="TEACHER",
    )

    assert created["user_id"] == "user_001"
    assert created["email"] == "teacher@example.com"
    assert created["password_hash"] == "hashed_password"
    assert created["role"] == "TEACHER"
    assert created["is_active"] is True

    by_email = await get_user_by_email(
        "TEACHER@example.com"
    )

    assert by_email is not None
    assert by_email["user_id"] == "user_001"

    by_id = await get_user_by_id("user_001")

    assert by_id is not None
    assert by_id["email"] == "teacher@example.com"
