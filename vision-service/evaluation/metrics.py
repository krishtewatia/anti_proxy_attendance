"""Statistical and metric calculations for biometric face recognition evaluation."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np


@dataclass
class DistributionStats:
    """Descriptive statistics for a set of similarity scores."""
    count: int
    min: float
    max: float
    mean: float
    median: float
    std: float
    p5: float
    p25: float
    p75: float
    p95: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "count": self.count,
            "min": round(self.min, 4),
            "max": round(self.max, 4),
            "mean": round(self.mean, 4),
            "median": round(self.median, 4),
            "std": round(self.std, 4),
            "p5": round(self.p5, 4),
            "p25": round(self.p25, 4),
            "p75": round(self.p75, 4),
            "p95": round(self.p95, 4),
        }


@dataclass
class Histogram:
    """Frequency histogram of similarity scores."""
    bin_edges: List[float]
    counts: List[int]
    total: int

    def render_ascii(self, max_bar_width: int = 30) -> str:
        """Render a readable text-based horizontal histogram."""
        if self.total == 0 or not self.counts:
            return "No data for histogram"

        max_count = max(self.counts) if self.counts else 1
        lines = []
        for i, count in enumerate(self.counts):
            low = self.bin_edges[i]
            high = self.bin_edges[i + 1]
            pct = (count / self.total) * 100.0 if self.total > 0 else 0.0
            bar_len = int((count / max_count) * max_bar_width) if max_count > 0 else 0
            bar = "#" * bar_len
            lines.append(f"[{low:+5.2f}, {high:+5.2f}) | {bar:<{max_bar_width}} | {count:5d} ({pct:5.1f}%)")
        return "\n".join(lines)


@dataclass
class SweepPoint:
    """Evaluation metrics at a single similarity threshold."""
    threshold: float
    true_accepts: int
    false_rejects: int
    false_accepts: int
    true_rejects: int
    gar: float  # Genuine Accept Rate (1 - FRR)
    frr: float  # False Reject Rate
    far: float  # False Accept Rate
    trr: float  # True Reject Rate
    precision: float
    recall: float
    f1_score: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "threshold": round(self.threshold, 3),
            "true_accepts": self.true_accepts,
            "false_rejects": self.false_rejects,
            "false_accepts": self.false_accepts,
            "true_rejects": self.true_rejects,
            "gar_pct": round(self.gar * 100.0, 2),
            "frr_pct": round(self.frr * 100.0, 2),
            "far_pct": round(self.far * 100.0, 2),
            "trr_pct": round(self.trr * 100.0, 2),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
        }


@dataclass
class Rank1Metrics:
    """Rank-1 identification performance metrics."""
    total_probes: int
    closed_set_probes: int
    open_set_probes: int
    correct_identifications: int
    false_identifications: int
    false_rejections: int  # Genuine rejected as UNKNOWN
    correct_unknown_rejections: int
    false_unknown_acceptances: int  # Impostor accepted as known
    closed_set_accuracy: float
    open_set_rejection_rate: float
    overall_accuracy: float


@dataclass
class ThreeVoteAnalysis:
    """End-to-end 3-vote temporal confirmation probability evaluation."""
    single_frame_far: float
    single_frame_gar: float
    gallery_size: int
    min_supporting_votes: int
    track_frames_evaluated: int
    prob_wrong_identity_confirmed: float
    prob_genuine_confirmation_failure: float
    prob_genuine_confirmed: float
    simulation_wrong_identity_confirmed: Optional[float] = None
    simulation_genuine_confirmed: Optional[float] = None


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Calculate cosine similarity between two feature embeddings."""
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def compute_distribution_stats(scores: List[float]) -> DistributionStats:
    """Compute summary statistics for a score list."""
    if not scores:
        return DistributionStats(
            count=0, min=0.0, max=0.0, mean=0.0, median=0.0, std=0.0,
            p5=0.0, p25=0.0, p75=0.0, p95=0.0
        )
    arr = np.asarray(scores, dtype=np.float64)
    return DistributionStats(
        count=len(arr),
        min=float(np.min(arr)),
        max=float(np.max(arr)),
        mean=float(np.mean(arr)),
        median=float(np.median(arr)),
        std=float(np.std(arr)),
        p5=float(np.percentile(arr, 5)),
        p25=float(np.percentile(arr, 25)),
        p75=float(np.percentile(arr, 75)),
        p95=float(np.percentile(arr, 95)),
    )


