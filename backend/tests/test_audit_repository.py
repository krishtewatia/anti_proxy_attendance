from datetime import datetime, timezone
import pytest
from mongomock_motor import AsyncMongoMockClient
from pydantic import ValidationError

from app.database import audit as audit_repo
from app.database import mongodb
from app.schemas.audit import AuditEvent


@pytest.fixture
async def setup_test_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await db[audit_repo.AUDIT_EVENTS_COLLECTION].delete_many({})
    await audit_repo.ensure_audit_indexes(db)
    yield
    await db[audit_repo.AUDIT_EVENTS_COLLECTION].delete_many({})


# ------------------------------------------------------------------------------
# 1. Creation & Retrieval by ID Tests
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_create_and_get_audit_event(setup_test_db):
    event_data = {
        "audit_id": "audit_001",
        "actor_user_id": "teacher_123",
        "actor_role": "TEACHER",
        "action": "SESSION_CREATED",
        "resource_type": "SESSION",
        "resource_id": "session_101",
        "timestamp": datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
        "metadata": {"course_name": "Distributed Systems", "classroom_id": "ROOM_101"},
    }

    created = await audit_repo.create_audit_event(event_data)
    assert created["audit_id"] == "audit_001"
    assert created["action"] == "SESSION_CREATED"

    # Verify retrievable by audit_id
    retrieved = await audit_repo.get_audit_event("audit_001")
    assert retrieved is not None
    assert retrieved["audit_id"] == "audit_001"
    assert retrieved["actor_user_id"] == "teacher_123"
    assert retrieved["actor_role"] == "TEACHER"
    assert retrieved["action"] == "SESSION_CREATED"
    assert retrieved["resource_type"] == "SESSION"
    assert retrieved["resource_id"] == "session_101"
    assert retrieved["metadata"]["course_name"] == "Distributed Systems"


@pytest.mark.anyio
async def test_get_audit_event_nonexistent_returns_none(setup_test_db):
    result = await audit_repo.get_audit_event("nonexistent_audit_id")
    assert result is None


# ------------------------------------------------------------------------------
# 2. Filtering Tests (resource_type, resource_id, both, none)
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_filter_audit_events_by_resource_type(setup_test_db):
    await audit_repo.create_audit_event({
        "audit_id": "audit_sess_1",
        "actor_user_id": "teacher_1",
        "actor_role": "TEACHER",
        "action": "SESSION_CREATED",
        "resource_type": "SESSION",
        "resource_id": "sess_101",
        "timestamp": datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
        "metadata": {},
    })
    await audit_repo.create_audit_event({
        "audit_id": "audit_user_1",
        "actor_user_id": "admin_1",
        "actor_role": "ADMIN",
        "action": "USER_REGISTERED",
        "resource_type": "USER",
        "resource_id": "user_202",
        "timestamp": datetime(2026, 10, 1, 9, 5, tzinfo=timezone.utc),
        "metadata": {},
    })

    session_events = await audit_repo.get_audit_events(resource_type="SESSION")
    assert len(session_events) == 1
    assert session_events[0]["audit_id"] == "audit_sess_1"

    user_events = await audit_repo.get_audit_events(resource_type="USER")
    assert len(user_events) == 1
    assert user_events[0]["audit_id"] == "audit_user_1"


@pytest.mark.anyio
async def test_filter_audit_events_by_resource_id(setup_test_db):
    await audit_repo.create_audit_event({
        "audit_id": "audit_r1",
        "actor_user_id": "teacher_1",
        "actor_role": "TEACHER",
        "action": "SESSION_CREATED",
        "resource_type": "SESSION",
        "resource_id": "sess_A",
        "timestamp": datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
        "metadata": {},
    })
    await audit_repo.create_audit_event({
        "audit_id": "audit_r2",
        "actor_user_id": "teacher_1",
        "actor_role": "TEACHER",
        "action": "SESSION_CREATED",
        "resource_type": "SESSION",
        "resource_id": "sess_B",
        "timestamp": datetime(2026, 10, 1, 9, 10, tzinfo=timezone.utc),
        "metadata": {},
    })

    events_a = await audit_repo.get_audit_events(resource_id="sess_A")
    assert len(events_a) == 1
    assert events_a[0]["audit_id"] == "audit_r1"


@pytest.mark.anyio
async def test_filter_audit_events_by_both_and_unfiltered(setup_test_db):
    await audit_repo.create_audit_event({
        "audit_id": "audit_both_1",
        "actor_user_id": "teacher_1",
        "actor_role": "TEACHER",
        "action": "ROSTER_UPDATED",
        "resource_type": "SESSION_ROSTER",
        "resource_id": "sess_target",
        "timestamp": datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
        "metadata": {},
    })
    await audit_repo.create_audit_event({
        "audit_id": "audit_both_2",
        "actor_user_id": "teacher_1",
        "actor_role": "TEACHER",
        "action": "SESSION_CREATED",
        "resource_type": "SESSION",
        "resource_id": "sess_target",
        "timestamp": datetime(2026, 10, 1, 8, 55, tzinfo=timezone.utc),
        "metadata": {},
    })

    # Filter by both
    roster_events = await audit_repo.get_audit_events(
        resource_type="SESSION_ROSTER", resource_id="sess_target"
    )
    assert len(roster_events) == 1
    assert roster_events[0]["audit_id"] == "audit_both_1"

    # Unfiltered
    all_events = await audit_repo.get_audit_events()
    assert len(all_events) == 2


