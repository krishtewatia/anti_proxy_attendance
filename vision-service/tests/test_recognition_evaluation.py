"""Unit and regression tests for biometric face recognition accuracy evaluation."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from evaluation.metrics import (
    DistributionStats,
    Histogram,
    Rank1Metrics,
    SweepPoint,
    ThreeVoteAnalysis,
    compute_condition_breakdown,
    compute_distribution_stats,
    compute_histogram,
    compute_rank1_identification,
    compute_three_vote_confirmation,
    compute_threshold_sweep,
    cosine_similarity,
    find_eer,
)
from evaluation.evaluator import RecognitionEvaluator
from evaluation.synthetic import generate_synthetic_evaluation_data
from pipeline.live_cv_pipeline import LiveCVPipeline


class TestCosineSimilarity(unittest.TestCase):
    """Test cosine similarity calculation edge cases."""

    def test_identical_vectors(self):
        v = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        sim = cosine_similarity(v, v)
        self.assertAlmostEqual(sim, 1.0, places=5)

    def test_orthogonal_vectors(self):
        v1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        v2 = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        sim = cosine_similarity(v1, v2)
        self.assertAlmostEqual(sim, 0.0, places=5)

    def test_opposite_vectors(self):
        v1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        v2 = np.array([-1.0, 0.0, 0.0], dtype=np.float32)
        sim = cosine_similarity(v1, v2)
        self.assertAlmostEqual(sim, -1.0, places=5)

    def test_zero_vector(self):
        v1 = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        v2 = np.array([1.0, 1.0, 1.0], dtype=np.float32)
        sim = cosine_similarity(v1, v2)
        self.assertEqual(sim, 0.0)


class TestDistributionMetrics(unittest.TestCase):
    """Test statistical metrics, quantiles, and histograms."""

    def test_empty_scores(self):
        stats = compute_distribution_stats([])
        self.assertEqual(stats.count, 0)
        self.assertEqual(stats.mean, 0.0)

        hist = compute_histogram([])
        self.assertEqual(hist.total, 0)
        self.assertIn("No data", hist.render_ascii())

    def test_known_distribution_stats(self):
        scores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        stats = compute_distribution_stats(scores)
        self.assertEqual(stats.count, 9)
        self.assertAlmostEqual(stats.min, 0.1, places=4)
        self.assertAlmostEqual(stats.max, 0.9, places=4)
        self.assertAlmostEqual(stats.mean, 0.5, places=4)
        self.assertAlmostEqual(stats.median, 0.5, places=4)

    def test_histogram_rendering(self):
        scores = [0.65, 0.68, 0.72, 0.75, 0.78, 0.82]
        hist = compute_histogram(scores, bins=5, min_val=0.5, max_val=1.0)
        self.assertEqual(hist.total, 6)
        rendered = hist.render_ascii()
        self.assertIn("#", rendered)
        self.assertIn("%", rendered)


class TestThresholdSweep(unittest.TestCase):
    """Test FAR, FRR, GAR, Precision, Recall, and F1 calculations."""

    def test_threshold_sweep_monotonicity(self):
        # Genuine scores clustered high (0.60 to 0.85)
        # Impostor scores clustered low (-0.10 to 0.15)
        genuine = [0.65, 0.70, 0.75, 0.80, 0.85]
        impostor = [-0.05, 0.00, 0.05, 0.10, 0.15]
        thresholds = [0.0, 0.2, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]

        sweep = compute_threshold_sweep(genuine, impostor, thresholds)
        self.assertEqual(len(sweep), len(thresholds))

        # Check monotonicity: as threshold increases, FAR <= previous, FRR >= previous
        for i in range(1, len(sweep)):
            prev = sweep[i - 1]
            curr = sweep[i]
            self.assertLessEqual(curr.far, prev.far + 1e-6)
            self.assertGreaterEqual(curr.frr, prev.frr - 1e-6)

        # At threshold 0.50, separation is 100%
        pt_50 = next(p for p in sweep if p.threshold == 0.5)
        self.assertAlmostEqual(pt_50.gar, 1.0)
        self.assertAlmostEqual(pt_50.far, 0.0)
        self.assertAlmostEqual(pt_50.frr, 0.0)
        self.assertAlmostEqual(pt_50.precision, 1.0)
        self.assertAlmostEqual(pt_50.f1_score, 1.0)

    def test_find_eer(self):
        genuine = [0.4, 0.5, 0.6, 0.7]
        impostor = [0.3, 0.4, 0.5, 0.6]
        sweep = compute_threshold_sweep(genuine, impostor, thresholds=[0.3, 0.4, 0.5, 0.6, 0.7])
        eer_point = find_eer(sweep)
        self.assertIsNotNone(eer_point)
        self.assertAlmostEqual(eer_point.threshold, 0.5, delta=0.1)


class TestRank1AndOpenSetIdentification(unittest.TestCase):
    """Test Rank-1 closed-set identification and open-set unknown rejection."""

    def test_rank1_metrics(self):
        probe_results = [
            # Closed-set correct
            {"true_subject": "person_01", "predicted_subject": "person_01", "top_similarity": 0.75, "runner_up_similarity": 0.20},
            # Closed-set misidentified
            {"true_subject": "person_02", "predicted_subject": "person_03", "top_similarity": 0.65, "runner_up_similarity": 0.20},
            # Closed-set rejected due to low similarity
            {"true_subject": "person_03", "predicted_subject": "person_03", "top_similarity": 0.45, "runner_up_similarity": 0.10},
            # Open-set unknown correctly rejected (sim < threshold)
            {"true_subject": "UNKNOWN", "predicted_subject": "person_01", "top_similarity": 0.35, "runner_up_similarity": 0.10},
            # Open-set unknown falsely accepted (sim >= threshold and margin >= 0.15)
            {"true_subject": "UNKNOWN", "predicted_subject": "person_02", "top_similarity": 0.60, "runner_up_similarity": 0.10},
        ]

        metrics = compute_rank1_identification(probe_results, threshold=0.50, min_margin=0.15)
        self.assertEqual(metrics.total_probes, 5)
        self.assertEqual(metrics.closed_set_probes, 3)
        self.assertEqual(metrics.open_set_probes, 2)
        self.assertEqual(metrics.correct_identifications, 1)  # person_01
        self.assertEqual(metrics.false_identifications, 1)   # person_02
        self.assertEqual(metrics.false_rejections, 1)        # person_03
        self.assertEqual(metrics.correct_unknown_rejections, 1)
        self.assertEqual(metrics.false_unknown_acceptances, 1)


class TestConditionBreakdown(unittest.TestCase):
    """Test slicing probe performance by condition metadata."""

    def test_condition_grouping(self):
        probe_results = [
            {"true_subject": "p1", "predicted_subject": "p1", "top_similarity": 0.80, "condition": {"lighting": "normal", "pose": "frontal"}},
            {"true_subject": "p1", "predicted_subject": "p1", "top_similarity": 0.65, "condition": {"lighting": "dim", "pose": "frontal"}},
            {"true_subject": "p2", "predicted_subject": "p2", "top_similarity": 0.70, "condition": {"lighting": "normal", "pose": "yaw"}},
        ]
        breakdown = compute_condition_breakdown(probe_results, threshold=0.50)
        self.assertIn("lighting", breakdown)
        self.assertIn("pose", breakdown)
        self.assertEqual(breakdown["lighting"]["normal"]["count"], 2)
        self.assertEqual(breakdown["lighting"]["dim"]["count"], 1)
        self.assertEqual(breakdown["lighting"]["normal"]["gar_pct"], 100.0)


class TestThreeVoteConfirmation(unittest.TestCase):
    """Test mathematical and Monte Carlo multi-frame 3-vote confirmation modeling."""

    def test_three_vote_reduces_impostor_false_accepts(self):
        # Suppose single-frame FAR is 1% (0.01) across 50 students
        analysis = compute_three_vote_confirmation(
            single_frame_far=0.01,
            single_frame_gar=0.95,
            gallery_size=50,
            track_frames_evaluated=15,
            min_supporting_votes=3,
            run_monte_carlo=True,
            mc_iterations=5000,
        )

        # Multi-frame false confirmation should be orders of magnitude lower than 0.01
        self.assertLess(analysis.prob_wrong_identity_confirmed, 1e-4)
        # Genuine confirmation should be > 99%
        self.assertGreater(analysis.prob_genuine_confirmed, 0.99)

        # Simulation output should be close to theoretical
        if analysis.simulation_wrong_identity_confirmed is not None:
            self.assertLess(analysis.simulation_wrong_identity_confirmed, 0.005)
        if analysis.simulation_genuine_confirmed is not None:
            self.assertGreater(analysis.simulation_genuine_confirmed, 0.98)


class TestEvaluatorEndToEndFixture(unittest.TestCase):
    """Test end-to-end evaluation harness on a tiny fixture."""

    def test_evaluate_tiny_fixture(self):
        gallery, probes, unknowns = generate_synthetic_evaluation_data(
            num_enrolled=4,
            probes_per_enrolled=3,
            num_unknown_probes=4,
            seed=123,
        )
        self.assertEqual(len(gallery), 4)
        self.assertEqual(len(probes), 4)
        self.assertEqual(len(unknowns), 4)

        evaluator = RecognitionEvaluator(
            recommended_threshold=0.50,
            min_margin=0.15,
            min_supporting_votes=3,
        )
        report = evaluator.evaluate_from_embeddings(
            enrolled_gallery=gallery,
            probe_embeddings=probes,
            unknown_embeddings=unknowns,
        )

        # Check report structures
        self.assertEqual(report.dataset_summary["enrolled_identities"], 4)
        self.assertEqual(report.dataset_summary["total_probes"], 16)  # 4*3 + 4
        self.assertGreater(report.genuine_stats.mean, 0.60)
        self.assertLess(report.impostor_stats.mean, 0.20)

        # Check markdown generation
        md = report.to_markdown()
        self.assertIn("# Biometric Face Recognition Accuracy & Threshold Validation Report", md)
        self.assertIn("## 1. Dataset Summary", md)
        self.assertIn("## 8. Limitations & Scope", md)
        self.assertIn("Small Dataset Caveat", md)

        # Ensure no raw embedding matrices or vectors are leaked into markdown
        self.assertNotIn("dtype=float32", md)
        self.assertNotIn("array([", md)


class TestPipelineConfigurableThreshold(unittest.TestCase):
    """Test LiveCVPipeline reads configurable threshold correctly."""

    def test_default_threshold_is_point_five(self):
        # Mock FaceAnalysis
        mock_app = MagicMock()
        pipeline = LiveCVPipeline(app=mock_app, gallery={})
        self.assertEqual(pipeline.similarity_threshold, 0.50)
        self.assertEqual(pipeline.min_margin, 0.15)

    def test_explicit_threshold_override(self):
        mock_app = MagicMock()
        pipeline = LiveCVPipeline(app=mock_app, gallery={}, similarity_threshold=0.42, min_margin=0.20)
        self.assertEqual(pipeline.similarity_threshold, 0.42)
        self.assertEqual(pipeline.min_margin, 0.20)

    def test_env_var_threshold_override(self):
        mock_app = MagicMock()
        orig = os.environ.get("RECOGNITION_SIMILARITY_THRESHOLD")
        try:
            os.environ["RECOGNITION_SIMILARITY_THRESHOLD"] = "0.58"
            pipeline = LiveCVPipeline(app=mock_app, gallery={})
            self.assertEqual(pipeline.similarity_threshold, 0.58)
        finally:
            if orig is not None:
                os.environ["RECOGNITION_SIMILARITY_THRESHOLD"] = orig
            else:
                os.environ.pop("RECOGNITION_SIMILARITY_THRESHOLD", None)