def compute_histogram(
    scores: List[float],
    bins: int = 20,
    min_val: float = -0.2,
    max_val: float = 1.0,
) -> Histogram:
    """Compute bin counts for score values between min_val and max_val."""
    if not scores:
        edges = list(np.linspace(min_val, max_val, bins + 1))
        return Histogram(bin_edges=edges, counts=[0] * bins, total=0)

    arr = np.clip(np.asarray(scores, dtype=np.float64), min_val, max_val)
    counts, edges = np.histogram(arr, bins=bins, range=(min_val, max_val))
    return Histogram(
        bin_edges=[float(e) for e in edges],
        counts=[int(c) for c in counts],
        total=len(scores),
    )


def compute_threshold_sweep(
    genuine_scores: List[float],
    impostor_scores: List[float],
    thresholds: Optional[List[float]] = None,
) -> List[SweepPoint]:
    """Calculate FAR, FRR, GAR, Precision, Recall, and F1 across thresholds."""
    if thresholds is None:
        thresholds = [round(t, 2) for t in np.arange(0.10, 0.91, 0.05)]

    gen_arr = np.asarray(genuine_scores, dtype=np.float64)
    imp_arr = np.asarray(impostor_scores, dtype=np.float64)

    total_gen = len(gen_arr)
    total_imp = len(imp_arr)

    points: List[SweepPoint] = []
    for thresh in thresholds:
        ta = int(np.sum(gen_arr >= thresh)) if total_gen > 0 else 0
        fr = int(np.sum(gen_arr < thresh)) if total_gen > 0 else 0
        fa = int(np.sum(imp_arr >= thresh)) if total_imp > 0 else 0
        tr = int(np.sum(imp_arr < thresh)) if total_imp > 0 else 0

        gar = ta / total_gen if total_gen > 0 else 0.0
        frr = fr / total_gen if total_gen > 0 else 0.0
        far = fa / total_imp if total_imp > 0 else 0.0
        trr = tr / total_imp if total_imp > 0 else 0.0

        denom_prec = ta + fa
        precision = (ta / denom_prec) if denom_prec > 0 else 1.0
        recall = gar
        denom_f1 = precision + recall
        f1 = (2.0 * precision * recall / denom_f1) if denom_f1 > 0 else 0.0

        points.append(
            SweepPoint(
                threshold=thresh,
                true_accepts=ta,
                false_rejects=fr,
                false_accepts=fa,
                true_rejects=tr,
                gar=gar,
                frr=frr,
                far=far,
                trr=trr,
                precision=precision,
                recall=recall,
                f1_score=f1,
            )
        )
    return points


def find_eer(sweep_points: List[SweepPoint]) -> Optional[SweepPoint]:
    """Find the operating point where |FAR - FRR| is minimal (Equal Error Rate)."""
    if not sweep_points:
        return None
    return min(sweep_points, key=lambda p: abs(p.far - p.frr))


