"""Admin & Teacher Face Enrollment CLI (Step 2E.2).

Performs:
1. Multi-image ingestion (3 to 5 images).
2. Per-image quality gates (face count, min size, detection confidence, sharpness/blur).
3. Quality-weighted mean ArcFace embedding extraction.
4. Immediate discarding of raw image data.
5. Registration with backend FastAPI / MongoDB (with cross-student duplicate check).
6. Audited re-enrollment and deletion support.

Security: Raw embeddings and images are NEVER printed or logged.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Optional

import requests

SERVICE_ROOT = Path(__file__).resolve().parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from enrollment.engine import process_multi_image_enrollment
from pipeline.live_cv_pipeline import create_face_analysis, swap_scrfd_detector


def run_enrollment_cli(args: argparse.Namespace) -> int:
    """Execute enrollment CLI commands."""
    backend_url = args.backend_url.rstrip("/")
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}

    # Handle deletion action
    if args.action == "delete":
        if not args.token:
            print("[ERROR] Authentication token (--token) is required to delete a student profile.")
            return 1
        url = f"{backend_url}/api/v1/enrollment/{args.identity}"
        print(f"[*] Deleting biometric profile for identity '{args.identity}'...")
        resp = requests.delete(url, headers=headers, timeout=5.0)
        if resp.status_code == 200:
            print(f"[SUCCESS] Biometric profile for '{args.identity}' deleted successfully.")
            return 0
        else:
            print(f"[ERROR] Failed to delete biometric profile: HTTP {resp.status_code} - {resp.text}")
            return 1

    # Handle enrollment / re-enrollment
    if not args.images or len(args.images) < 3 or len(args.images) > 5:
        print(f"[ERROR] Must provide between 3 and 5 image paths. Provided: {len(args.images or [])}")
        return 1

    image_paths = [Path(p).resolve() for p in args.images]
    for p in image_paths:
        if not p.exists():
            print(f"[ERROR] Image file not found: {p}")
            return 1

    print(f"[*] Initializing InsightFace ArcFace models for enrollment...")
    app = create_face_analysis(
        name="buffalo_l",
        allowed_modules=["detection", "recognition"],
        intra_threads=4,
        inter_threads=2,
    )
    swap_scrfd_detector(app, detector_type="0.5g", intra_threads=4, inter_threads=2)

    # Fetch existing gallery for local pre-check if token provided
    existing_gallery = {}
    if args.token:
        try:
            gal_resp = requests.get(f"{backend_url}/api/v1/enrollment/gallery", headers=headers, timeout=5.0)
            if gal_resp.status_code == 200:
                raw_gal = gal_resp.json().get("gallery", {})
                import numpy as np
                for k, v in raw_gal.items():
                    existing_gallery[k] = np.array(v, dtype=np.float32)
        except Exception:
            pass

    print(f"[*] Evaluating {len(image_paths)} images against biometric quality gates for '{args.identity}'...")
    batch_result = process_multi_image_enrollment(
        images=image_paths,
        identity=args.identity,
        app=app,
        existing_gallery=existing_gallery,
        min_images=3,
        max_images=5,
        min_face_size=args.min_face_size,
        min_det_score=args.min_det_score,
        min_sharpness=args.min_sharpness,
        duplicate_threshold=args.duplicate_threshold,
    )

    # Detailed per-image quality report
    print("\n--- Biometric Quality Inspection ---")
    for idx, r in enumerate(batch_result.per_image_results):
        status = "PASSED" if r.passed else "REJECTED"
        print(f"  Image {idx + 1}: [{status}] - Size: {r.face_size[0]}x{r.face_size[1]}px, DetScore: {r.det_score:.2f}, Sharpness: {r.sharpness:.1f}")
        if not r.passed:
            for reason in r.rejection_reasons:
                print(f"    * REASON: {reason}")
    print("------------------------------------\n")

    if not batch_result.passed:
        print(f"[FAILED] Enrollment failed quality checks:")
        for r in batch_result.rejection_reasons:
            print(f"  * {r}")
        return 1

    print(f"[*] Quality gates passed! Computed quality-weighted mean ArcFace embedding from {batch_result.sample_count} samples.")
    print(f"[*] Raw images discarded from memory.")

    # Submit to backend API
    if not args.token:
        print("[WARNING] No authentication token provided. Embedding was extracted locally but not saved to backend.")
        return 0

    endpoint = f"{backend_url}/api/v1/enrollment/{args.identity}" if args.action == "reenroll" else f"{backend_url}/api/v1/enrollment"
    method = requests.put if args.action == "reenroll" else requests.post

    payload = {
        "identity": args.identity,
        "mean_embedding": batch_result.mean_embedding.tolist(),
        "sample_count": batch_result.sample_count,
        "quality_score": round(batch_result.quality_score, 4),
    }

    print(f"[*] Transmitting biometric profile to backend ({args.action})...")
    resp = method(endpoint, headers=headers, json=payload, timeout=5.0)

    if resp.status_code in (200, 201):
        data = resp.json()
        print(f"\n[SUCCESS] Student '{data['identity']}' enrolled successfully!")
        print(f"  Sample Count : {data['sample_count']}")
        print(f"  Quality Score: {data['quality_score']}")
        print(f"  Enrolled By  : {data['enrolled_by']}")
        print(f"  Timestamp    : {data['created_at']}")
        return 0
    elif resp.status_code == 409:
        print(f"\n[CONFLICT] Cross-Student Duplicate Rejected: {resp.json().get('detail')}")
        return 1
    elif resp.status_code == 403:
        print(f"\n[FORBIDDEN] Insufficient permissions. Only TEACHER or ADMIN can enroll faces.")
        return 1
    else:
        print(f"\n[ERROR] Backend rejected enrollment: HTTP {resp.status_code} - {resp.text}")
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Admin & Teacher Face Enrollment CLI")
    parser.add_argument("--identity", required=True, help="Canonical student identity (e.g. person_05)")
    parser.add_argument("--images", nargs="*", help="List of 3 to 5 face image paths")
    parser.add_argument("--action", choices=["enroll", "reenroll", "delete"], default="enroll", help="Action to perform")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000", help="Backend API URL")
    parser.add_argument("--token", default="", help="JWT bearer token (TEACHER or ADMIN)")
    parser.add_argument("--min-face-size", type=int, default=80, help="Minimum face bounding box size (px)")
    parser.add_argument("--min-det-score", type=float, default=0.60, help="Minimum SCRFD detection score")
    parser.add_argument("--min-sharpness", type=float, default=50.0, help="Minimum Laplacian variance for blur gate")
    parser.add_argument("--duplicate-threshold", type=float, default=0.70, help="Cross-student duplicate similarity threshold")

    args = parser.parse_args()
    code = run_enrollment_cli(args)
    sys.exit(code)


if __name__ == "__main__":
    main()
