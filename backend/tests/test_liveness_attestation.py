"""Liveness on the backend side of the frame path.

The vision service attests liveness inside the signed recognition result. The
backend never marks a face the vision service refused to sign, records spoof
attempts in the audit log, and in enforce mode accepts only results signed as
"liveness passed". The vision service is stubbed; no image data is involved.
"""

from datetime import datetime, timezone

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.api.routes import attendance as attendance_routes
from app.core.config import settings
from app.database import mongodb
from app.database.users import create_user
from app.main import app
from app.security.config import validate_liveness_mode
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from app.services.recognition_service import RecognitionRejected, verify_recognition
from tests.conftest import FRAME_BYTES

SESSION_ID = "sess_liveness_001"
TEACHER_ID = "teacher_liveness_owner"
FRAME_URL = f"/api/v1/attendance/{SESSION_ID}/process-frame"


@pytest.fixture(autouse=True)
def fresh_state():
    mongodb._client = AsyncMongoMockClient()
    attendance_routes._last_spoof_audit.clear()
    yield
    mongodb._client = AsyncMongoMockClient()
    attendance_routes._last_spoof_audit.clear()


@pytest.fixture
async def teacher_headers():
    await create_user(
        user_id=TEACHER_ID,
        email=f"{TEACHER_ID}@liveness.test",
        password_hash=hash_password("Password123!"),
        role="TEACHER",
    )
    return {"Authorization": f"Bearer {create_access_token(user_id=TEACHER_ID, role='TEACHER')}"}


@pytest.fixture
def enforce(monkeypatch):
    monkeypatch.setattr(settings, "LIVENESS_MODE", "enforce")


async def _seed_session(roster: tuple[str, ...] = ("student1", "student2")) -> None:
    db = mongodb.get_database()
    now = datetime.now(timezone.utc)
    await db["sessions"].insert_one(
        {
            "session_id": SESSION_ID,
            "course_name": "Liveness",
            "classroom_id": "ROOM_101",
            "start_time": now,
            "end_time": now,
            "required_presence_percentage": 100.0,
            "status": "ACTIVE",
            "created_by": TEACHER_ID,
        }
    )
    await db["session_rosters"].insert_one({"session_id": SESSION_ID, "identities": list(roster)})
    for identity in roster:
        await db["attendance_records"].insert_one(
            {
                "attendance_id": f"att_{SESSION_ID}_{identity}",
                "session_id": SESSION_ID,
                "identity": identity,
                "status": "ABSENT",
            }
        )


async def _status_of(identity: str) -> str | None:
    rec = await mongodb.get_database()["attendance_records"].find_one(
        {"session_id": SESSION_ID, "identity": identity}
    )
    return rec.get("status") if rec else None


async def _spoof_audit_events() -> list[dict]:
    cursor = mongodb.get_database()["audit_events"].find({"action": "SPOOF_ATTEMPT"})
    return [doc async for doc in cursor]


def _blocked_face(identity: str, status: str = "spoof", score: float | None = 0.04) -> dict:
    """What the vision service returns for a recognized face it refused to sign."""
    return {
        "bbox": [10, 10, 110, 110],
        "identity": identity,
        "student_id": identity,
        "name": identity,
        "similarity": 0.93,
        "status": status,
        "liveness": {"status": "spoof" if status == "spoof" else "error", "score": score, "mode": "enforce"},
    }


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ------------------------------------------------------------------------------
# A face the vision service refused to sign marks nobody
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_spoof_face_marks_nobody_and_is_reported_to_the_teacher(teacher_headers, vision_frames):
    await _seed_session()
    vision_frames.faces = [_blocked_face("student1")]

    async with _client() as client:
        resp = await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)

    assert resp.status_code == 200
    body = resp.json()
    face = body["faces"][0]
    assert face["status"] == "spoof"
    assert face["mark_status"] == "blocked"
    assert body["recognized"] is False
    assert "recognition" not in face
    assert await _status_of("student1") == "ABSENT"


@pytest.mark.anyio
async def test_spoof_attempt_is_audited_once_per_student_with_no_image_data(
    teacher_headers, vision_frames
):
    await _seed_session()
    vision_frames.faces = [_blocked_face("student1")]

    async with _client() as client:
        for _ in range(4):  # the same spoof is seen on consecutive frames
            await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)
        vision_frames.faces = [_blocked_face("student2", score=0.11)]
        await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)

    events = await _spoof_audit_events()
    assert len(events) == 2
    by_identity = {e["metadata"]["presented_identity"]: e for e in events}
    first = by_identity["student1"]
    assert first["resource_type"] == "SESSION"
    assert first["resource_id"] == SESSION_ID
    assert first["actor_role"] == "SYSTEM"
    assert first["metadata"] == {
        "presented_identity": "student1",
        "liveness_score": 0.04,
        "session_teacher_id": TEACHER_ID,
    }
    assert by_identity["student2"]["metadata"]["liveness_score"] == 0.11
    assert await _status_of("student1") == "ABSENT"
    assert await _status_of("student2") == "ABSENT"


