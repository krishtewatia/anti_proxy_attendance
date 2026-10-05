"""Biometric recognition accuracy evaluation package."""

from .metrics import (
    DistributionStats,
    Histogram,
    SweepPoint,
    Rank1Metrics,
    ThreeVoteAnalysis,
    cosine_similarity,
    compute_distribution_stats,
    compute_histogram,
    compute_threshold_sweep,
    compute_rank1_identification,
    compute_condition_breakdown,
    compute_three_vote_confirmation,
)
from .evaluator import RecognitionEvaluator

__all__ = [
    "DistributionStats",
    "Histogram",
    "SweepPoint",
    "Rank1Metrics",
    "ThreeVoteAnalysis",
    "cosine_similarity",
    "compute_distribution_stats",
    "compute_histogram",
    "compute_threshold_sweep",
    "compute_rank1_identification",
    "compute_condition_breakdown",
    "compute_three_vote_confirmation",
    "RecognitionEvaluator",
]
