"""Metric and threshold logic of the liveness evaluation, on synthetic scores.

No images and no models: the scores are made up. Fast and safe for CI.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from evaluation.liveness_eval import (  # noqa: E402
    Attempt,
    attempt_accepted,
    frame_passes,
    metrics_at,
    recommend_threshold,
    upper_bound_when_zero,
)


def _attempt(category: str, *scores) -> Attempt:
    return Attempt(category=category, name="attempt", scores=list(scores))


def test_a_frame_without_a_face_never_passes():
    assert frame_passes(0.9, 0.5) is True
    assert frame_passes(0.5, 0.5) is True  # equality passes, as in the gate
    assert frame_passes(0.49, 0.5) is False
    assert frame_passes(None, 0.0) is False


def test_one_passing_frame_accepts_a_spoof_attempt():
    """One signed frame marks attendance, so any passing frame counts as an accepted attempt."""
    spoof = _attempt("print", 0.1, 0.2, 0.71, 0.1)
    assert attempt_accepted(spoof, 0.7) is True
    assert attempt_accepted(spoof, 0.8) is False


def test_consecutive_frames_requirement():
    isolated = _attempt("print", 0.9, 0.1, 0.9, 0.1)
    assert attempt_accepted(isolated, 0.7, consecutive=1) is True
    assert attempt_accepted(isolated, 0.7, consecutive=2) is False

    # A frame with no face breaks the run
    broken = _attempt("live", 0.9, None, 0.9)
    assert attempt_accepted(broken, 0.7, consecutive=2) is False
    assert attempt_accepted(_attempt("live", 0.1, 0.9, 0.95), 0.7, consecutive=2) is True


def test_rates_are_counted_per_frame_and_per_attempt():
    attempts = [
        _attempt("live", 0.9, 0.9, 0.4, 0.9),  # 1 of 4 frames rejected, attempt accepted
        _attempt("live", 0.3, 0.2, None),  # 2 of 2 scored frames rejected, attempt rejected
        _attempt("print", 0.1, 0.1, 0.1),
        _attempt("print", 0.1, 0.8, 0.1),  # one frame slips through -> attempt accepted
        _attempt("phone_screen", 0.2, 0.3),
    ]
    row = metrics_at(attempts, 0.5)

    assert row["live_frames"] == 6  # the no-face frame is not a scored frame
    assert row["frame_false_reject_rate"] == pytest.approx(3 / 6)
    assert row["attempt_false_reject_rate"] == pytest.approx(1 / 2)

    assert row["attacks"]["print"]["frame_false_accept_rate"] == pytest.approx(1 / 6)
    assert row["attacks"]["print"]["attempt_false_accept_rate"] == pytest.approx(1 / 2)
    assert row["attacks"]["print"]["attempts_accepted"] == 1
    assert row["attacks"]["phone_screen"]["attempt_false_accept_rate"] == 0.0
    assert row["attacks"]["laptop_replay"]["attempt_false_accept_rate"] is None  # no samples

    assert row["attack_frames"] == 8
    assert row["frame_false_accept_rate"] == pytest.approx(1 / 8)
    assert row["attack_attempts"] == 3
    assert row["attempt_false_accept_rate"] == pytest.approx(1 / 3)


def test_recommends_the_lowest_threshold_that_rejects_every_attack_attempt():
    attempts = [
        _attempt("live", 0.95, 0.97, 0.99),
        _attempt("live", 0.93, 0.96, 0.98),
        _attempt("print", 0.05, 0.30, 0.61),
        _attempt("phone_screen", 0.10, 0.20, 0.44),
        _attempt("laptop_replay", 0.02, 0.15, 0.33),
    ]
    result = recommend_threshold(attempts, thresholds=(0.3, 0.5, 0.6, 0.65, 0.7, 0.9))

    # 0.6 still lets the 0.61 print frame through; 0.65 is the first that does not
    assert result["threshold"] == 0.65
    assert result["metrics"]["attack_attempts_accepted"] == 0
    assert result["metrics"]["frame_false_reject_rate"] == 0.0


def test_no_threshold_is_recommended_when_live_and_spoof_scores_overlap():
    attempts = [
        _attempt("live", 0.40, 0.45, 0.50),
        _attempt("print", 0.60, 0.70, 0.80),  # scores higher than the live face
    ]
    result = recommend_threshold(attempts, thresholds=(0.3, 0.5, 0.7, 0.9))

    assert result["threshold"] is None
    assert "no threshold" in result["reason"]


def test_a_threshold_that_rejects_a_whole_live_attempt_is_not_recommended():
    attempts = [
        _attempt("live", 0.99, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99) for _ in range(30)
    ]
    attempts.append(_attempt("live", 0.50, 0.50))  # under 5% of live frames, but a whole attempt
    attempts.append(_attempt("print", 0.60))
    result = recommend_threshold(attempts, thresholds=(0.4, 0.7))

    assert result["threshold"] is None


def test_nothing_is_recommended_without_both_live_and_attack_samples():
    assert recommend_threshold([_attempt("live", 0.9)])["threshold"] is None
    assert recommend_threshold([_attempt("print", 0.1)])["threshold"] is None
    assert recommend_threshold([])["threshold"] is None


def test_zero_observed_failures_still_leaves_an_upper_bound():
    # 0 of 100 accepted does not mean 0%: the 95% bound is about 3%
    assert upper_bound_when_zero(100) == pytest.approx(0.0295, abs=0.001)
    assert upper_bound_when_zero(15) == pytest.approx(0.181, abs=0.002)
    assert upper_bound_when_zero(0) is None
