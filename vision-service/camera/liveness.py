"""Passive liveness (anti-spoofing) gate for the frame recognition path.

A recognized face is checked here before the vision service signs a
recognition result. In ``enforce`` mode a face that is not judged live never
produces a signed result. In ``observe`` mode the check runs and is logged,
but results are still signed, marked as ``unchecked``.

Model: the two-model MiniFASNet ensemble from
https://github.com/minivision-ai/Silent-Face-Anti-Spoofing (Apache-2.0),
converted to ONNX. See docs/adr/ADR-011-passive-liveness-gate.md.

Nothing in this module logs or stores image data, crops or embeddings.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Optional, Protocol, Sequence

import numpy as np

logger = logging.getLogger(__name__)

MODE_OBSERVE = "observe"
MODE_ENFORCE = "enforce"
LIVENESS_MODES = (MODE_OBSERVE, MODE_ENFORCE)
# Observe until the threshold has been calibrated on a measured attack set
# (ADR-011). Changing this default is a deliberate, separately reviewed step.
DEFAULT_LIVENESS_MODE = MODE_OBSERVE

# Attestation values carried inside the signed recognition result.
ATTESTATION_PASSED = "passed"
ATTESTATION_UNCHECKED = "unchecked"

STATUS_LIVE = "live"
STATUS_SPOOF = "spoof"
STATUS_ERROR = "error"

# Provisional: upstream accepts a face when "real" is the most likely of three
# classes. To be replaced by the calibrated value (ADR-011, evaluation section).
DEFAULT_LIVENESS_THRESHOLD = 0.5
REAL_CLASS_INDEX = 1
INPUT_SIZE = 80
DEFAULT_MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "liveness"


@dataclass(frozen=True)
class LivenessModelSpec:
    filename: str
    crop_scale: float
    sha256: str


# Files published as the ``liveness-models-v1`` release asset of this repository.
MODEL_SPECS: tuple[LivenessModelSpec, ...] = (
    LivenessModelSpec(
        "minifasnet_v2_scale2.7_80x80.onnx",
        2.7,
        "c058068e54189e467aff1991442b8cf5c75220ab0356f49c9508aaff9e3e91e6",
    ),
    LivenessModelSpec(
        "minifasnet_v1se_scale4.0_80x80.onnx",
        4.0,
        "2be5c295aefee7bf6356edbf6303b1827aab5d793e4a1898de4e11fb0fa2db35",
    ),
)


@dataclass(frozen=True)
class LivenessResult:
    """Outcome of one liveness check. ``score`` is the mean probability of "real face"."""

    status: str
    score: Optional[float] = None
    reason: Optional[str] = None

    @property
    def is_live(self) -> bool:
        return self.status == STATUS_LIVE


@dataclass(frozen=True)
class GateDecision:
    """What the recognition path may do with one recognized face.

    ``allow_signing`` False means no signed result may be produced.
    ``attestation`` is the value to sign when signing is allowed.
    """

    allow_signing: bool
    attestation: Optional[str]
    result: LivenessResult


class LivenessChecker(Protocol):
    def check(self, frame_bgr: np.ndarray, bbox_xyxy: Sequence[float]) -> LivenessResult: ...


def resolve_liveness_mode(value: Optional[str] = None) -> str:
    """Return the configured mode. An unknown value is an error, never a silent default."""
    raw = (value if value is not None else os.getenv("LIVENESS_MODE", "")).strip().lower()
    if not raw:
        return DEFAULT_LIVENESS_MODE
    if raw not in LIVENESS_MODES:
        raise RuntimeError(
            f"LIVENESS_MODE must be one of {', '.join(LIVENESS_MODES)} (found '{raw}')."
        )
    return raw


def resolve_liveness_threshold(value: Optional[str] = None) -> float:
    raw = value if value is not None else os.getenv("LIVENESS_THRESHOLD", "")
    if raw is None or not str(raw).strip():
        return DEFAULT_LIVENESS_THRESHOLD
    try:
        threshold = float(raw)
    except ValueError as exc:
        raise RuntimeError("LIVENESS_THRESHOLD must be a number between 0 and 1.") from exc
    if not 0.0 <= threshold <= 1.0:
        raise RuntimeError("LIVENESS_THRESHOLD must be a number between 0 and 1.")
    return threshold


def scaled_crop_box(
    frame_width: int, frame_height: int, bbox_xyxy: Sequence[float], scale: float
) -> tuple[int, int, int, int]:
    """Enlarge a face box around its centre by ``scale`` and keep it inside the frame.

    Same geometry as upstream ``CropImage._get_new_box``: the scale is reduced
    if the enlarged box would not fit, and the box is shifted, not shrunk, when
    it touches an edge. Returns inclusive (left, top, right, bottom).
    """
    x1, y1, x2, y2 = (float(v) for v in bbox_xyxy)
    box_w = max(x2 - x1 + 1.0, 1.0)
    box_h = max(y2 - y1 + 1.0, 1.0)

    scale = min((frame_height - 1) / box_h, min((frame_width - 1) / box_w, scale))
    new_w = box_w * scale
    new_h = box_h * scale
    centre_x = box_w / 2 + x1
    centre_y = box_h / 2 + y1

    left = centre_x - new_w / 2
    top = centre_y - new_h / 2
    right = centre_x + new_w / 2
    bottom = centre_y + new_h / 2

    if left < 0:
        right -= left
        left = 0
    if top < 0:
        bottom -= top
        top = 0
    if right > frame_width - 1:
        left -= right - frame_width + 1
        right = frame_width - 1
    if bottom > frame_height - 1:
        top -= bottom - frame_height + 1
        bottom = frame_height - 1

    return int(max(left, 0)), int(max(top, 0)), int(right), int(bottom)


def prepare_model_input(
    frame_bgr: np.ndarray, bbox_xyxy: Sequence[float], scale: float
) -> np.ndarray:
    """Crop, resize to 80x80 and lay out as float32 [1, 3, 80, 80] (BGR, 0-255)."""
    import cv2

    height, width = frame_bgr.shape[:2]
    left, top, right, bottom = scaled_crop_box(width, height, bbox_xyxy, scale)
    patch = frame_bgr[top : bottom + 1, left : right + 1]
    if patch.size == 0:
        raise ValueError("empty liveness crop")
    resized = cv2.resize(patch, (INPUT_SIZE, INPUT_SIZE))
    return np.ascontiguousarray(resized.transpose(2, 0, 1)[None], dtype=np.float32)


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits)
    exp = np.exp(shifted)
    return exp / np.sum(exp)


class MiniFASNetLiveness:
    """Runs the MiniFASNet ensemble with ONNX Runtime on CPU."""

    def __init__(
        self,
        model_dir: Path | str = DEFAULT_MODEL_DIR,
        threshold: float = DEFAULT_LIVENESS_THRESHOLD,
        intra_threads: int = 2,
        sessions: Optional[Sequence[tuple[Any, float]]] = None,
    ) -> None:
        self.threshold = float(threshold)
        if sessions is not None:
            # Injected in tests so no model file is needed.
            self._sessions = list(sessions)
            return

        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = intra_threads
        options.inter_op_num_threads = 1

        directory = Path(model_dir)
        self._sessions = []
        for spec in MODEL_SPECS:
            path = directory / spec.filename
            if not path.is_file():
                raise FileNotFoundError(f"Liveness model not found: {path}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != spec.sha256:
                raise RuntimeError(
                    f"Liveness model {spec.filename} failed its integrity check (unexpected SHA-256)."
                )
            session = ort.InferenceSession(
                str(path), sess_options=options, providers=["CPUExecutionProvider"]
            )
            self._sessions.append((session, spec.crop_scale))

    def check(self, frame_bgr: np.ndarray, bbox_xyxy: Sequence[float]) -> LivenessResult:
        try:
            probabilities = np.zeros(3, dtype=np.float64)
            for session, scale in self._sessions:
                tensor = prepare_model_input(frame_bgr, bbox_xyxy, scale)
                input_name = session.get_inputs()[0].name
                logits = np.asarray(session.run(None, {input_name: tensor})[0][0], dtype=np.float64)
                probabilities += _softmax(logits)
            score = float(probabilities[REAL_CLASS_INDEX] / len(self._sessions))
        except Exception as exc:
            # The type only: an exception message could describe the input.
            logger.warning("Liveness check failed: %s", type(exc).__name__)
            return LivenessResult(status=STATUS_ERROR, reason="inference_failed")

        if score >= self.threshold:
            return LivenessResult(status=STATUS_LIVE, score=score)
        return LivenessResult(status=STATUS_SPOOF, score=score, reason="below_threshold")


def evaluate_liveness_gate(
    mode: str,
    checker: Optional[LivenessChecker],
    frame_bgr: np.ndarray,
    bbox_xyxy: Sequence[float],
) -> GateDecision:
    """Decide whether a recognized face may produce a signed result.

    enforce: only a face judged live is signed, with ``passed``. A spoof, an
             inference error or a missing model all mean no signature.
    observe: the check runs if a model is loaded, and the result is signed as
             ``unchecked`` whatever the outcome.
    """
    if checker is None:
        result = LivenessResult(status=STATUS_ERROR, reason="model_unavailable")
    else:
        try:
            result = checker.check(frame_bgr, bbox_xyxy)
        except Exception as exc:
            logger.warning("Liveness checker raised: %s", type(exc).__name__)
            result = LivenessResult(status=STATUS_ERROR, reason="checker_failed")

    if mode == MODE_ENFORCE:
        if result.is_live:
            return GateDecision(True, ATTESTATION_PASSED, result)
        return GateDecision(False, None, result)
    return GateDecision(True, ATTESTATION_UNCHECKED, result)


def load_liveness_checker(
    mode: str,
    model_dir: Optional[Path | str] = None,
    threshold: Optional[float] = None,
) -> Optional[LivenessChecker]:
    """Load the model for the configured mode.

    enforce fails closed: without a usable model the service must not start.
    observe starts without one, logging that nothing is being checked.
    """
    directory = Path(model_dir or os.getenv("LIVENESS_MODEL_DIR") or DEFAULT_MODEL_DIR)
    limit = resolve_liveness_threshold() if threshold is None else threshold
    try:
        checker = MiniFASNetLiveness(directory, threshold=limit)
    except Exception as exc:
        if mode == MODE_ENFORCE:
            raise RuntimeError(
                f"LIVENESS_MODE=enforce but the liveness model could not be loaded from {directory}: {exc}"
            ) from exc
        logger.warning(
            "Liveness model not loaded (%s); observe mode continues without checking.", exc
        )
        return None
    logger.info("Liveness model loaded (mode=%s, threshold=%.2f)", mode, limit)
    return checker
