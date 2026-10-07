"""Security tests for the attendance marking path.

A student is marked PRESENT only when a teacher who owns an ACTIVE session
sends a frame through the backend, and the vision service returns a signed
recognition result that the backend can verify for a rostered student.
"""

from datetime import datetime, timezone
import logging
import time

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.core.config import settings
from app.database import mongodb
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from app.services import recognition_service
from app.services.recognition_service import (
    RecognitionRejected,
    compute_signature,
    verify_recognition,
)
from app.services import vision_client
from app.services.vision_client import VisionServiceUnavailable, forward_frame_to_vision
from tests.conftest import FRAME_BYTES, TEST_RECOGNITION_KEY

SESSION_ID = "sess_secure_001"
OTHER_SESSION_ID = "sess_secure_002"
TEACHER_ID = "teacher_secure_owner"
FRAME_URL = f"/api/v1/attendance/{SESSION_ID}/process-frame"


@pytest.fixture(autouse=True)
def fresh_db():
    mongodb._client = AsyncMongoMockClient()
    yield
    mongodb._client = AsyncMongoMockClient()


async def _make_user(user_id: str, role: str) -> dict[str, str]:
    await create_user(
        user_id=user_id,
        email=f"{user_id}@secure.test",
        password_hash=hash_password("Password123!"),
        role=role,
    )
    return {"Authorization": f"Bearer {create_access_token(user_id=user_id, role=role)}"}


@pytest.fixture
async def teacher_headers():
    return await _make_user(TEACHER_ID, "TEACHER")


async def _seed_session(
    session_id: str = SESSION_ID,
    *,
    status: str = "ACTIVE",
    owner: str = TEACHER_ID,
    roster: tuple[str, ...] = ("student1", "student2"),
) -> None:
    db = mongodb.get_database()
    now = datetime.now(timezone.utc)
    await db["sessions"].insert_one(
        {
            "session_id": session_id,
            "course_name": "Secure Marking",
            "classroom_id": "ROOM_101",
            "start_time": now,
            "end_time": now,
            "required_presence_percentage": 100.0,
            "status": status,
            "created_by": owner,
        }
    )
    await db["session_rosters"].insert_one({"session_id": session_id, "identities": list(roster)})
    for identity in roster:
        await db["attendance_records"].insert_one(
            {
                "attendance_id": f"att_{session_id}_{identity}",
                "session_id": session_id,
                "identity": identity,
                "status": "ABSENT",
            }
        )


async def _status_of(identity: str, session_id: str = SESSION_ID) -> str | None:
    rec = await mongodb.get_database()["attendance_records"].find_one(
        {"session_id": session_id, "identity": identity}
    )
    return rec.get("status") if rec else None


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ------------------------------------------------------------------------------
# Who may send frames
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_frame_without_jwt_is_rejected_401(vision_frames):
    await _seed_session()
    vision_frames.faces = [vision_frames.recognized(SESSION_ID, "student1")]

    async with _client() as client:
        resp = await client.post(FRAME_URL, content=FRAME_BYTES)

    assert resp.status_code == 401
    assert vision_frames.calls == 0
    assert await _status_of("student1") == "ABSENT"


@pytest.mark.anyio
async def test_frame_from_student_is_rejected_403(vision_frames):
    await _seed_session()
    student_headers = await _make_user("student_secure_caller", "STUDENT")
    vision_frames.faces = [vision_frames.recognized(SESSION_ID, "student1")]

    async with _client() as client:
        resp = await client.post(FRAME_URL, headers=student_headers, content=FRAME_BYTES)

    assert resp.status_code == 403
    assert vision_frames.calls == 0
    assert await _status_of("student1") == "ABSENT"


@pytest.mark.anyio
async def test_frame_from_teacher_who_does_not_own_session_is_rejected_403(vision_frames):
    await _seed_session()
    other_teacher_headers = await _make_user("teacher_secure_other", "TEACHER")
    vision_frames.faces = [vision_frames.recognized(SESSION_ID, "student1")]

    async with _client() as client:
        resp = await client.post(FRAME_URL, headers=other_teacher_headers, content=FRAME_BYTES)

    assert resp.status_code == 403
    assert vision_frames.calls == 0
    assert await _status_of("student1") == "ABSENT"


@pytest.mark.anyio
async def test_frame_for_unknown_session_is_404(teacher_headers, vision_frames):
    async with _client() as client:
        resp = await client.post(
            "/api/v1/attendance/no_such_session/process-frame",
            headers=teacher_headers,
            content=FRAME_BYTES,
        )

    assert resp.status_code == 404
    assert vision_frames.calls == 0