# ------------------------------------------------------------------------------
# 3. Chronological Ordering Tests
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_chronological_ordering(setup_test_db):
    t1 = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 10, 1, 10, 15, tzinfo=timezone.utc)
    t3 = datetime(2026, 10, 1, 10, 30, tzinfo=timezone.utc)

    # Insert out-of-order: t3, then t1, then t2
    await audit_repo.create_audit_event({
        "audit_id": "audit_order_3",
        "actor_user_id": "user_1",
        "actor_role": "TEACHER",
        "action": "SESSION_UPDATED",
        "resource_type": "SESSION",
        "resource_id": "sess_order",
        "timestamp": t3,
        "metadata": {},
    })
    await audit_repo.create_audit_event({
        "audit_id": "audit_order_1",
        "actor_user_id": "user_1",
        "actor_role": "TEACHER",
        "action": "SESSION_CREATED",
        "resource_type": "SESSION",
        "resource_id": "sess_order",
        "timestamp": t1,
        "metadata": {},
    })
    await audit_repo.create_audit_event({
        "audit_id": "audit_order_2",
        "actor_user_id": "user_1",
        "actor_role": "TEACHER",
        "action": "ROSTER_UPDATED",
        "resource_type": "SESSION",
        "resource_id": "sess_order",
        "timestamp": t2,
        "metadata": {},
    })

    results = await audit_repo.get_audit_events(resource_id="sess_order")
    assert len(results) == 3
    assert [r["audit_id"] for r in results] == [
        "audit_order_1",
        "audit_order_2",
        "audit_order_3",
    ]


# ------------------------------------------------------------------------------
# 4. Multiple Lifecycle Events & Resource Isolation
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_multiple_session_lifecycle_events_in_order(setup_test_db):
    sess_id = "session_lifecycle_demo"

    # 1. SESSION_CREATED (10:00 AM)
    await audit_repo.create_audit_event({
        "audit_id": "ev_001",
        "actor_user_id": "teacher_prof",
        "actor_role": "TEACHER",
        "action": "SESSION_CREATED",
        "resource_type": "SESSION",
        "resource_id": sess_id,
        "timestamp": datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc),
        "metadata": {"course": "OS"},
    })

    # 2. ROSTER_UPDATED (10:05 AM)
    await audit_repo.create_audit_event({
        "audit_id": "ev_002",
        "actor_user_id": "teacher_prof",
        "actor_role": "TEACHER",
        "action": "ROSTER_UPDATED",
        "resource_type": "SESSION",
        "resource_id": sess_id,
        "timestamp": datetime(2026, 10, 1, 10, 5, 0, tzinfo=timezone.utc),
        "metadata": {"count": 2},
    })

    # 3. ATTENDANCE_FINALIZED (11:00 AM)
    await audit_repo.create_audit_event({
        "audit_id": "ev_003",
        "actor_user_id": "teacher_prof",
        "actor_role": "TEACHER",
        "action": "ATTENDANCE_FINALIZED",
        "resource_type": "SESSION",
        "resource_id": sess_id,
        "timestamp": datetime(2026, 10, 1, 11, 0, 0, tzinfo=timezone.utc),
        "metadata": {"present_count": 2},
    })

    events = await audit_repo.get_audit_events(resource_id=sess_id)
    assert len(events) == 3
    assert events[0]["action"] == "SESSION_CREATED"
    assert events[1]["action"] == "ROSTER_UPDATED"
    assert events[2]["action"] == "ATTENDANCE_FINALIZED"
    assert events[0]["timestamp"] < events[1]["timestamp"] < events[2]["timestamp"]


@pytest.mark.anyio
async def test_session_resource_isolation(setup_test_db):
    await audit_repo.create_audit_event({
        "audit_id": "ev_sess_a",
        "actor_user_id": "teacher_a",
        "actor_role": "TEACHER",
        "action": "SESSION_CREATED",
        "resource_type": "SESSION",
        "resource_id": "session_A",
        "timestamp": datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
        "metadata": {},
    })
    await audit_repo.create_audit_event({
        "audit_id": "ev_sess_b",
        "actor_user_id": "teacher_b",
        "actor_role": "TEACHER",
        "action": "SESSION_CREATED",
        "resource_type": "SESSION",
        "resource_id": "session_B",
        "timestamp": datetime(2026, 10, 1, 10, 5, tzinfo=timezone.utc),
        "metadata": {},
    })

    events_a = await audit_repo.get_audit_events(resource_id="session_A")
    assert len(events_a) == 1
    assert events_a[0]["resource_id"] == "session_A"
    assert all(e["resource_id"] != "session_B" for e in events_a)

    events_b = await audit_repo.get_audit_events(resource_id="session_B")
    assert len(events_b) == 1
    assert events_b[0]["resource_id"] == "session_B"
    assert all(e["resource_id"] != "session_A" for e in events_b)


