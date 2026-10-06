#!/usr/bin/env python3
"""Standalone Test Runner for Anti-Proxy Attendance E2E Testing Track.

Executes all 4 tiers of opaque-box E2E tests:
  Tier 1: Clean Seeding & Biometric Validation
  Tier 2: API Boundary & Security Validation
  Tier 3: Event Ingestion to Live Snapshot State Transitions
  Tier 4: Full Real-World Demo Application Lifecycle

Usage:
  python tests/e2e/run_tests.py                  # Run all tiers
  python tests/e2e/run_tests.py --tier 1          # Run Tier 1 only
  python tests/e2e/run_tests.py --tier 2          # Run Tier 2 only
  python tests/e2e/run_tests.py --tier 3          # Run Tier 3 only
  python tests/e2e/run_tests.py --tier 4          # Run Tier 4 only
  python tests/e2e/run_tests.py --verbose         # Detailed output
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
E2E_DIR = PROJECT_ROOT / "tests" / "e2e"
BACKEND_DIR = PROJECT_ROOT / "backend"

for d in [str(PROJECT_ROOT), str(E2E_DIR), str(BACKEND_DIR)]:
    if d not in sys.path:
        sys.path.insert(0, d)

TIER_FILES = {
    "1": ("Tier 1: Clean Seeding & Biometrics", E2E_DIR / "test_tier1_clean_seeding.py"),
    "2": ("Tier 2: API Boundary & Security", E2E_DIR / "test_tier2_api_boundary_security.py"),
    "3": ("Tier 3: Events & Live Snapshots", E2E_DIR / "test_tier3_events_and_snapshots.py"),
    "4": ("Tier 4: Demo Lifecycle & Ledger", E2E_DIR / "test_tier4_demo_lifecycle.py"),
}


def print_banner(text: str) -> None:
    print(f"\n{'=' * 75}\n{text}\n{'=' * 75}")


def preflight_check() -> bool:
    """Validate environment prerequisites before executing tests."""
    print_banner("PREFLIGHT HEALTH CHECK")

    # 1. Check MongoDB
    mongo_uri = os.getenv("MONGO_URI") or os.getenv("MONGODB_URL") or "mongodb://localhost:27017"
    print(f"[PREFLIGHT] Checking MongoDB connection ({mongo_uri})...")
    try:
        from pymongo import MongoClient
        from conftest import get_mongo_connection_uri

        resolved_uri = get_mongo_connection_uri()
        c = MongoClient(resolved_uri, serverSelectionTimeoutMS=2000)
        c.admin.command("ping")
        print(f"  [OK] MongoDB reachable at {resolved_uri}")
        c.close()
    except Exception as exc:
        print(f"  [WARN] MongoDB ping failed ({exc}). Tests will attempt auto-recovery.")

    # 2. Check Backend API
    api_url = os.getenv("API_BASE_URL", "http://localhost:8000")
    print(f"[PREFLIGHT] Checking FastAPI Backend ({api_url})...")
    try:
        import httpx
        r = httpx.get(f"{api_url}/health", timeout=1.5)
        if r.status_code == 200:
            print(f"  [OK] FastAPI Backend is live at {api_url}")
        else:
            print(f"  [INFO] FastAPI returned {r.status_code}. ASGI fallback available.")
    except Exception:
        print("  [INFO] Live daemon not responding. In-process ASGI transport will be used.")

    # 3. Check Benchmark Vectors
    bench_file = Path(os.environ.get("VISION_FIXTURES_DIR") or "vision-fixtures-not-configured") / "benchmark_embeddings.json"
    if bench_file.exists():
        print(f"  [OK] Authentic InsightFace embeddings found: {bench_file.name}")
    else:
        print(f"  [WARN] Benchmark embeddings file missing at {bench_file}")

    return True


def run_tests(tier: str, verbose: bool = False) -> int:
    import pytest

    preflight_check()

    selected_tiers = list(TIER_FILES.keys()) if tier == "all" else [tier]
    overall_start = time.time()
    results: dict[str, tuple[str, str, float]] = {}

    for t in selected_tiers:
        name, file_path = TIER_FILES[t]
        print_banner(f"RUNNING {name.upper()}")

        pytest_args = [str(file_path), "-v" if verbose else "-q", "--tb=short", "-o", f"pythonpath={E2E_DIR}"]
        t_start = time.time()
        ret = pytest.main(pytest_args)
        duration = time.time() - t_start

        status = "PASSED" if ret == 0 else f"FAILED (code {ret})"
        results[t] = (name, status, duration)

    total_time = time.time() - overall_start

    # Summary Table
    print_banner("E2E TEST RUN SUMMARY")
    print(f"{'Tier':<10} | {'Test Suite':<40} | {'Status':<12} | {'Time (s)':<8}")
    print("-" * 75)

    all_passed = True
    for t, (name, status, dur) in results.items():
        if "PASSED" not in status:
            all_passed = False
        print(f"Tier {t:<5} | {name:<40} | {status:<12} | {dur:<8.2f}")

    print("-" * 75)
    print(f"Total Duration: {total_time:.2f} seconds")

    if all_passed:
        print("\n>>> ALL E2E TEST TIERS COMPLETED SUCCESSFULLY (EXIT 0) <<<\n")
        return 0
    else:
        print("\n>>> ONE OR MORE E2E TEST TIERS FAILED (EXIT 1) <<<\n")
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Anti-Proxy E2E Test Suites")
    parser.add_argument(
        "--tier",
        choices=["1", "2", "3", "4", "all"],
        default="all",
        help="Specific test tier to run (default: all)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose test output",
    )
    args = parser.parse_args()

    sys.exit(run_tests(args.tier, verbose=args.verbose))


if __name__ == "__main__":
    main()