@pytest.mark.anyio
@pytest.mark.parametrize("session_status", ["SCHEDULED", "FINALIZED", "COMPLETED"])
async def test_frame_for_session_that_is_not_active_is_rejected_409(
    teacher_headers, vision_frames, session_status
):
    await _seed_session(status=session_status)
    vision_frames.faces = [vision_frames.recognized(SESSION_ID, "student1")]

    async with _client() as client:
        resp = await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)

    assert resp.status_code == 409
    assert vision_frames.calls == 0
    assert await _status_of("student1") == "ABSENT"


# ------------------------------------------------------------------------------
# Happy path
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_valid_signed_recognition_marks_present_once(teacher_headers, vision_frames):
    await _seed_session()

    async with _client() as client:
        vision_frames.faces = [
            vision_frames.recognized(SESSION_ID, "student1", name="Alex Example"),
            vision_frames.unknown(),
        ]
        first = await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)

        # A later frame carries a new signed result for the same student
        vision_frames.faces = [vision_frames.recognized(SESSION_ID, "student1")]
        second = await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)

    assert first.status_code == 200
    body = first.json()
    assert body["recognized"] is True
    assert body["student_name"] == "Alex Example"
    assert body["detected_faces"] == 2
    assert body["faces"][0]["mark_status"] == "marked"
    assert body["faces"][1]["status"] == "unknown"
    assert "mark_status" not in body["faces"][1]

    assert second.status_code == 200
    assert second.json()["faces"][0]["mark_status"] == "already_present"

    db = mongodb.get_database()
    assert await _status_of("student1") == "PRESENT"
    assert await _status_of("student2") == "ABSENT"
    assert (
        await db["attendance_records"].count_documents(
            {"session_id": SESSION_ID, "identity": "student1"}
        )
        == 1
    )
    rec = await db["attendance_records"].find_one(
        {"session_id": SESSION_ID, "identity": "student1"}
    )
    assert rec["marked_at"] is not None


@pytest.mark.anyio
async def test_signed_results_are_never_returned_to_the_browser(teacher_headers, vision_frames):
    await _seed_session()
    vision_frames.faces = [vision_frames.recognized(SESSION_ID, "student1")]

    async with _client() as client:
        resp = await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)

    assert resp.status_code == 200
    assert "recognition" not in resp.json()["faces"][0]
    assert "signature" not in resp.text


# ------------------------------------------------------------------------------
# Forged, expired, mismatched and replayed results
# ------------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        ("unsigned", "unsigned"),
        ("wrong_key", "bad_signature"),
        ("tampered_identity", "bad_signature"),
        ("tampered_confidence", "bad_signature"),
        ("expired", "expired"),
        ("issued_in_future", "issued_in_future"),
        ("ttl_too_long", "ttl_too_long"),
        ("other_session", "session_mismatch"),
        ("malformed", "malformed"),
    ],
)
async def test_invalid_recognition_results_are_rejected(
    teacher_headers, vision_frames, sign_recognition, case, expected_reason
):
    await _seed_session()
    await _seed_session(OTHER_SESSION_ID)
    now = int(time.time())

    if case == "unsigned":
        token = None
    elif case == "wrong_key":
        token = sign_recognition(SESSION_ID, "student1", key="an-attackers-own-key")
    elif case == "tampered_identity":
        # Signed for student2, presented as student1
        token = {**sign_recognition(SESSION_ID, "student2"), "identity": "student1"}
    elif case == "tampered_confidence":
        token = {**sign_recognition(SESSION_ID, "student1", confidence=0.31), "confidence": 0.99}
    elif case == "expired":
        token = sign_recognition(SESSION_ID, "student1", issued_at=now - 120)
    elif case == "issued_in_future":
        token = sign_recognition(SESSION_ID, "student1", issued_at=now + 600)
    elif case == "ttl_too_long":
        token = sign_recognition(SESSION_ID, "student1", ttl=3600)
    elif case == "other_session":
        token = sign_recognition(OTHER_SESSION_ID, "student1")
    else:
        token = {**sign_recognition(SESSION_ID, "student1"), "issued_at": "not-a-number"}

    vision_frames.faces = [vision_frames.recognized(SESSION_ID, "student1", recognition=token)]

    async with _client() as client:
        resp = await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)

    assert resp.status_code == 200
    face = resp.json()["faces"][0]
    assert face["mark_status"] == "rejected"
    assert face["mark_reason"] == expected_reason
    # An unverifiable result is never shown as a recognized student
    assert face["status"] == "unverified"
    assert face["identity"] is None
    assert face["name"] == "UNKNOWN"
    assert resp.json()["recognized"] is False

    assert await _status_of("student1") == "ABSENT"
    assert await _status_of("student1", OTHER_SESSION_ID) == "ABSENT"


