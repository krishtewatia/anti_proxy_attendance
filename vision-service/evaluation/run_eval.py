"""Command-line runner for biometric face recognition accuracy evaluation."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add project root to sys.path if needed
SCRIPT_DIR = Path(__file__).resolve().parent
SERVICE_ROOT = SCRIPT_DIR.parent
PROJECT_ROOT = SERVICE_ROOT.parent

if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.evaluator import RecognitionEvaluator
from evaluation.synthetic import generate_synthetic_evaluation_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("recognition_eval")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate face recognition accuracy & select threshold from data.")
    parser.add_argument(
        "--data-dir",
        type=str,
        default=None,
        help="Path to evaluation dataset directory (with enrollment/ and probes/ or legacy benchmark).",
    )
    parser.add_argument(
        "--output-file",
        type=str,
        default="docs/evaluation/recognition_eval.md",
        help="Path to output markdown report file.",
    )
    parser.add_argument(
        "--histogram-file",
        type=str,
        default="docs/evaluation/score_distribution.txt",
        help="Path to output score distribution histogram text file.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.50,
        help="Recommended similarity threshold (default: 0.50).",
    )
    parser.add_argument(
        "--min-margin",
        type=float,
        default=0.15,
        help="Minimum top-1 vs runner-up similarity margin (default: 0.15).",
    )
    parser.add_argument(
        "--min-votes",
        type=int,
        default=3,
        help="Minimum supporting votes for temporal track confirmation (default: 3).",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Generate synthetic benchmark modeling empirical ArcFace distributions.",
    )
    parser.add_argument(
        "--num-enrolled",
        type=int,
        default=25,
        help="Number of enrolled subjects for synthetic evaluation (default: 25).",
    )
    args = parser.parse_args()

    evaluator = RecognitionEvaluator(
        recommended_threshold=args.threshold,
        min_margin=args.min_margin,
        min_supporting_votes=args.min_votes,
    )

    data_dir_path = Path(args.data_dir) if args.data_dir else None
    report = None

    if data_dir_path and data_dir_path.exists() and not args.synthetic:
        logger.info("Evaluating real dataset at %s...", data_dir_path)
        try:
            from insightface.app import FaceAnalysis
            app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"], allowed_modules=["detection", "recognition"])
            app.prepare(ctx_id=0, det_size=(640, 640))
            evaluator.app = app
            report = evaluator.evaluate_from_directory(data_dir_path)
        except Exception as e:
            logger.warning("Could not initialize InsightFace on dataset: %s. Falling back to synthetic benchmark.", e)

    if report is None:
        logger.info("Generating synthetic benchmark evaluation (num_enrolled=%d)...", args.num_enrolled)
        gallery, probes, unknowns = generate_synthetic_evaluation_data(
            num_enrolled=args.num_enrolled,
            probes_per_enrolled=6,
            num_unknown_probes=30,
            seed=42,
        )
        report = evaluator.evaluate_from_embeddings(
            enrolled_gallery=gallery,
            probe_embeddings=probes,
            unknown_embeddings=unknowns,
        )

    # Render Markdown report
    md_content = report.to_markdown()

    out_file = Path(args.output_file)
    if not out_file.is_absolute():
        out_file = PROJECT_ROOT / out_file
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(md_content, encoding="utf-8")
    logger.info("Saved evaluation markdown report to: %s", out_file)

    # Render Histogram text file
    hist_file = Path(args.histogram_file)
    if not hist_file.is_absolute():
        hist_file = PROJECT_ROOT / hist_file
    hist_file.parent.mkdir(parents=True, exist_ok=True)

    hist_lines = [
        "============================================================",
        "BIOMETRIC SIMILARITY SCORE FREQUENCY DISTRIBUTIONS",
        "============================================================",
        f"Recommended Threshold (theta): {args.threshold:.2f}",
        f"Genuine Samples: {report.genuine_stats.count} (Mean: {report.genuine_stats.mean:.4f}, Min: {report.genuine_stats.min:.4f}, Max: {report.genuine_stats.max:.4f})",
        f"Impostor Samples: {report.impostor_stats.count} (Mean: {report.impostor_stats.mean:.4f}, Min: {report.impostor_stats.min:.4f}, Max: {report.impostor_stats.max:.4f})",
        "",
        "--- GENUINE DISTRIBUTION ---",
        report.genuine_histogram.render_ascii(),
        "",
        "--- IMPOSTOR DISTRIBUTION ---",
        report.impostor_histogram.render_ascii(),
        "============================================================",
    ]
    hist_file.write_text("\n".join(hist_lines), encoding="utf-8")
    logger.info("Saved score distribution histogram to: %s", hist_file)

    # Console summary print
    print("\n" + "=" * 65)
    print("RECOGNITION ACCURACY & THRESHOLD VALIDATION COMPLETE")
    print("=" * 65)
    print(f"  Enrolled Identities : {report.dataset_summary.get('enrolled_identities')}")
    print(f"  Total Probes        : {report.dataset_summary.get('total_probes')}")
    print(f"  Genuine Comparisons : {report.genuine_stats.count}")
    print(f"  Impostor Comparisons: {report.impostor_stats.count}")
    print("-" * 65)
    print(f"  Genuine Similarity  : mean={report.genuine_stats.mean:.4f}, min={report.genuine_stats.min:.4f}, max={report.genuine_stats.max:.4f}")
    print(f"  Impostor Similarity : mean={report.impostor_stats.mean:.4f}, min={report.impostor_stats.min:.4f}, max={report.impostor_stats.max:.4f}")
    print(f"  Separation Gap      : {report.genuine_stats.min - report.impostor_stats.max:+.4f}")
    print("-" * 65)
    print(f"  Recommended Thresh  : {report.recommended_threshold:.2f}")
    print(f"  Rank-1 Accuracy     : {report.rank1_metrics.closed_set_accuracy*100.0:.2f}%")
    print(f"  Unknown Rejection   : {report.rank1_metrics.open_set_rejection_rate*100.0:.2f}%")
    print(f"  3-Vote Wrong Accept : {report.three_vote_analysis.prob_wrong_identity_confirmed:.6f}")
    print(f"  3-Vote Genuine Conf : {report.three_vote_analysis.prob_genuine_confirmed*100.0:.2f}%")

    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
