import pytest
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.database.mongodb import init_indexes
from app.database.student_profiles import (
    DuplicateStudentProfileRecordError,
    create_student_profile as repo_create_student_profile,
    get_student_profile_by_identity,
    get_student_profile_by_user_id,
)
from app.schemas.student import StudentProfile
from app.services.student_service import (
    DuplicateStudentProfileError,
    StudentAuthorizationError,
    create_student_profile,
    get_student_profile_by_cv_identity,
    get_student_profile_by_user,
)


@pytest.fixture(autouse=True)
async def setup_test_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await init_indexes(db)
    await db["student_profiles"].delete_many({})
    yield
    await db["student_profiles"].delete_many({})


# =========================================================================
# Step 2B.7.5: Database Constraint Tests
# =========================================================================

@pytest.mark.anyio
async def test_database_rejects_duplicate_user_id():
    """Verify MongoDB unique index on user_id rejects duplicates at repository level."""
    # First record succeeds
    await repo_create_student_profile(
        user_id="user_student_1",
        identity="person_01",
    )

    # Second record with same user_id must be rejected
    with pytest.raises(DuplicateStudentProfileRecordError):
        await repo_create_student_profile(
            user_id="user_student_1",
            identity="person_02",
        )


@pytest.mark.anyio
async def test_database_rejects_duplicate_identity():
    """Verify MongoDB unique index on identity rejects duplicates at repository level."""
    # First record succeeds
    await repo_create_student_profile(
        user_id="user_student_1",
        identity="person_01",
    )

    # Second record with same identity but different user_id must be rejected
    with pytest.raises(DuplicateStudentProfileRecordError):
        await repo_create_student_profile(
            user_id="user_student_2",
            identity="person_01",
        )


# =========================================================================
# Step 2B.7.5: Authorization Tests
# =========================================================================

@pytest.mark.anyio
async def test_student_role_allowed_to_create_profile():
    """Authenticated student user is authorized to bind identity profile."""
    student_user = {
        "user_id": "user_student_alice",
        "email": "alice@student.example.com",
        "role": "STUDENT",
        "is_active": True,
    }

    profile = await create_student_profile(
        current_user=student_user,
        identity="person_alice",
    )

    assert isinstance(profile, StudentProfile)
    assert profile.user_id == "user_student_alice"
    assert profile.identity == "person_alice"


@pytest.mark.anyio
async def test_teacher_role_forbidden_from_student_profile():
    """Authenticated teacher user is rejected with StudentAuthorizationError."""
    teacher_user = {
        "user_id": "user_teacher_bob",
        "email": "bob@teacher.example.com",
        "role": "TEACHER",
        "is_active": True,
    }

    with pytest.raises(StudentAuthorizationError, match="STUDENT"):
        await create_student_profile(
            current_user=teacher_user,
            identity="person_bob",
        )


@pytest.mark.anyio
async def test_admin_role_forbidden_from_student_profile():
    """Authenticated admin user is rejected with StudentAuthorizationError."""
    admin_user = {
        "user_id": "user_admin_charlie",
        "email": "charlie@admin.example.com",
        "role": "ADMIN",
        "is_active": True,
    }

    with pytest.raises(StudentAuthorizationError, match="STUDENT"):
        await create_student_profile(
            current_user=admin_user,
            identity="person_charlie",
        )


# =========================================================================
# Step 2B.7.5: Student Identity Uniqueness Tests
# =========================================================================

@pytest.mark.anyio
async def test_student_identity_uniqueness_lifecycle():
    """
    Verify complete lifecycle requirement:
    Student A -> person_01 -> success
    Student A -> person_02 -> rejected
    Student B -> person_01 -> rejected
    """
    student_a = {
        "user_id": "user_student_a",
        "email": "a@student.com",
        "role": "STUDENT",
        "is_active": True,
    }
    student_b = {
        "user_id": "user_student_b",
        "email": "b@student.com",
        "role": "STUDENT",
        "is_active": True,
    }

    # 1. Student A -> person_01 -> success
    profile_a = await create_student_profile(
        current_user=student_a,
        identity="person_01",
    )
    assert profile_a.user_id == "user_student_a"
    assert profile_a.identity == "person_01"

    # 2. Student A -> person_02 -> rejected (user already bound)
    with pytest.raises(DuplicateStudentProfileError, match="already has a student profile"):
        await create_student_profile(
            current_user=student_a,
            identity="person_02",
        )

    # 3. Student B -> person_01 -> rejected (identity already bound to Student A)
    with pytest.raises(DuplicateStudentProfileError, match="already bound"):
        await create_student_profile(
            current_user=student_b,
            identity="person_01",
        )


# =========================================================================
# Retrieval and Lookup Tests
# =========================================================================

@pytest.mark.anyio
async def test_student_profile_lookups():
    """Verify bidirectional lookup by user_id and CV identity."""
    student_user = {
        "user_id": "user_lookup_test",
        "email": "lookup@student.com",
        "role": "STUDENT",
        "is_active": True,
    }

    # Prior to creation, both lookups return None
    assert await get_student_profile_by_user("user_lookup_test") is None
    assert await get_student_profile_by_cv_identity("person_lookup_test") is None

    # Bind profile
    await create_student_profile(
        current_user=student_user,
        identity="person_lookup_test",
    )

    # Look up by user_id
    by_user = await get_student_profile_by_user("user_lookup_test")
    assert by_user is not None
    assert by_user.user_id == "user_lookup_test"
    assert by_user.identity == "person_lookup_test"

    # Look up by CV identity
    by_identity = await get_student_profile_by_cv_identity("person_lookup_test")
    assert by_identity is not None
    assert by_identity.user_id == "user_lookup_test"
    assert by_identity.identity == "person_lookup_test"