@pytest.mark.anyio
async def test_replayed_recognition_is_rejected(teacher_headers, vision_frames, sign_recognition):
    await _seed_session()
    token = sign_recognition(SESSION_ID, "student1")

    async with _client() as client:
        vision_frames.faces = [vision_frames.recognized(SESSION_ID, "student1", recognition=token)]
        first = await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)

        # The teacher corrects the student back to ABSENT, then the same result is replayed
        await mongodb.get_database()["attendance_records"].update_one(
            {"session_id": SESSION_ID, "identity": "student1"},
            {"$set": {"status": "ABSENT"}},
        )
        vision_frames.faces = [vision_frames.recognized(SESSION_ID, "student1", recognition=token)]
        replay = await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)

    assert first.json()["faces"][0]["mark_status"] == "marked"
    replay_face = replay.json()["faces"][0]
    assert replay_face["mark_status"] == "rejected"
    assert replay_face["mark_reason"] == "replayed"
    assert await _status_of("student1") == "ABSENT"


@pytest.mark.anyio
async def test_student_not_on_roster_is_rejected(teacher_headers, vision_frames):
    await _seed_session(roster=("student1",))
    vision_frames.faces = [vision_frames.recognized(SESSION_ID, "student_from_another_class")]

    async with _client() as client:
        resp = await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)

    face = resp.json()["faces"][0]
    assert face["mark_status"] == "rejected"
    assert face["mark_reason"] == "not_on_roster"
    assert resp.json()["recognized"] is False
    assert await _status_of("student_from_another_class") is None
    assert (
        await mongodb.get_database()["attendance_records"].count_documents(
            {"session_id": SESSION_ID}
        )
        == 1
    )


@pytest.mark.anyio
async def test_nothing_is_accepted_when_no_signing_key_is_configured(
    teacher_headers, vision_frames, monkeypatch
):
    await _seed_session()
    vision_frames.faces = [vision_frames.recognized(SESSION_ID, "student1")]
    monkeypatch.setattr(settings, "RECOGNITION_SIGNING_KEY", "")

    async with _client() as client:
        resp = await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)

    face = resp.json()["faces"][0]
    assert face["mark_status"] == "rejected"
    assert face["mark_reason"] == "signing_key_not_configured"
    assert await _status_of("student1") == "ABSENT"


# ------------------------------------------------------------------------------
# Manual corrections win
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_manual_correction_to_absent_is_not_overwritten_by_recognition(
    teacher_headers, vision_frames, caplog
):
    await _seed_session()
    attendance_id = f"att_{SESSION_ID}_student1"

    async with _client() as client:
        vision_frames.faces = [vision_frames.recognized(SESSION_ID, "student1")]
        marked = await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)
        assert marked.json()["faces"][0]["mark_status"] == "marked"

        # Teacher corrects the student to ABSENT through the audited route, session still ACTIVE
        correction = await client.patch(
            f"/api/v1/attendance/{SESSION_ID}/records/{attendance_id}",
            headers=teacher_headers,
            json={
                "new_status": "ABSENT",
                "new_presence_seconds": 0.0,
                "reason": "Student left immediately after being scanned.",
            },
        )
        assert correction.status_code == 200

        # A new, fully valid signed recognition arrives for the same student
        with caplog.at_level(logging.WARNING, logger="app.services.recognition_service"):
            vision_frames.faces = [vision_frames.recognized(SESSION_ID, "student1")]
            after = await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)

    assert after.status_code == 200
    face = after.json()["faces"][0]
    assert face["mark_status"] == "locked"
    assert after.json()["recognized"] is False

    rec = await mongodb.get_database()["attendance_records"].find_one(
        {"session_id": SESSION_ID, "identity": "student1"}
    )
    assert rec["status"] == "ABSENT"
    assert rec["manually_corrected"] is True

    # The blocked attempt is logged
    blocked = [r for r in caplog.records if "locked by a manual correction" in r.getMessage()]
    assert len(blocked) == 1
    assert "student1" in blocked[0].getMessage()
    assert SESSION_ID in blocked[0].getMessage()


