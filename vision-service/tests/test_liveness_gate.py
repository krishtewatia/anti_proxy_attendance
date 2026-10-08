"""The liveness gate on the frame path, with a stubbed model.

No face photo and no model file is used: frames are synthetic arrays, the face
detector is a stub that reports one face, and the liveness model is a stub
that returns whatever the test asks for. Fast and safe for CI.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from pathlib import Path
import secrets
import sys
import time
from types import SimpleNamespace

from aiohttp.test_utils import TestClient, TestServer
import cv2
import numpy as np
import pytest

SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from camera import liveness as liveness_module  # noqa: E402
from camera import vision_api  # noqa: E402
from camera.liveness import (  # noqa: E402
    ATTESTATION_PASSED,
    ATTESTATION_UNCHECKED,
    DEFAULT_LIVENESS_MODE,
    MODE_ENFORCE,
    MODE_OBSERVE,
    STATUS_ERROR,
    STATUS_LIVE,
    STATUS_SPOOF,
    LivenessResult,
    MiniFASNetLiveness,
    evaluate_liveness_gate,
    load_liveness_checker,
    prepare_model_input,
    resolve_liveness_mode,
    resolve_liveness_threshold,
    scaled_crop_box,
)
from camera.recognition_signing import canonical_message  # noqa: E402
from camera.vision_api import VisionApiServer  # noqa: E402

SERVICE_KEY = secrets.token_hex(16)  # generated per run; no key material in the repo
SIGNING_KEY = secrets.token_hex(32)
AUTH = {"X-API-Key": SERVICE_KEY}
SESSION_ID = "sess_liveness_1"
FRAME = np.full((240, 320, 3), 90, dtype=np.uint8)
FACE_BBOX = [100.0, 60.0, 180.0, 160.0]


def _jpeg() -> bytes:
    ok, encoded = cv2.imencode(".jpg", FRAME)
    assert ok
    return encoded.tobytes()


def _unit(index: int) -> np.ndarray:
    vector = np.zeros(512, dtype=np.float32)
    vector[index] = 1.0
    return vector


class StubFaceApp:
    """Reports one face whose embedding matches the enrolled student (or nobody)."""

    def __init__(self, embedding: np.ndarray):
        self._embedding = embedding

    def get(self, image):
        return [
            SimpleNamespace(
                bbox=np.array(FACE_BBOX, dtype=np.float32),
                normed_embedding=self._embedding,
                det_score=0.99,
            )
        ]


class StubLiveness:
    def __init__(self, result: LivenessResult | Exception):
        self.result = result
        self.calls = 0

    def check(self, frame_bgr, bbox_xyxy):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


LIVE = LivenessResult(status=STATUS_LIVE, score=0.97)
SPOOF = LivenessResult(status=STATUS_SPOOF, score=0.04, reason="below_threshold")
FAILED = LivenessResult(status=STATUS_ERROR, reason="inference_failed")


def _process_frame(monkeypatch, *, mode, checker, embedding=None):
    """Send one frame through the real handler and return (face, sign_call_count)."""
    monkeypatch.setenv("VISION_SERVICE_API_KEY", SERVICE_KEY)
    monkeypatch.setenv("RECOGNITION_SIGNING_KEY", SIGNING_KEY)

    sign_calls = []
    real_sign = vision_api.sign_recognition

    def counting_sign(**kwargs):
        sign_calls.append(kwargs)
        return real_sign(**kwargs)

    monkeypatch.setattr(vision_api, "sign_recognition", counting_sign)

    async def _main():
        server = VisionApiServer(liveness_mode=mode, liveness_checker=checker)
        server.set_face_app(StubFaceApp(_unit(0) if embedding is None else embedding))
        server.gallery = {"student1": _unit(0)}
        server._last_gallery_sync = time.time()  # no backend to sync from in this test
        async with TestClient(TestServer(server.app)) as client:
            response = await client.post(
                f"/process-frame?session_id={SESSION_ID}",
                data=_jpeg(),
                headers={**AUTH, "Content-Type": "image/jpeg"},
            )
            assert response.status == 200
            return await response.json()

    payload = asyncio.run(_main())
    assert len(payload["faces"]) == 1
    return payload["faces"][0], sign_calls


def _signature_is_valid(token: dict) -> bool:
    message = canonical_message(
        token["session_id"],
        token["identity"],
        token["confidence"],
        token["issued_at"],
        token["expires_at"],
        token["nonce"],
        token["liveness"],
    )
    expected = hmac.new(SIGNING_KEY.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, token["signature"])


# ------------------------------------------------------------------------------
# Enforce: a face that is not judged live never produces a signed result
# ------------------------------------------------------------------------------


def test_enforce_spoof_produces_no_signed_result(monkeypatch):
    checker = StubLiveness(SPOOF)
    face, sign_calls = _process_frame(monkeypatch, mode=MODE_ENFORCE, checker=checker)

    assert checker.calls == 1
    assert face["status"] == "spoof"
    assert "recognition" not in face
    assert "signature" not in str(face)
    assert sign_calls == []
    assert face["liveness"] == {"status": "spoof", "score": 0.04, "mode": "enforce"}


def test_enforce_live_face_is_signed_as_liveness_passed(monkeypatch):
    checker = StubLiveness(LIVE)
    face, sign_calls = _process_frame(monkeypatch, mode=MODE_ENFORCE, checker=checker)

    assert checker.calls == 1
    assert face["status"] == "recognized"
    assert len(sign_calls) == 1
    token = face["recognition"]
    assert token["identity"] == "student1"
    assert token["session_id"] == SESSION_ID
    assert token["liveness"] == ATTESTATION_PASSED
    assert _signature_is_valid(token)


@pytest.mark.parametrize(
    "checker",
    [StubLiveness(FAILED), StubLiveness(RuntimeError("model crashed")), None],
    ids=["inference_error", "checker_raises", "model_not_loaded"],
)
def test_enforce_fails_closed_when_liveness_cannot_be_determined(monkeypatch, checker):
    face, sign_calls = _process_frame(monkeypatch, mode=MODE_ENFORCE, checker=checker)

    assert face["status"] == "liveness_unavailable"
    assert "recognition" not in face
    assert sign_calls == []


def test_the_attestation_is_covered_by_the_signature(monkeypatch):
    """A result signed as unchecked cannot be relabelled as passed."""
    face, _ = _process_frame(monkeypatch, mode=MODE_OBSERVE, checker=StubLiveness(SPOOF))
    token = face["recognition"]
    assert _signature_is_valid(token)
    assert not _signature_is_valid({**token, "liveness": ATTESTATION_PASSED})


# ------------------------------------------------------------------------------
# Observe: checked and logged, still signed, but never signed as "passed"
# ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "checker", [StubLiveness(SPOOF), StubLiveness(LIVE), None], ids=["spoof", "live", "no_model"]
)
def test_observe_signs_as_unchecked_whatever_the_outcome(monkeypatch, checker):
    face, sign_calls = _process_frame(monkeypatch, mode=MODE_OBSERVE, checker=checker)

    assert face["status"] == "recognized"
    assert len(sign_calls) == 1
    assert face["recognition"]["liveness"] == ATTESTATION_UNCHECKED
    assert face["liveness"]["mode"] == "observe"


def test_observe_is_the_default_mode():
    assert DEFAULT_LIVENESS_MODE == MODE_OBSERVE
    assert VisionApiServer().liveness_mode == MODE_OBSERVE


# ------------------------------------------------------------------------------
# Scope and logging
# ------------------------------------------------------------------------------


def test_unknown_face_is_not_checked_and_not_signed(monkeypatch):
    checker = StubLiveness(LIVE)
    face, sign_calls = _process_frame(
        monkeypatch, mode=MODE_ENFORCE, checker=checker, embedding=_unit(7)
    )

    assert face["status"] == "unknown"
    assert checker.calls == 0
    assert sign_calls == []


def test_spoof_is_logged_with_identifiers_and_no_image_or_embedding_data(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="camera.vision_api"):
        _process_frame(monkeypatch, mode=MODE_ENFORCE, checker=StubLiveness(SPOOF))

    messages = [r.getMessage() for r in caplog.records if "Liveness" in r.getMessage()]
    assert len(messages) == 1
    message = messages[0]
    assert "spoof" in message and SESSION_ID in message and "student1" in message
    assert "0.04" in message and "signed=False" in message
    # No pixel data, bounding boxes or vectors: only short identifiers and a score.
    assert len(message) < 200
    assert "[" not in message and "array" not in message


# ------------------------------------------------------------------------------
# The gate decision itself
# ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode,result,allow,attestation",
    [
        (MODE_ENFORCE, LIVE, True, ATTESTATION_PASSED),
        (MODE_ENFORCE, SPOOF, False, None),
        (MODE_ENFORCE, FAILED, False, None),
        (MODE_OBSERVE, LIVE, True, ATTESTATION_UNCHECKED),
        (MODE_OBSERVE, SPOOF, True, ATTESTATION_UNCHECKED),
        (MODE_OBSERVE, FAILED, True, ATTESTATION_UNCHECKED),
    ],
)
def test_gate_decision_table(mode, result, allow, attestation):
    decision = evaluate_liveness_gate(mode, StubLiveness(result), FRAME, FACE_BBOX)
    assert decision.allow_signing is allow
    assert decision.attestation == attestation
    assert decision.result == result


def test_passed_is_only_ever_attested_for_a_live_face_in_enforce_mode():
    for mode in (MODE_ENFORCE, MODE_OBSERVE):
        for result in (LIVE, SPOOF, FAILED):
            decision = evaluate_liveness_gate(mode, StubLiveness(result), FRAME, FACE_BBOX)
            if decision.attestation == ATTESTATION_PASSED:
                assert mode == MODE_ENFORCE and result.is_live


# ------------------------------------------------------------------------------
# Configuration fails closed
# ------------------------------------------------------------------------------


def test_mode_and_threshold_parsing(monkeypatch):
    monkeypatch.delenv("LIVENESS_MODE", raising=False)
    monkeypatch.delenv("LIVENESS_THRESHOLD", raising=False)
    assert resolve_liveness_mode() == MODE_OBSERVE
    assert resolve_liveness_mode(" Enforce ") == MODE_ENFORCE
    assert resolve_liveness_threshold() == liveness_module.DEFAULT_LIVENESS_THRESHOLD
    assert resolve_liveness_threshold("0.8") == 0.8

    for bad_mode in ("off", "disabled", "true"):
        with pytest.raises(RuntimeError):
            resolve_liveness_mode(bad_mode)
    for bad_threshold in ("high", "1.5", "-0.1"):
        with pytest.raises(RuntimeError):
            resolve_liveness_threshold(bad_threshold)


def test_enforce_refuses_to_start_without_the_model(tmp_path):
    with pytest.raises(RuntimeError, match="enforce"):
        load_liveness_checker(MODE_ENFORCE, model_dir=tmp_path)


def test_observe_starts_without_the_model_only_when_no_model_directory_is_configured(
    tmp_path, monkeypatch
):
    """A development run: nothing configured, nothing in the default location."""
    monkeypatch.delenv("LIVENESS_MODEL_DIR", raising=False)
    monkeypatch.setattr(liveness_module, "DEFAULT_MODEL_DIR", tmp_path)
    assert load_liveness_checker(MODE_OBSERVE) is None


def test_a_configured_model_directory_must_load_even_in_observe_mode(tmp_path, monkeypatch):
    """In the image LIVENESS_MODEL_DIR is set: a model that cannot be read is a broken build."""
    monkeypatch.setenv("LIVENESS_MODEL_DIR", str(tmp_path))
    with pytest.raises(RuntimeError, match="LIVENESS_MODEL_DIR"):
        load_liveness_checker(MODE_OBSERVE)
    with pytest.raises(RuntimeError, match="LIVENESS_MODEL_DIR"):
        load_liveness_checker(MODE_OBSERVE, model_dir=tmp_path)


def test_image_copies_the_model_files_into_a_traversable_directory():
    """Copying the directory itself with --chmod=0444 made it unreadable for the service user."""
    dockerfile = (SERVICE_ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (SERVICE_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "--chmod=0444 /liveness/ /app/models/liveness/" not in dockerfile
    assert "mkdir -p /app/models/liveness" in dockerfile
    for spec in liveness_module.MODEL_SPECS:
        assert f"/liveness/{spec.filename}" in dockerfile
        assert f"sha256:{spec.sha256}" in dockerfile
        assert f"test -r /app/models/liveness/{spec.filename}" in dockerfile
    # Local model files must not reach the image through the build context.
    assert "models/" in dockerignore.splitlines()


def test_a_model_file_with_the_wrong_hash_is_refused(tmp_path):
    for spec in liveness_module.MODEL_SPECS:
        (tmp_path / spec.filename).write_bytes(b"not the published model")
    with pytest.raises(RuntimeError, match="integrity"):
        MiniFASNetLiveness(tmp_path)
    with pytest.raises(RuntimeError):
        load_liveness_checker(MODE_ENFORCE, model_dir=tmp_path)


# ------------------------------------------------------------------------------
# Preprocessing and scoring (synthetic arrays, fake ONNX sessions)
# ------------------------------------------------------------------------------


def test_crop_box_is_enlarged_around_the_face_and_stays_inside_the_frame():
    # 81x101 face in a 320x240 frame, scale 2.0 fits: 162x202 around centre (140.5, 110.5)
    assert scaled_crop_box(320, 240, FACE_BBOX, 2.0) == (59, 9, 221, 211)

    # Scale 4.0 does not fit; it is reduced to the largest that does (239/101)
    left, top, right, bottom = scaled_crop_box(320, 240, FACE_BBOX, 4.0)
    assert (top, bottom) == (0, 239)
    assert 0 <= left < right <= 319

    # A face in the corner: the box is shifted, not cut
    left, top, right, bottom = scaled_crop_box(320, 240, [0, 0, 40, 40], 2.7)
    assert (left, top) == (0, 0)
    assert right - left == pytest.approx(41 * 2.7, abs=1.5)
    assert right <= 319 and bottom <= 239


def test_model_input_is_bgr_float32_0_to_255_in_nchw():
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    frame[:, :, 0] = 10  # B
    frame[:, :, 1] = 20  # G
    frame[:, :, 2] = 250  # R
    tensor = prepare_model_input(frame, FACE_BBOX, 2.7)

    assert tensor.shape == (1, 3, 80, 80)
    assert tensor.dtype == np.float32
    assert tensor[0, 0].mean() == 10 and tensor[0, 1].mean() == 20 and tensor[0, 2].mean() == 250


class FakeSession:
    """Stands in for an ONNX Runtime session: returns fixed logits."""

    def __init__(self, logits):
        self._logits = np.array([logits], dtype=np.float32)
        self.seen_shapes = []

    def get_inputs(self):
        return [SimpleNamespace(name="input")]

    def run(self, output_names, feeds):
        self.seen_shapes.append(feeds["input"].shape)
        return [self._logits]


def test_score_is_the_mean_real_probability_of_the_two_models():
    # softmax([0, ln 3, 0]) -> real 0.6 ; softmax([0, 0, 0]) -> real 1/3
    sessions = [(FakeSession([0.0, float(np.log(3.0)), 0.0]), 2.7), (FakeSession([0.0, 0.0, 0.0]), 4.0)]
    expected = (0.6 + 1.0 / 3.0) / 2.0

    live = MiniFASNetLiveness(threshold=0.45, sessions=sessions).check(FRAME, FACE_BBOX)
    assert live.status == STATUS_LIVE
    assert live.score == pytest.approx(expected, abs=1e-6)

    spoof = MiniFASNetLiveness(threshold=0.50, sessions=sessions).check(FRAME, FACE_BBOX)
    assert spoof.status == STATUS_SPOOF
    assert spoof.score == pytest.approx(expected, abs=1e-6)
    assert all(session.seen_shapes[0] == (1, 3, 80, 80) for session, _ in sessions)


def test_a_score_equal_to_the_threshold_passes():
    sessions = [(FakeSession([0.0, 0.0, 0.0]), 2.7)]
    assert MiniFASNetLiveness(threshold=1.0 / 3.0 - 1e-9, sessions=sessions).check(FRAME, FACE_BBOX).is_live


def test_inference_failure_is_an_error_not_a_pass():
    class Broken(FakeSession):
        def run(self, output_names, feeds):
            raise RuntimeError("onnx failure")

    result = MiniFASNetLiveness(sessions=[(Broken([0, 0, 0]), 2.7)]).check(FRAME, FACE_BBOX)
    assert result.status == STATUS_ERROR
    assert result.is_live is False
    assert result.score is None
