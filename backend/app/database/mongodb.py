"""MongoDB connection and database dependency management."""

from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings

import asyncio

_client: Optional[AsyncIOMotorClient] = None


def get_client() -> AsyncIOMotorClient:
    """Get or create singleton MongoDB client with event-loop awareness."""
    global _client
    if _client is not None:
        try:
            current_loop = asyncio.get_running_loop()
            client_loop = getattr(_client, "io_loop", None)
            if (
                client_loop is not None
                and isinstance(client_loop, asyncio.AbstractEventLoop)
                and (client_loop.is_closed() or client_loop != current_loop)
            ):
                _client.close()
                _client = None
        except RuntimeError:
            pass

    if _client is None:
        if (
            settings.MONGODB_URL.startswith("mongomock://")
            or settings.MONGODB_URL == "mock"
            or settings.MONGODB_URL == ""
        ):
            from mongomock_motor import AsyncMongoMockClient

            _client = AsyncMongoMockClient()
        else:
            _client = AsyncIOMotorClient(
                settings.MONGODB_URL,
                serverSelectionTimeoutMS=settings.MONGODB_SERVER_SELECTION_TIMEOUT_MS,
            )
    return _client


def close_client():
    """Close MongoDB client connection."""
    global _client
    if _client is not None:
        _client.close()
        _client = None


def get_database() -> AsyncIOMotorDatabase:
    """FastAPI dependency to retrieve the application database."""
    client = get_client()
    return client[settings.DATABASE_NAME]


async def init_indexes(db: AsyncIOMotorDatabase):
    """Ensure required database indexes are created."""
    # Enforce unique event_id for strict database-level idempotency
    await db[settings.EVENTS_COLLECTION].create_index(
        "event_id",
        unique=True,
        name="unique_event_id_idx",
    )
    # Enforce unique email on users collection
    await db["users"].create_index(
        [("email", 1)],
        unique=True,
        name="uq_users_email",
    )
    # Enforce unique user_id and identity on student_profiles collection
    await db["student_profiles"].create_index(
        [("user_id", 1)],
        unique=True,
        name="uq_student_profiles_user_id",
    )
    await db["student_profiles"].create_index(
        [("identity", 1)],
        unique=True,
        name="uq_student_profiles_identity",
    )
    # Enforce unique audit_id and compound chronological history on audit_events
    await db["audit_events"].create_index(
        "audit_id",
        unique=True,
        name="uq_audit_id",
    )
    await db["audit_events"].create_index(
        [("resource_type", 1), ("resource_id", 1), ("timestamp", 1)],
        name="idx_audit_resource_history",
    )
    # Replay protection for signed recognition results: unique nonce + TTL expiry
    await db["recognition_nonces"].create_index(
        "nonce",
        unique=True,
        name="uq_recognition_nonce",
    )
    await db["recognition_nonces"].create_index(
        "expires_at",
        expireAfterSeconds=0,
        name="ttl_recognition_nonce",
    )
    # Pilot organisation model: one document per key.
    for collection, keys, name in (
        ("org_terms", [("term_id", 1)], "uq_org_terms"),
        ("org_branches", [("code", 1)], "uq_org_branches"),
        ("org_cohorts", [("cohort_id", 1)], "uq_org_cohorts"),
        ("org_sections", [("cohort_id", 1), ("code", 1)], "uq_org_sections"),
        ("org_group_sets", [("cohort_id", 1), ("set_code", 1)], "uq_org_group_sets"),
        ("catalog_subjects", [("key", 1)], "uq_catalog_subjects"),
        ("org_classes", [("class_id", 1)], "uq_org_classes"),
        ("timetable_versions", [("version_id", 1)], "uq_timetable_versions"),
        ("timetable_slots", [("slot_id", 1)], "uq_timetable_slots"),
        ("calendar_exceptions", [("exception_id", 1)], "uq_calendar_exceptions"),
        ("org_settings", [("settings_id", 1)], "uq_org_settings"),
        ("consents", [("user_id", 1), ("notice_version", 1)], "uq_consents"),
        ("enrolment_requests", [("request_id", 1)], "uq_enrolment_requests"),
        ("enrolments", [("user_id", 1), ("term_id", 1)], "uq_enrolments"),
        ("section_lists", [("cohort_id", 1)], "uq_section_lists"),
        ("teacher_requests", [("request_id", 1)], "uq_teacher_requests"),
    ):
        await db[collection].create_index(keys, unique=True, name=name)
    await db["timetable_slots"].create_index(
        [("version_id", 1), ("day", 1), ("start_minute", 1)], name="idx_timetable_slots_day"
    )
    # Sessions of all sections run at once: unique ids, at most one session per
    # timetable slot and day (sparse: older sessions have no slot), and the
    # lookups each frame and roster make.
    await db["sessions"].create_index(
        [("session_id", 1)], unique=True, name="uq_sessions_session_id"
    )
    await db["sessions"].create_index(
        [("slot_id", 1), ("date", 1)], unique=True, sparse=True, name="uq_sessions_slot_date"
    )
    await db["attendance_records"].create_index(
        [("session_id", 1), ("identity", 1)], name="idx_attendance_session_identity"
    )
    await db["session_rosters"].create_index(
        [("session_id", 1)], name="idx_session_rosters_session"
    )
    await db["enrolments"].create_index([("class_ids", 1)], name="idx_enrolments_class_ids")
    await db["org_classes"].create_index([("teacher_ids", 1)], name="idx_org_classes_teacher_ids")
    await db["teacher_assignments"].create_index(
        [("class_id", 1), ("teacher_id", 1), ("to", 1)], name="idx_teacher_assignments_open"
    )
    # Enforce unique camera_id on cameras collection
    await db["cameras"].create_index(
        [("camera_id", 1)],
        unique=True,
        name="uq_cameras_camera_id",
    )