@pytest.mark.anyio
async def test_manual_correction_to_present_survives_and_is_not_duplicated(
    teacher_headers, vision_frames
):
    await _seed_session()
    attendance_id = f"att_{SESSION_ID}_student2"

    async with _client() as client:
        correction = await client.patch(
            f"/api/v1/attendance/{SESSION_ID}/records/{attendance_id}",
            headers=teacher_headers,
            json={"status": "PRESENT"},
        )
        assert correction.status_code == 200

        vision_frames.faces = [vision_frames.recognized(SESSION_ID, "student2")]
        resp = await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)

    assert resp.json()["faces"][0]["mark_status"] == "locked"
    assert await _status_of("student2") == "PRESENT"


# ------------------------------------------------------------------------------
# Transport limits and failures
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_frame_rate_limit_per_session_returns_429(
    teacher_headers, vision_frames, monkeypatch
):
    await _seed_session()
    monkeypatch.setattr(settings, "FRAME_RATE_LIMIT_PER_MINUTE", 3)
    vision_frames.faces = [vision_frames.unknown()]

    async with _client() as client:
        codes = [
            (await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)).status_code
            for _ in range(5)
        ]

    assert codes == [200, 200, 200, 429, 429]
    assert vision_frames.calls == 3


@pytest.mark.anyio
async def test_frame_rate_limit_per_teacher_returns_429(
    teacher_headers, vision_frames, monkeypatch
):
    await _seed_session()
    monkeypatch.setattr(settings, "TEACHER_FRAME_RATE_LIMIT_PER_MINUTE", 2)
    vision_frames.faces = [vision_frames.unknown()]

    async with _client() as client:
        codes = [
            (await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)).status_code
            for _ in range(3)
        ]

    assert codes == [200, 200, 429]


@pytest.mark.anyio
async def test_oversized_and_empty_frames_are_rejected(teacher_headers, vision_frames, monkeypatch):
    await _seed_session()
    monkeypatch.setattr(settings, "FRAME_MAX_BYTES", 64)

    async with _client() as client:
        too_big = await client.post(FRAME_URL, headers=teacher_headers, content=b"x" * 200)
        empty = await client.post(FRAME_URL, headers=teacher_headers, content=b"")

    assert too_big.status_code == 413
    assert empty.status_code == 400
    assert vision_frames.calls == 0


@pytest.mark.anyio
async def test_vision_service_outage_returns_503_and_marks_nothing(teacher_headers, vision_frames):
    await _seed_session()
    vision_frames.error = VisionServiceUnavailable("vision service unreachable")

    async with _client() as client:
        resp = await client.post(FRAME_URL, headers=teacher_headers, content=FRAME_BYTES)

    assert resp.status_code == 503
    assert await _status_of("student1") == "ABSENT"


@pytest.mark.anyio
async def test_frame_contents_are_never_logged(teacher_headers, vision_frames, caplog):
    await _seed_session()
    marker = b"FRAME-PAYLOAD-MARKER-7f3a9c"
    vision_frames.faces = [vision_frames.recognized(SESSION_ID, "student1")]

    with caplog.at_level(logging.DEBUG):
        async with _client() as client:
            resp = await client.post(FRAME_URL, headers=teacher_headers, content=marker)

    assert resp.status_code == 200
    assert marker.decode() not in caplog.text
    for record in caplog.records:
        assert marker.decode() not in repr(record.args)


# ------------------------------------------------------------------------------
# Removed and locked-down routes
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_public_mark_routes_no_longer_exist(teacher_headers):
    await _seed_session()

    async with _client() as client:
        sessionless = await client.post(
            "/api/v1/attendance/mark",
            json={"identity": "student1", "session_id": SESSION_ID},
        )
        scoped = await client.post(
            f"/api/v1/attendance/{SESSION_ID}/mark",
            headers=teacher_headers,
            json={"identity": "student1"},
        )
        sessionless_frame = await client.post(
            "/api/v1/attendance/process-frame", headers=teacher_headers, content=FRAME_BYTES
        )

    assert sessionless.status_code in (404, 405)
    assert scoped.status_code in (404, 405)
    assert sessionless_frame.status_code in (404, 405)
    assert await _status_of("student1") == "ABSENT"