def compute_rank1_identification(
    probe_results: List[Dict[str, Any]],
    threshold: float,
    min_margin: float = 0.0,
) -> Rank1Metrics:
    """
    Evaluate Rank-1 open-set identification.

    Each item in probe_results must have:
      - true_subject: str ("UNKNOWN" if open-set impostor)
      - predicted_subject: str (top-ranked match name)
      - top_similarity: float
      - runner_up_similarity: float (or margin)
    """
    total = len(probe_results)
    if total == 0:
        return Rank1Metrics(
            total_probes=0, closed_set_probes=0, open_set_probes=0,
            correct_identifications=0, false_identifications=0, false_rejections=0,
            correct_unknown_rejections=0, false_unknown_acceptances=0,
            closed_set_accuracy=0.0, open_set_rejection_rate=0.0, overall_accuracy=0.0,
        )

    closed_probes = 0
    open_probes = 0
    correct_id = 0
    false_id = 0
    false_rej = 0
    correct_unknown = 0
    false_unknown_accept = 0

    for res in probe_results:
        true_sub = res.get("true_subject", "")
        pred_sub = res.get("predicted_subject", "")
        top_sim = float(res.get("top_similarity", 0.0))
        runner_up = float(res.get("runner_up_similarity", -1.0))
        margin = top_sim - runner_up if runner_up >= -1.0 else 1.0

        is_accepted = (top_sim >= threshold) and (margin >= min_margin)

        if true_sub and true_sub.upper() != "UNKNOWN":
            closed_probes += 1
            if is_accepted:
                if pred_sub == true_sub:
                    correct_id += 1
                else:
                    false_id += 1
            else:
                false_rej += 1
        else:
            open_probes += 1
            if not is_accepted:
                correct_unknown += 1
            else:
                false_unknown_accept += 1

    closed_acc = (correct_id / closed_probes) if closed_probes > 0 else 0.0
    open_rej = (correct_unknown / open_probes) if open_probes > 0 else 0.0
    overall = ((correct_id + correct_unknown) / total) if total > 0 else 0.0

    return Rank1Metrics(
        total_probes=total,
        closed_set_probes=closed_probes,
        open_set_probes=open_probes,
        correct_identifications=correct_id,
        false_identifications=false_id,
        false_rejections=false_rej,
        correct_unknown_rejections=correct_unknown,
        false_unknown_acceptances=false_unknown_accept,
        closed_set_accuracy=closed_acc,
        open_set_rejection_rate=open_rej,
        overall_accuracy=overall,
    )


def compute_condition_breakdown(
    probe_results: List[Dict[str, Any]],
    threshold: float,
) -> Dict[str, Dict[str, Any]]:
    """Group closed-set probe results by condition attributes and compute GAR / mean score."""
    breakdown: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

    for res in probe_results:
        true_sub = res.get("true_subject", "")
        if not true_sub or true_sub.upper() == "UNKNOWN":
            continue

        conditions = res.get("condition", {})
        if not isinstance(conditions, dict):
            continue

        for dim, val in conditions.items():
            dim_key = str(dim)
            val_key = str(val)
            if dim_key not in breakdown:
                breakdown[dim_key] = {}
            if val_key not in breakdown[dim_key]:
                breakdown[dim_key][val_key] = []
            breakdown[dim_key][val_key].append(res)

    results: Dict[str, Dict[str, Any]] = {}
    for dim, vals in breakdown.items():
        results[dim] = {}
        for val, items in vals.items():
            count = len(items)
            scores = [float(it.get("top_similarity", 0.0)) for it in items]
            accepts = sum(1 for it in items if float(it.get("top_similarity", 0.0)) >= threshold and it.get("predicted_subject") == it.get("true_subject"))
            gar = (accepts / count) if count > 0 else 0.0
            results[dim][val] = {
                "count": count,
                "gar_pct": round(gar * 100.0, 2),
                "frr_pct": round((1.0 - gar) * 100.0, 2),
                "mean_similarity": round(float(np.mean(scores)), 4) if scores else 0.0,
                "min_similarity": round(float(np.min(scores)), 4) if scores else 0.0,
            }
    return results


def _comb(n: int, k: int) -> int:
    """Binomial coefficient helper."""
    if k < 0 or k > n:
        return 0
    return math.comb(n, k)


