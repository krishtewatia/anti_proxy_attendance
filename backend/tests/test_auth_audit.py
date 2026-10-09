from unittest.mock import patch
import pytest
from mongomock_motor import AsyncMongoMockClient

from app.database import mongodb
from app.database.audit import AUDIT_EVENTS_COLLECTION, ensure_audit_indexes
from app.database.audit import get_audit_events
from app.schemas.auth import UserCreate
from app.services import auth_service
from app.services.auth_service import AuthenticationError, DuplicateUserError
from tests.conftest import approve_account


@pytest.fixture
async def setup_test_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await db["users"].delete_many({})
    await db[AUDIT_EVENTS_COLLECTION].delete_many({})
    await ensure_audit_indexes(db)
    yield
    await db["users"].delete_many({})
    await db[AUDIT_EVENTS_COLLECTION].delete_many({})


# ------------------------------------------------------------------------------
# 1. USER_REGISTERED Audit Integration Tests
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_teacher_registration_records_audit_event(setup_test_db):
    user_req = UserCreate(
        email="professor.turing@university.edu",
        password="ValidPassword123!",
        role="TEACHER",
    )
    user = await auth_service.register_user(user_req)

    # Check audit record in MongoDB
    events = await get_audit_events(resource_type="USER", resource_id=user.user_id)
    assert len(events) == 1

    ev = events[0]
    assert ev["audit_id"].startswith("audit_")
    assert ev["actor_user_id"] == user.user_id
    assert ev["actor_role"] == "TEACHER"
    assert ev["action"] == "USER_REGISTERED"
    assert ev["resource_type"] == "USER"
    assert ev["resource_id"] == user.user_id
    assert ev["metadata"] == {"status": "PENDING"}


@pytest.mark.anyio
async def test_student_registration_records_audit_event(setup_test_db):
    user_req = UserCreate(
        email="alice.student@university.edu",
        password="ValidPassword123!",
        role="STUDENT",
    )
    user = await auth_service.register_user(user_req)

    events = await get_audit_events(resource_type="USER", resource_id=user.user_id)
    assert len(events) == 1

    ev = events[0]
    assert ev["actor_user_id"] == user.user_id
    assert ev["actor_role"] == "STUDENT"
    assert ev["action"] == "USER_REGISTERED"
    assert ev["metadata"] == {"status": "PENDING"}


@pytest.mark.anyio
async def test_failed_registration_does_not_create_audit_event(setup_test_db):
    user_req = UserCreate(
        email="duplicate@university.edu",
        password="ValidPassword123!",
        role="TEACHER",
    )
    await auth_service.register_user(user_req)

    # Second attempt with same email must fail
    with pytest.raises(DuplicateUserError):
        await auth_service.register_user(user_req)

    # Verify only the first registration has an audit entry
    all_events = await get_audit_events(resource_type="USER")
    assert len(all_events) == 1


# ------------------------------------------------------------------------------
# 2. USER_LOGIN Audit Integration Tests
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_user_login_records_audit_event(setup_test_db):
    email = "charlie@university.edu"
    password = "CorrectPassword123!"

    # 1. Register user
    user = await auth_service.register_user(
        UserCreate(email=email, password=password, role="TEACHER")
    )

    # 2. Login (once an administrator has approved the registration)
    await approve_account(user.user_id)
    token_resp = await auth_service.authenticate_user(email=email, password=password)
    assert token_resp.access_token is not None

    # 3. Verify audit history for this user: USER_REGISTERED -> USER_LOGIN
    events = await get_audit_events(resource_type="USER", resource_id=user.user_id)
    assert len(events) == 2

    assert events[0]["action"] == "USER_REGISTERED"
    assert events[1]["action"] == "USER_LOGIN"
    assert events[1]["actor_user_id"] == user.user_id
    assert events[1]["actor_role"] == "TEACHER"
    assert events[1]["resource_id"] == user.user_id
    assert events[1]["metadata"] == {"email": email}
    assert events[0]["timestamp"] <= events[1]["timestamp"]


@pytest.mark.anyio
async def test_failed_login_does_not_create_login_audit_event(setup_test_db):
    email = "dave@university.edu"
    password = "CorrectPassword123!"

    user = await auth_service.register_user(
        UserCreate(email=email, password=password, role="STUDENT")
    )

    # Attempt login with wrong password
    with pytest.raises(AuthenticationError):
        await auth_service.authenticate_user(email=email, password="WrongPassword999!")

    # Verify only the registration event exists
    events = await get_audit_events(resource_type="USER", resource_id=user.user_id)
    assert len(events) == 1
    assert events[0]["action"] == "USER_REGISTERED"


# ------------------------------------------------------------------------------
# 3. Resilience: Audit Failures Do Not Corrupt Primary Auth Flow
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_audit_failure_does_not_block_registration(setup_test_db):
    with patch(
        "app.services.auth_service.record_audit_event",
        side_effect=RuntimeError("Simulated audit database connection outage"),
    ):
        user = await auth_service.register_user(
            UserCreate(
                email="resilient.reg@university.edu",
                password="SecurePassword123!",
                role="TEACHER",
            )
        )

    # Primary business operation succeeded
    assert user.email == "resilient.reg@university.edu"
    assert user.user_id.startswith("user_")


@pytest.mark.anyio
async def test_audit_failure_does_not_block_login(setup_test_db):
    email = "resilient.login@university.edu"
    password = "SecurePassword123!"

    registered = await auth_service.register_user(
        UserCreate(email=email, password=password, role="STUDENT")
    )
    await approve_account(registered.user_id)

    with patch(
        "app.services.auth_service.record_audit_event",
        side_effect=RuntimeError("Simulated audit database connection outage"),
    ):
        token_resp = await auth_service.authenticate_user(email=email, password=password)

    # Primary business operation succeeded
    assert token_resp.access_token is not None
    assert token_resp.user.email == email