@pytest.mark.anyio
async def test_gallery_and_active_session_require_the_service_key(
    teacher_headers, service_key_headers
):
    await _seed_session()
    db = mongodb.get_database()
    await db["biometric_profiles"].insert_one(
        {"identity": "student1", "mean_embedding": [0.05] * 512}
    )

    async with _client() as client:
        for path in ("/api/v1/attendance/vision-gallery", "/api/v1/attendance/active-session"):
            assert (await client.get(path)).status_code == 401
            # A teacher's JWT is not a service credential
            assert (await client.get(path, headers=teacher_headers)).status_code == 401
            assert (await client.get(path, headers={"X-API-Key": "wrong-key"})).status_code == 401

        gallery = await client.get("/api/v1/attendance/vision-gallery", headers=service_key_headers)
        active = await client.get("/api/v1/attendance/active-session", headers=service_key_headers)

    assert gallery.status_code == 200
    assert gallery.json()["count"] == 1
    assert active.status_code == 200
    assert active.json()["session_id"] == SESSION_ID


@pytest.mark.anyio
async def test_service_key_is_required_even_when_camera_auth_is_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_CAMERA_AUTH", False)

    async with _client() as client:
        resp = await client.get("/api/v1/attendance/vision-gallery")

    assert resp.status_code == 401


# ------------------------------------------------------------------------------
# Signature format (must stay identical to the vision service signer)
# ------------------------------------------------------------------------------


def test_signature_matches_the_shared_test_vector():
    """The same vector is asserted in vision-service/tests/test_recognition_signing.py."""
    signature = compute_signature(
        "shared-test-vector-key",
        "sess_vector_1",
        "student1",
        0.9123,
        1790000000,
        1790000030,
        "0123456789abcdef0123456789abcdef",
    )
    assert signature == "f7c62bfa88f268a5dc4513f9c588139877106aa1c35b615a427d37d24796cfbe"


def test_verify_recognition_accepts_a_fresh_result_and_rejects_non_dicts(sign_recognition):
    token = sign_recognition(SESSION_ID, "student1", confidence=0.8765)

    verified = verify_recognition(token, session_id=SESSION_ID)
    assert verified.identity == "student1"
    assert verified.confidence == 0.8765
    assert verified.nonce == token["nonce"]

    for bad in ("a string", ["a", "list"], 42, {}):
        with pytest.raises(RecognitionRejected) as excinfo:
            verify_recognition(bad, session_id=SESSION_ID)
        assert excinfo.value.reason == "unsigned"


def test_signing_key_in_tests_is_the_configured_one(sign_recognition):
    assert settings.RECOGNITION_SIGNING_KEY == TEST_RECOGNITION_KEY
    assert recognition_service.NONCE_COLLECTION == "recognition_nonces"


# ------------------------------------------------------------------------------
# Backend -> vision service client
# ------------------------------------------------------------------------------


class _FakeVisionHTTP:
    """Minimal stand-in for httpx.AsyncClient used by the vision client."""

    def __init__(self, *, status_code=200, payload=None, raises=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self._raises = raises
        self._text = text
        self.requests: list[dict] = []

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, **kwargs):
        self.requests.append({"url": url, **kwargs})
        if self._raises is not None:
            raise self._raises
        return self

    def json(self):
        if self._text is not None:
            raise ValueError("not json")
        return self._payload


@pytest.mark.anyio
async def test_vision_client_sends_the_service_key_and_session(monkeypatch, service_key_headers):
    fake = _FakeVisionHTTP(payload={"faces": []})
    monkeypatch.setattr(vision_client.httpx, "AsyncClient", fake)
    monkeypatch.setattr(settings, "VISION_SERVICE_URL", "http://vision-service:8088/")

    result = await forward_frame_to_vision(FRAME_BYTES, "image/jpeg", SESSION_ID)

    assert result == {"faces": []}
    request = fake.requests[0]
    assert request["url"] == "http://vision-service:8088/process-frame"
    assert request["headers"]["X-API-Key"] == service_key_headers["X-API-Key"]
    assert request["headers"]["Content-Type"] == "image/jpeg"
    assert request["params"] == {"session_id": SESSION_ID}
    assert request["content"] == FRAME_BYTES


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fake",
    [
        _FakeVisionHTTP(status_code=401, payload={"error": "unauthorized"}),
        _FakeVisionHTTP(status_code=503, payload={}),
        _FakeVisionHTTP(text="<html>not json</html>"),
        _FakeVisionHTTP(payload=["not", "a", "dict"]),
        _FakeVisionHTTP(raises=vision_client.httpx.ConnectError("connection refused")),
    ],
)
async def test_vision_client_turns_every_failure_into_unavailable(monkeypatch, fake):
    monkeypatch.setattr(vision_client.httpx, "AsyncClient", fake)

    with pytest.raises(VisionServiceUnavailable):
        await forward_frame_to_vision(FRAME_BYTES, "image/jpeg", SESSION_ID)
