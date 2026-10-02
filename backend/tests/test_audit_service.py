from datetime import datetime, timezone, timedelta
import pytest
from mongomock_motor import AsyncMongoMockClient
from pydantic import ValidationError

from app.database import mongodb
from app.database.audit import AUDIT_EVENTS_COLLECTION, ensure_audit_indexes
from app.schemas.audit import AuditEvent
from app.services import audit_service


@pytest.fixture
async def setup_test_db():
    mongodb._client = AsyncMongoMockClient()
    db = mongodb.get_database()
    await db[AUDIT_EVENTS_COLLECTION].delete_many({})
    await ensure_audit_indexes(db)
    yield
    await db[AUDIT_EVENTS_COLLECTION].delete_many({})


# ------------------------------------------------------------------------------
# 1. Successful Audit Creation & Generation Tests
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_record_audit_event_success(setup_test_db):
    event = await audit_service.record_audit_event(
        actor_user_id="teacher_101",
        actor_role="TEACHER",
        action="SESSION_CREATED",
        resource_type="SESSION",
        resource_id="session_404",
        metadata={"classroom_id": "ROOM_202", "course": "Computer Networks"},
    )

    assert isinstance(event, AuditEvent)
    assert event.audit_id.startswith("audit_")
    assert event.actor_user_id == "teacher_101"
    assert event.actor_role == "TEACHER"
    assert event.action == "SESSION_CREATED"
    assert event.resource_type == "SESSION"
    assert event.resource_id == "session_404"
    assert event.metadata["classroom_id"] == "ROOM_202"
    assert event.metadata["course"] == "Computer Networks"
    assert event.timestamp is not None


@pytest.mark.anyio
async def test_record_audit_event_unique_generated_audit_id(setup_test_db):
    e1 = await audit_service.record_audit_event(
        actor_user_id="teacher_101",
        actor_role="TEACHER",
        action="SESSION_CREATED",
        resource_type="SESSION",
        resource_id="sess_1",
    )
    e2 = await audit_service.record_audit_event(
        actor_user_id="teacher_101",
        actor_role="TEACHER",
        action="SESSION_CREATED",
        resource_type="SESSION",
        resource_id="sess_2",
    )

    assert e1.audit_id != e2.audit_id
    assert e1.audit_id.startswith("audit_")
    assert e2.audit_id.startswith("audit_")


@pytest.mark.anyio
async def test_record_audit_event_timestamp_generation(setup_test_db):
    before = datetime.now(timezone.utc) - timedelta(seconds=1)
    event = await audit_service.record_audit_event(
        actor_user_id="admin_1",
        actor_role="ADMIN",
        action="USER_REGISTERED",
        resource_type="USER",
        resource_id="user_999",
    )
    after = datetime.now(timezone.utc) + timedelta(seconds=1)

    assert before <= event.timestamp <= after


@pytest.mark.anyio
async def test_record_audit_event_custom_id_and_timestamp(setup_test_db):
    custom_time = datetime(2026, 10, 1, 8, 30, tzinfo=timezone.utc)
    event = await audit_service.record_audit_event(
        actor_user_id="teacher_01",
        actor_role="TEACHER",
        action="SESSION_UPDATED",
        resource_type="SESSION",
        resource_id="sess_custom",
        audit_id="audit_custom_fixed_id",
        timestamp=custom_time,
    )

    assert event.audit_id == "audit_custom_fixed_id"
    assert event.timestamp == custom_time


# ------------------------------------------------------------------------------
# 2. Metadata & SYSTEM Actor Tests
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_record_audit_event_metadata_preservation(setup_test_db):
    metadata = {
        "ip_address": "192.168.1.50",
        "nested": {"key": "value", "count": 42},
        "tags": ["urgent", "manual_override"],
    }
    event = await audit_service.record_audit_event(
        actor_user_id="teacher_101",
        actor_role="TEACHER",
        action="ATTENDANCE_CORRECTED",
        resource_type="ATTENDANCE",
        resource_id="att_001",
        metadata=metadata,
    )

    assert event.metadata == metadata
    assert event.metadata["nested"]["count"] == 42


@pytest.mark.anyio
async def test_record_audit_event_metadata_defaults_to_empty_dict(setup_test_db):
    event = await audit_service.record_audit_event(
        actor_user_id="student_1",
        actor_role="STUDENT",
        action="STUDENT_PROFILE_CREATED",
        resource_type="STUDENT_PROFILE",
        resource_id="profile_1",
        metadata=None,
    )

    assert event.metadata == {}