@pytest.mark.anyio
async def test_liveness_unavailable_marks_nobody_and_is_not_called_a_spoof(
    teacher_headers, vision_frames
):
    await _seed_session()
    vision_frames.faces = [_blocked_face("student1", status="liveness_unavailable", score=None)]

    async with _client() as client:
        resp = await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)

    face = resp.json()["faces"][0]
    assert face["status"] == "liveness_unavailable"
    assert face["mark_status"] == "blocked"
    assert await _status_of("student1") == "ABSENT"
    assert await _spoof_audit_events() == []


@pytest.mark.anyio
async def test_a_spoof_next_to_a_live_student_blocks_only_the_spoof(teacher_headers, vision_frames):
    await _seed_session()
    vision_frames.faces = [
        _blocked_face("student1"),
        vision_frames.recognized(SESSION_ID, "student2"),
    ]

    async with _client() as client:
        resp = await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)

    statuses = {f["identity"]: f["mark_status"] for f in resp.json()["faces"]}
    assert statuses == {"student1": "blocked", "student2": "marked"}
    assert await _status_of("student1") == "ABSENT"
    assert await _status_of("student2") == "PRESENT"


# ------------------------------------------------------------------------------
# Enforce: only results signed as "liveness passed" are accepted
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_enforce_rejects_a_result_signed_without_a_liveness_verdict(
    teacher_headers, vision_frames, enforce
):
    """A vision service running in observe mode cannot mark when the backend enforces."""
    await _seed_session()
    vision_frames.faces = [vision_frames.recognized(SESSION_ID, "student1", liveness="unchecked")]

    async with _client() as client:
        resp = await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)

    face = resp.json()["faces"][0]
    assert face["mark_status"] == "rejected"
    assert face["mark_reason"] == "liveness_not_passed"
    assert face["status"] == "unverified"
    assert face["identity"] is None
    assert await _status_of("student1") == "ABSENT"


@pytest.mark.anyio
async def test_enforce_accepts_a_result_signed_as_liveness_passed(
    teacher_headers, vision_frames, enforce
):
    await _seed_session()
    vision_frames.faces = [vision_frames.recognized(SESSION_ID, "student1", liveness="passed")]

    async with _client() as client:
        resp = await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)

    assert resp.json()["faces"][0]["mark_status"] == "marked"
    assert await _status_of("student1") == "PRESENT"


@pytest.mark.anyio
@pytest.mark.parametrize("attestation", ["unchecked", "passed"])
async def test_observe_accepts_both_attestations(teacher_headers, vision_frames, attestation):
    assert settings.LIVENESS_MODE == "observe"
    await _seed_session()
    vision_frames.faces = [vision_frames.recognized(SESSION_ID, "student1", liveness=attestation)]

    async with _client() as client:
        resp = await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)

    assert resp.json()["faces"][0]["mark_status"] == "marked"
    assert await _status_of("student1") == "PRESENT"


# ------------------------------------------------------------------------------
# The attestation is part of what is signed
# ------------------------------------------------------------------------------


def test_relabelling_unchecked_as_passed_breaks_the_signature(sign_recognition, enforce):
    token = sign_recognition(SESSION_ID, "student1", liveness="unchecked")
    upgraded = {**token, "liveness": "passed"}

    with pytest.raises(RecognitionRejected) as excinfo:
        verify_recognition(upgraded, session_id=SESSION_ID)
    assert excinfo.value.reason == "bad_signature"


def test_a_result_without_a_liveness_attestation_is_unsigned(sign_recognition):
    token = sign_recognition(SESSION_ID, "student1")
    for bad in ({k: v for k, v in token.items() if k != "liveness"}, {**token, "liveness": ""}):
        with pytest.raises(RecognitionRejected) as excinfo:
            verify_recognition(bad, session_id=SESSION_ID)
        assert excinfo.value.reason == "unsigned"


def test_an_unknown_attestation_value_is_rejected_even_if_correctly_signed(sign_recognition):
    token = sign_recognition(SESSION_ID, "student1", liveness="probably")
    with pytest.raises(RecognitionRejected) as excinfo:
        verify_recognition(token, session_id=SESSION_ID)
    assert excinfo.value.reason == "malformed"


def test_verified_result_reports_the_attestation(sign_recognition):
    assert verify_recognition(
        sign_recognition(SESSION_ID, "student1", liveness="passed"), session_id=SESSION_ID
    ).liveness == "passed"


# ------------------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------------------


def test_liveness_mode_must_be_observe_or_enforce():
    validate_liveness_mode("observe")
    validate_liveness_mode("enforce")
    for bad in ("", "off", "disabled", "ENFORCE ", "true"):
        with pytest.raises(RuntimeError):
            validate_liveness_mode(bad)
