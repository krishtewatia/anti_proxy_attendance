from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from app.schemas.audit import AuditEvent


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