@pytest.mark.anyio
async def test_record_audit_event_system_actor_support(setup_test_db):
    event = await audit_service.record_audit_event(
        actor_user_id="SYSTEM",
        actor_role="SYSTEM",
        action="ATTENDANCE_FINALIZED",
        resource_type="ATTENDANCE",
        resource_id="att_batch_job",
        metadata={"automated_job": "nightly_worker"},
    )

    assert event.actor_role == "SYSTEM"
    assert event.actor_user_id == "SYSTEM"
    assert event.action == "ATTENDANCE_FINALIZED"


# ------------------------------------------------------------------------------
# 3. Validation & Rejection Tests
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_record_audit_event_rejects_invalid_actor(setup_test_db):
    with pytest.raises(ValidationError) as exc:
        await audit_service.record_audit_event(
            actor_user_id="user_1",
            actor_role="SUPERADMIN",  # invalid
            action="SESSION_CREATED",
            resource_type="SESSION",
            resource_id="sess_1",
        )
    assert "actor_role" in str(exc.value)


@pytest.mark.anyio
async def test_record_audit_event_rejects_invalid_action(setup_test_db):
    with pytest.raises(ValidationError) as exc:
        await audit_service.record_audit_event(
            actor_user_id="user_1",
            actor_role="TEACHER",
            action="DELETE_DATABASE",  # invalid
            resource_type="SESSION",
            resource_id="sess_1",
        )
    assert "action" in str(exc.value)


@pytest.mark.anyio
async def test_record_audit_event_rejects_invalid_resource(setup_test_db):
    with pytest.raises(ValidationError) as exc:
        await audit_service.record_audit_event(
            actor_user_id="user_1",
            actor_role="TEACHER",
            action="SESSION_CREATED",
            resource_type="HARDWARE_ROUTER",  # invalid
            resource_id="sess_1",
        )
    assert "resource_type" in str(exc.value)


# ------------------------------------------------------------------------------
# 4. Repository Persistence & Retrieval Tests
# ------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_record_audit_event_persists_in_mongodb(setup_test_db):
    event = await audit_service.record_audit_event(
        actor_user_id="teacher_persist",
        actor_role="TEACHER",
        action="ROSTER_UPDATED",
        resource_type="SESSION_ROSTER",
        resource_id="sess_persist",
        metadata={"added_students": ["person_01", "person_02"]},
    )

    # Query directly in MongoDB collection to verify persistence
    db = mongodb.get_database()
    raw_doc = await db[AUDIT_EVENTS_COLLECTION].find_one({"audit_id": event.audit_id})

    assert raw_doc is not None
    assert raw_doc["audit_id"] == event.audit_id
    assert raw_doc["action"] == "ROSTER_UPDATED"
    assert raw_doc["metadata"]["added_students"] == ["person_01", "person_02"]

    # Retrieve through service get_audit_event
    retrieved = await audit_service.get_audit_event(event.audit_id)
    assert retrieved is not None
    assert retrieved.audit_id == event.audit_id
    assert retrieved.action == "ROSTER_UPDATED"


@pytest.mark.anyio
async def test_get_audit_events_chronological_filtering(setup_test_db):
    t1 = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 10, 1, 10, 10, tzinfo=timezone.utc)

    await audit_service.record_audit_event(
        actor_user_id="t1",
        actor_role="TEACHER",
        action="SESSION_CREATED",
        resource_type="SESSION",
        resource_id="sess_seq",
        timestamp=t2,
    )
    await audit_service.record_audit_event(
        actor_user_id="t1",
        actor_role="TEACHER",
        action="SESSION_CREATED",
        resource_type="SESSION",
        resource_id="sess_seq",
        timestamp=t1,
    )

    events = await audit_service.get_audit_events(
        resource_type="SESSION", resource_id="sess_seq"
    )
    assert len(events) == 2
    # Chronological: t1 before t2
    assert events[0].timestamp == t1
    assert events[1].timestamp == t2


# ------------------------------------------------------------------------------
# 5. Immutability Tests
# ------------------------------------------------------------------------------

def test_audit_service_immutability():
    """Verify that audit_service does NOT expose any mutation or deletion functions."""
    assert not hasattr(audit_service, "update_audit_event")
    assert not hasattr(audit_service, "delete_audit_event")
    assert not hasattr(audit_service, "update_event")
    assert not hasattr(audit_service, "delete_event")

    # Ensure no function in audit_service begins with 'update' or 'delete'
    for attr in dir(audit_service):
        assert not attr.startswith("update_"), f"Unexpected update function in service: {attr}"
        assert not attr.startswith("delete_"), f"Unexpected delete function in service: {attr}"