# ------------------------------------------------------------------------------
# 5. Immutability & Index Uniqueness
# ------------------------------------------------------------------------------

def test_immutability_no_update_or_delete_functions():
    """Verify that audit repository strictly enforces append-only immutability."""
    assert not hasattr(audit_repo, "update_audit_event")
    assert not hasattr(audit_repo, "delete_audit_event")
    assert not hasattr(audit_repo, "update_event")
    assert not hasattr(audit_repo, "delete_event")

    # Ensure no function in audit_repo starts with update or delete
    for attr in dir(audit_repo):
        assert not attr.startswith("update_"), f"Unexpected update function found: {attr}"
        assert not attr.startswith("delete_"), f"Unexpected delete function found: {attr}"


@pytest.mark.anyio
async def test_unique_audit_id_index(setup_test_db):
    from pymongo.errors import DuplicateKeyError

    event = {
        "audit_id": "unique_audit_123",
        "actor_user_id": "teacher_1",
        "actor_role": "TEACHER",
        "action": "SESSION_CREATED",
        "resource_type": "SESSION",
        "resource_id": "sess_1",
        "timestamp": datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
        "metadata": {},
    }
    await audit_repo.create_audit_event(event)

    # Inserting same audit_id must fail
    with pytest.raises(DuplicateKeyError):
        await audit_repo.create_audit_event(event)


# ------------------------------------------------------------------------------
# 6. Schema Validation Tests
# ------------------------------------------------------------------------------

def test_audit_event_schema_valid():
    event = AuditEvent(
        audit_id="audit_valid_1",
        actor_user_id="user_admin",
        actor_role="ADMIN",
        action="USER_REGISTERED",
        resource_type="USER",
        resource_id="user_new",
        timestamp=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
    )
    assert event.audit_id == "audit_valid_1"
    assert event.actor_role == "ADMIN"
    assert event.action == "USER_REGISTERED"
    assert event.resource_type == "USER"
    assert event.metadata == {}  # defaults to empty dict


def test_audit_event_schema_system_actor():
    event = AuditEvent(
        audit_id="audit_sys_1",
        actor_user_id="SYSTEM",
        actor_role="SYSTEM",
        action="ATTENDANCE_FINALIZED",
        resource_type="ATTENDANCE",
        resource_id="att_batch_001",
        timestamp=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
        metadata={"automated_job": "nightly_finalizer"},
    )
    assert event.actor_role == "SYSTEM"
    assert event.metadata["automated_job"] == "nightly_finalizer"


def test_audit_event_schema_invalid_actor_role():
    with pytest.raises(ValidationError) as exc:
        AuditEvent(
            audit_id="aud_1",
            actor_user_id="user_1",
            actor_role="SUPERUSER",  # invalid
            action="SESSION_CREATED",
            resource_type="SESSION",
            resource_id="sess_1",
            timestamp=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
        )
    assert "actor_role" in str(exc.value)


def test_audit_event_schema_invalid_action():
    with pytest.raises(ValidationError) as exc:
        AuditEvent(
            audit_id="aud_1",
            actor_user_id="user_1",
            actor_role="TEACHER",
            action="SESSION_DELETED",  # invalid
            resource_type="SESSION",
            resource_id="sess_1",
            timestamp=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
        )
    assert "action" in str(exc.value)


def test_audit_event_schema_invalid_resource_type():
    with pytest.raises(ValidationError) as exc:
        AuditEvent(
            audit_id="aud_1",
            actor_user_id="user_1",
            actor_role="TEACHER",
            action="SESSION_CREATED",
            resource_type="CLASSROOM",  # invalid
            resource_id="sess_1",
            timestamp=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
        )
    assert "resource_type" in str(exc.value)


def test_audit_event_schema_missing_required_fields():
    with pytest.raises(ValidationError) as exc:
        AuditEvent.model_validate({
            "audit_id": "aud_missing",
            # missing actor_user_id, actor_role, action, resource_type, resource_id, timestamp
        })
    errors = str(exc.value)
    assert "actor_user_id" in errors
    assert "actor_role" in errors
    assert "action" in errors
    assert "resource_type" in errors
    assert "resource_id" in errors
    assert "timestamp" in errors


def test_audit_event_schema_extra_fields_forbidden():
    with pytest.raises(ValidationError) as exc:
        AuditEvent(
            audit_id="aud_extra",
            actor_user_id="user_1",
            actor_role="TEACHER",
            action="SESSION_CREATED",
            resource_type="SESSION",
            resource_id="sess_1",
            timestamp=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
            tampered_flag=True,  # extra field forbidden
        )
    assert "extra_forbidden" in str(exc.value) or "Extra inputs are not permitted" in str(exc.value)
