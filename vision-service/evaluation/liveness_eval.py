#!/usr/bin/env python3
"""Measure the liveness gate on a small, locally captured attack set.

Reads frames from ``$VISION_FIXTURES_DIR/liveness`` (never from the repository):

    liveness/
      live/attempt_01/*.jpg            a real face in front of the camera
      print/attempt_01/*.jpg           a printed photo
      phone_screen/attempt_01/*.jpg    a photo shown on a phone screen
      laptop_replay/attempt_01/*.jpg   a video replayed on a laptop screen

One sub-folder is one attempt: one continuous presentation of a few seconds.
See docs/evaluation/liveness_capture_guide.md.

For every frame the largest detected face is scored by the MiniFASNet
ensemble. The report gives, for a range of thresholds:

  * false accept rate (spoof frames scored live), per attack type
  * false reject rate (live frames scored spoof)
  * the same per attempt, which is what matters in use: one accepted frame
    marks attendance, so a spoof attempt counts as accepted if ANY of its
    frames passes, and a live attempt counts as rejected only if ALL fail

and recommends a threshold. Only scores, counts and file counts are printed or
written; no image data.

Usage (from vision-service/):

    VISION_FIXTURES_DIR=/path/to/fixtures python evaluation/liveness_eval.py
    python evaluation/liveness_eval.py --data /path/to/liveness --json-out report.json
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import sys
from typing import Optional, Sequence

LIVE_CATEGORY = "live"
ATTACK_CATEGORIES = ("print", "phone_screen", "laptop_replay")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
# A live student is in view for several frames, so a few rejected frames cost
# almost nothing; a single accepted spoof frame marks attendance.
MAX_FRAME_FALSE_REJECT_RATE = 0.05
DEFAULT_THRESHOLDS = tuple(round(0.05 * i, 2) for i in range(1, 20)) + (0.97, 0.98, 0.99)


@dataclass
class Attempt:
    """Scores of one presentation. ``None`` means no face was detected in that frame."""

    category: str
    name: str
    scores: list[Optional[float]] = field(default_factory=list)

    @property
    def scored(self) -> list[float]:
        return [s for s in self.scores if s is not None]


def frame_passes(score: Optional[float], threshold: float) -> bool:
    """A frame without a detected face cannot be recognized, so it never passes."""
    return score is not None and score >= threshold


def attempt_accepted(attempt: Attempt, threshold: float, consecutive: int = 1) -> bool:
    """True if the attempt would get a result signed: ``consecutive`` passing frames in a row."""
    run = 0
    for score in attempt.scores:
        run = run + 1 if frame_passes(score, threshold) else 0
        if run >= consecutive:
            return True
    return False


def _rate(numerator: int, denominator: int) -> Optional[float]:
    return None if denominator == 0 else numerator / denominator


def metrics_at(attempts: Sequence[Attempt], threshold: float, consecutive: int = 1) -> dict:
    """False accept / false reject rates at one threshold, per frame and per attempt."""
    live = [a for a in attempts if a.category == LIVE_CATEGORY]
    live_frames = [s for a in live for s in a.scored]
    live_frame_rejects = sum(1 for s in live_frames if s < threshold)
    live_attempt_rejects = sum(1 for a in live if not attempt_accepted(a, threshold, consecutive))

    result = {
        "threshold": threshold,
        "consecutive_frames_required": consecutive,
        "frame_false_reject_rate": _rate(live_frame_rejects, len(live_frames)),
        "live_frames": len(live_frames),
        "attempt_false_reject_rate": _rate(live_attempt_rejects, len(live)),
        "live_attempts": len(live),
        "attacks": {},
    }

    total_frames = total_frame_accepts = total_attempts = total_attempt_accepts = 0
    for category in ATTACK_CATEGORIES:
        group = [a for a in attempts if a.category == category]
        frames = [s for a in group for s in a.scored]
        frame_accepts = sum(1 for s in frames if s >= threshold)
        attempt_accepts = sum(1 for a in group if attempt_accepted(a, threshold, consecutive))
        result["attacks"][category] = {
            "frame_false_accept_rate": _rate(frame_accepts, len(frames)),
            "frames": len(frames),
            "attempt_false_accept_rate": _rate(attempt_accepts, len(group)),
            "attempts": len(group),
            "attempts_accepted": attempt_accepts,
        }
        total_frames += len(frames)
        total_frame_accepts += frame_accepts
        total_attempts += len(group)
        total_attempt_accepts += attempt_accepts

    result["frame_false_accept_rate"] = _rate(total_frame_accepts, total_frames)
    result["attack_frames"] = total_frames
    result["attempt_false_accept_rate"] = _rate(total_attempt_accepts, total_attempts)
    result["attack_attempts"] = total_attempts
    result["attack_attempts_accepted"] = total_attempt_accepts
    return result


def recommend_threshold(
    attempts: Sequence[Attempt],
    thresholds: Sequence[float] = DEFAULT_THRESHOLDS,
    consecutive: int = 1,
    max_frame_false_reject_rate: float = MAX_FRAME_FALSE_REJECT_RATE,
) -> dict:
    """Lowest threshold with no accepted attack attempt and an acceptable false reject rate.

    Returns ``{"threshold": None, "reason": ...}`` when no threshold satisfies
    both, rather than recommending a compromise silently.
    """
    table = [metrics_at(attempts, t, consecutive) for t in sorted(thresholds)]
    if not table or table[0]["attack_attempts"] == 0 or table[0]["live_frames"] == 0:
        return {"threshold": None, "reason": "need both live and attack samples", "table": table}

    for row in table:
        no_spoof_accepted = row["attack_attempts_accepted"] == 0
        live_ok = (
            row["frame_false_reject_rate"] <= max_frame_false_reject_rate
            and row["attempt_false_reject_rate"] == 0
        )
        if no_spoof_accepted and live_ok:
            return {"threshold": row["threshold"], "reason": "meets both criteria", "metrics": row, "table": table}

    return {
        "threshold": None,
        "reason": (
            "no threshold rejects every attack attempt while keeping live false rejects "
            f"at or below {max_frame_false_reject_rate:.0%} per frame"
        ),
        "table": table,
    }


def upper_bound_when_zero(trials: int, confidence: float = 0.95) -> Optional[float]:
    """Upper confidence bound on a rate when 0 of ``trials`` were observed ("rule of three")."""
    if trials <= 0:
        return None
    return 1.0 - (1.0 - confidence) ** (1.0 / trials)


# ------------------------------------------------------------------ data loading (needs models)


def discover(data_dir: Path) -> list[tuple[str, str, list[Path]]]:
    found = []
    for category in (LIVE_CATEGORY, *ATTACK_CATEGORIES):
        category_dir = data_dir / category
        if not category_dir.is_dir():
            continue
        for attempt_dir in sorted(p for p in category_dir.iterdir() if p.is_dir()):
            files = sorted(f for f in attempt_dir.iterdir() if f.suffix.lower() in IMAGE_SUFFIXES)
            if files:
                found.append((category, attempt_dir.name, files))
    return found


def score_dataset(data_dir: Path, model_dir: Optional[Path]) -> list[Attempt]:
    import cv2

    service_root = Path(__file__).resolve().parent.parent
    if str(service_root) not in sys.path:
        sys.path.insert(0, str(service_root))
    from camera.liveness import DEFAULT_MODEL_DIR, MiniFASNetLiveness
    from pipeline.live_cv_pipeline import create_face_analysis, swap_scrfd_detector

    app = create_face_analysis(
        name="buffalo_l", allowed_modules=["detection", "recognition"], intra_threads=4, inter_threads=2
    )
    swap_scrfd_detector(app, detector_type="0.5g", intra_threads=4, inter_threads=2)
    # Threshold 0 so every face gets a score; thresholds are applied afterwards.
    checker = MiniFASNetLiveness(model_dir or DEFAULT_MODEL_DIR, threshold=0.0)

    attempts = []
    for category, name, files in discover(data_dir):
        attempt = Attempt(category=category, name=name)
        for path in files:
            image = cv2.imread(str(path))
            faces = app.get(image) if image is not None else []
            if not faces:
                attempt.scores.append(None)
                continue
            face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
            attempt.scores.append(checker.check(image, face.bbox).score)
        attempts.append(attempt)
    return attempts


# ------------------------------------------------------------------ report


def _pct(value: Optional[float]) -> str:
    return "  n/a" if value is None else f"{value * 100:5.1f}%"


def print_report(attempts: Sequence[Attempt], consecutive: int) -> dict:
    print("Samples (attempts / frames / frames with no face detected):")
    for category in (LIVE_CATEGORY, *ATTACK_CATEGORIES):
        group = [a for a in attempts if a.category == category]
        frames = sum(len(a.scores) for a in group)
        no_face = sum(1 for a in group for s in a.scores if s is None)
        scored = sorted(s for a in group for s in a.scored)
        spread = (
            f"  score min/median/max {scored[0]:.3f}/{scored[len(scored) // 2]:.3f}/{scored[-1]:.3f}"
            if scored
            else ""
        )
        print(f"  {category:<14} {len(group):>3} / {frames:>4} / {no_face:>3}{spread}")

    recommendation = recommend_threshold(attempts, consecutive=consecutive)
    print(f"\nPer threshold (a result needs {consecutive} passing frame(s) in a row):")
    print("  thr   | live: frame FRR  attempt FRR | spoof: frame FAR  attempt FAR | " + "  ".join(ATTACK_CATEGORIES))
    for row in recommendation["table"]:
        per_attack = "  ".join(
            f"{row['attacks'][c]['attempts_accepted']}/{row['attacks'][c]['attempts']}".center(len(c))
            for c in ATTACK_CATEGORIES
        )
        print(
            f"  {row['threshold']:.2f}  |       {_pct(row['frame_false_reject_rate'])}       "
            f"{_pct(row['attempt_false_reject_rate'])} |        {_pct(row['frame_false_accept_rate'])}       "
            f"{_pct(row['attempt_false_accept_rate'])} | {per_attack}"
        )

    print()
    if recommendation["threshold"] is None:
        print(f"No threshold recommended: {recommendation['reason']}.")
    else:
        chosen = recommendation["metrics"]
        bound = upper_bound_when_zero(chosen["attack_attempts"])
        print(f"Recommended threshold: {recommendation['threshold']:.2f}")
        print(
            f"  spoof attempts accepted: 0 of {chosen['attack_attempts']} "
            f"(95% upper bound on the true rate: {_pct(bound).strip()})"
        )
        print(
            f"  live frames rejected: {_pct(chosen['frame_false_reject_rate']).strip()} of {chosen['live_frames']}; "
            f"live attempts rejected: {_pct(chosen['attempt_false_reject_rate']).strip()} of {chosen['live_attempts']}"
        )
    print("\nLimits: one person, one camera, a small attack set. This is not a general accuracy claim.")
    return recommendation


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure the liveness gate on a local attack set")
    parser.add_argument("--data", type=Path, help="Folder with live/ print/ phone_screen/ laptop_replay/")
    parser.add_argument("--model-dir", type=Path, help="Folder holding the two liveness ONNX files")
    parser.add_argument("--consecutive", type=int, default=1, help="Passing frames in a row needed (default 1)")
    parser.add_argument("--json-out", type=Path, help="Write scores-free metrics as JSON to this file")
    args = parser.parse_args()

    data_dir = args.data
    if data_dir is None and os.environ.get("VISION_FIXTURES_DIR"):
        data_dir = Path(os.environ["VISION_FIXTURES_DIR"]) / "liveness"
    if data_dir is None or not data_dir.is_dir():
        print("ERROR: pass --data or set VISION_FIXTURES_DIR (expects a 'liveness' folder in it).", file=sys.stderr)
        return 2

    attempts = score_dataset(data_dir, args.model_dir)
    if not attempts:
        print(f"ERROR: no attempts found under {data_dir}.", file=sys.stderr)
        return 2

    recommendation = print_report(attempts, args.consecutive)
    if args.json_out:
        args.json_out.write_text(json.dumps(recommendation, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