def compute_three_vote_confirmation(
    single_frame_far: float,
    single_frame_gar: float,
    gallery_size: int = 50,
    track_frames_evaluated: int = 15,
    min_supporting_votes: int = 3,
    run_monte_carlo: bool = True,
    mc_iterations: int = 20000,
) -> ThreeVoteAnalysis:
    """
    Evaluate multi-frame temporal voting logic (default 3 votes required).

    1. Probability a wrong identity (impostor or unknown) is confirmed within M frames:
       Let single_frame_far be p_fa.
       Across K enrolled gallery candidates, assuming false accepts disperse across identities,
       single-frame vote probability for a specific target identity is p_i = p_fa / K.
       Prob(votes for identity i >= V in M frames):
         P_i = 1 - sum_{k=0}^{V-1} binom(M, k) * (p_i)^k * (1 - p_i)^(M-k)
       Union bound across K identities:
         P_wrong_confirmed <= K * P_i

    2. Probability a genuine person fails to confirm within N frames:
       Let single_frame_gar be q.
       Prob(votes < V in N frames):
         P_fail = sum_{k=0}^{V-1} binom(N, k) * q^k * (1 - q)^(N-k)
    """
    M = max(track_frames_evaluated, min_supporting_votes)
    V = min_supporting_votes
    K = max(gallery_size, 1)

    # 1. Impostor confirmation probability
    p_fa = max(0.0, min(1.0, single_frame_far))
    p_i = p_fa / K  # Target identity false accept probability per frame

    p_i_less_than_v = sum(_comb(M, k) * (p_i ** k) * ((1.0 - p_i) ** (M - k)) for k in range(V))
    p_i_confirmed = max(0.0, 1.0 - p_i_less_than_v)
    prob_wrong_confirmed = min(1.0, K * p_i_confirmed)

    # 2. Genuine confirmation failure probability
    q = max(0.0, min(1.0, single_frame_gar))
    prob_genuine_fail = sum(_comb(M, k) * (q ** k) * ((1.0 - q) ** (M - k)) for k in range(V))
    prob_genuine_confirmed = max(0.0, 1.0 - prob_genuine_fail)

    # 3. Monte Carlo validation
    sim_wrong: Optional[float] = None
    sim_genuine: Optional[float] = None

    if run_monte_carlo and mc_iterations > 0:
        rng = np.random.default_rng(seed=42)

        # Simulation for impostor track
        # On each frame, impostor can trigger a false accept with prob p_fa, choosing uniformly among K candidates
        fa_events = rng.random((mc_iterations, M)) < p_fa
        candidate_choices = rng.integers(0, K, size=(mc_iterations, M))
        impostor_confirmed_count = 0

        for trial in range(mc_iterations):
            votes: Dict[int, int] = {}
            confirmed = False
            for f in range(M):
                if fa_events[trial, f]:
                    c = candidate_choices[trial, f]
                    votes[c] = votes.get(c, 0) + 1
                    if votes[c] >= V:
                        confirmed = True
                        break
            if confirmed:
                impostor_confirmed_count += 1
        sim_wrong = impostor_confirmed_count / mc_iterations

        # Simulation for genuine track
        gen_matches = rng.random((mc_iterations, M)) < q
        gen_votes = np.sum(gen_matches, axis=1)
        sim_genuine = float(np.mean(gen_votes >= V))

    return ThreeVoteAnalysis(
        single_frame_far=single_frame_far,
        single_frame_gar=single_frame_gar,
        gallery_size=gallery_size,
        min_supporting_votes=min_supporting_votes,
        track_frames_evaluated=M,
        prob_wrong_identity_confirmed=prob_wrong_confirmed,
        prob_genuine_confirmation_failure=prob_genuine_fail,
        prob_genuine_confirmed=prob_genuine_confirmed,
        simulation_wrong_identity_confirmed=sim_wrong,
        simulation_genuine_confirmed=sim_genuine,
    )
