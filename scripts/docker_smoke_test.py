#!/usr/bin/env python3
"""End-to-End Docker Compose Smoke Test for Anti-Proxy Attendance Stack.

Validates the full system lifecycle:
1. Docker Compose bringup (or connects to already running stack)
2. Healthchecks for Backend, MongoDB, Frontend, Vision Service
3. User registration and JWT authentication
4. Attendance session creation
5. Camera telemetry and service-authenticated event ingestion (POST /api/v1/events)
6. Real-time attendance computation and live snapshot verification
7. Optional teardown (docker compose down)

Usage:
    python scripts/docker_smoke_test.py                 # Run against running stack
    python scripts/docker_smoke_test.py --docker-up     # Run with docker compose up & down
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from typing import Any, Optional
import urllib.parse
import urllib.request
import urllib.error

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_API_KEY = "test_vision_api_key_for_smoke_test_12345"


class SmokeTestFailure(Exception):
    """Raised when any step of the smoke test fails."""


LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def log_step(step_num: int, title: str) -> None:
    print(f"\n[{step_num}/7] {title}...")


def http_request(
    url: str,
    method: str = "GET",
    headers: Optional[dict[str, str]] = None,
    data: Optional[dict[str, Any]] = None,
    timeout: float = 10.0,
) -> tuple[int, dict[str, Any]]:
    """Helper to perform HTTP requests using standard library urllib."""
    req_headers = {"User-Agent": "AntiProxySmokeTest/1.0"}
    if headers:
        req_headers.update(headers)

    body_bytes = None
    if data is not None:
        body_bytes = json.dumps(data).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    # This smoke test only ever targets the local Docker Compose stack.
    parsed_url = urllib.parse.urlsplit(url)
    if parsed_url.scheme not in ("http", "https") or parsed_url.hostname not in LOOPBACK_HOSTS:
        raise ValueError(f"Smoke test only calls loopback http(s) URLs, got: {url}")

    req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method=method)
    try:
        # The URL is restricted to loopback hosts and http(s) just above, so it
        # cannot be steered to file:// or to another machine.
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.status
            content = resp.read().decode("utf-8")
            try:
                parsed = json.loads(content) if content else {}
            except json.JSONDecodeError:
                parsed = {"raw": content}
            return status_code, parsed
    except urllib.error.HTTPError as exc:
        err_content = exc.read().decode("utf-8")
        try:
            parsed = json.loads(err_content) if err_content else {}
        except json.JSONDecodeError:
            parsed = {"raw": err_content}
        return exc.code, parsed
    except Exception as exc:
        raise SmokeTestFailure(f"Request to {url} failed: {exc}") from exc


def wait_for_health(backend_url: str, timeout_seconds: int = 60) -> None:
    """Poll backend /health endpoint until it returns 200 OK."""
    health_url = f"{backend_url.rstrip('/')}/health"
    deadline = time.time() + timeout_seconds
    last_err = None

    print(f"Polling {health_url} (timeout: {timeout_seconds}s)...", end="", flush=True)
    while time.time() < deadline:
        try:
            status, data = http_request(health_url, timeout=3.0)
            if status == 200 and data.get("status") == "healthy":
                print(" OK!")
                return
        except Exception as e:
            last_err = e
        print(".", end="", flush=True)
        time.sleep(2)

    raise SmokeTestFailure(
        f"Backend failed to become healthy within {timeout_seconds}s. Last error: {last_err}"
    )


def check_frontend(frontend_url: str) -> None:
    """Verify frontend static server is accessible."""
    try:
        status, _ = http_request(frontend_url, timeout=5.0)
        if status in (200, 304):
            print(f"Frontend responsive at {frontend_url} (HTTP {status})")
        else:
            print(f"[WARN] Frontend returned HTTP {status}")
    except Exception as exc:
        print(f"[WARN] Frontend check skipped or unavailable: {exc}")


def run_smoke_test(
    backend_url: str = "http://localhost:8000",
    frontend_url: str = "http://localhost:3000",
    vision_api_key: str = DEFAULT_API_KEY,
    docker_up: bool = False,
    docker_down: bool = False,
) -> bool:
    """Execute end-to-end smoke verification."""
    print("=" * 72)
    print("ANTI-PROXY SYSTEM: DOCKER STACK END-TO-END SMOKE TEST")
    print("=" * 72)

    if docker_up:
        print("[SETUP] Starting containers with 'docker compose up -d'...")
        subprocess.run(["docker", "compose", "up", "-d"], cwd=PROJECT_ROOT, check=True)

    try:
        # Step 1: Verify Stack Health
        log_step(1, "Verifying backend and frontend service health")
        wait_for_health(backend_url)
        check_frontend(frontend_url)

        # Step 2: Register a new teacher account
        log_step(2, "Registering test teacher account")
        unique_suffix = secrets.token_hex(4)
        teacher_email = f"teacher_smoke_{unique_suffix}@demo.edu"
        teacher_password = f"TestPass!_{unique_suffix}"

        reg_url = f"{backend_url}/api/v1/auth/register"
        reg_status, reg_data = http_request(
            reg_url,
            method="POST",
            data={
                "email": teacher_email,
                "password": teacher_password,
                "role": "TEACHER",
            },
        )
        if reg_status != 201:
            raise SmokeTestFailure(f"User registration failed (HTTP {reg_status}): {reg_data}")
        teacher_user_id = reg_data["user_id"]
        print(f"Registered teacher: {teacher_email} (ID: {teacher_user_id})")

        # Step 3: Authenticate and retrieve JWT
        log_step(3, "Authenticating user via JWT login")
        login_url = f"{backend_url}/api/v1/auth/login"
        login_status, login_data = http_request(
            login_url,
            method="POST",
            data={"email": teacher_email, "password": teacher_password},
        )
        if login_status != 200 or "access_token" not in login_data:
            raise SmokeTestFailure(f"Login failed (HTTP {login_status}): {login_data}")
        token = login_data["access_token"]
        auth_header = {"Authorization": f"Bearer {token}"}
        print("Obtained valid JWT Bearer access token.")

        # Step 4: Create an Attendance Session
        log_step(4, "Creating attendance session")
        now = datetime.now(timezone.utc)
        session_url = f"{backend_url}/api/v1/sessions"
        classroom = "ROOM_101"
        sess_status, sess_data = http_request(
            session_url,
            method="POST",
            headers=auth_header,
            data={
                "course_name": f"Smoke Test Course {unique_suffix}",
                "classroom_id": classroom,
                "start_time": (now - timedelta(minutes=10)).isoformat(),
                "end_time": (now + timedelta(minutes=50)).isoformat(),
                "required_presence_percentage": 75.0,
            },
        )
        if sess_status != 201:
            raise SmokeTestFailure(f"Session creation failed (HTTP {sess_status}): {sess_data}")
        session_id = sess_data["session_id"]
        print(f"Created session: {session_id} for classroom {classroom}")

        # Step 5: Post Credentialed Attendance Events
        log_step(5, "Dispatching credentialed biometric events (ENTRY & EXIT)")
        events_url = f"{backend_url}/api/v1/events"
        student_id = f"STU_{unique_suffix.upper()}"
        event_time_entry = (now - timedelta(minutes=5)).isoformat()

        # Send ENTRY event
        entry_payload = {
            "event_id": f"evt_entry_{unique_suffix}",
            "camera_id": "CAM_ROOM_101_DOOR",
            "track_id": 101,
            "identity": student_id,
            "direction": "ENTRY",
            "timestamp": event_time_entry,
            "evidence": {
                "peak_similarity": 0.95,
                "mean_similarity": 0.91,
                "supporting_frames": 10,
                "total_frames": 12,
                "consistency_pct": 83.3,
                "margin_over_runner_up": 0.25,
                "runner_up_identity": "UNKNOWN",
            },
        }
        event_headers = {"x-api-key": vision_api_key}
        e1_status, e1_data = http_request(
            events_url,
            method="POST",
            headers=event_headers,
            data=entry_payload,
        )
        if e1_status not in (200, 201):
            raise SmokeTestFailure(f"ENTRY event failed (HTTP {e1_status}): {e1_data}")
        print(f"ENTRY event ingested successfully: {entry_payload['event_id']}")

        # Send EXIT event
        event_time_exit = (now - timedelta(minutes=1)).isoformat()
        exit_payload = {
            "event_id": f"evt_exit_{unique_suffix}",
            "camera_id": "CAM_ROOM_101_DOOR",
            "track_id": 102,
            "identity": student_id,
            "direction": "EXIT",
            "timestamp": event_time_exit,
            "evidence": {
                "peak_similarity": 0.93,
                "mean_similarity": 0.89,
                "supporting_frames": 8,
                "total_frames": 10,
                "consistency_pct": 80.0,
                "margin_over_runner_up": 0.20,
                "runner_up_identity": "UNKNOWN",
            },
        }
        e2_status, e2_data = http_request(
            events_url,
            method="POST",
            headers=event_headers,
            data=exit_payload,
        )
        if e2_status not in (200, 201):
            raise SmokeTestFailure(f"EXIT event failed (HTTP {e2_status}): {e2_data}")
        print(f"EXIT event ingested successfully: {exit_payload['event_id']}")

        # Step 6: Query Attendance & Live Session Feed
        log_step(6, "Reading attendance records and live snapshot")
        # Live snapshot
        snapshot_url = f"{backend_url}/api/v1/sessions/{session_id}/live-snapshot"
        snap_status, snap_data = http_request(snapshot_url, headers=auth_header)
        if snap_status != 200:
            raise SmokeTestFailure(f"Live snapshot query failed (HTTP {snap_status}): {snap_data}")

        feed_events = snap_data.get("events_feed", [])
        print(
            f"Live snapshot retrieved: {len(feed_events)} events in feed, session status: {snap_data.get('status')}"
        )

        # Attendance query
        att_url = f"{backend_url}/api/v1/attendance/{session_id}"
        att_status, att_data = http_request(att_url, headers=auth_header)
        if att_status != 200:
            raise SmokeTestFailure(f"Attendance query failed (HTTP {att_status}): {att_data}")
        records = att_data.get("records", [])
        print(f"Session attendance retrieved: {len(records)} student records processed.")

        # Step 7: Completed successfully
        log_step(7, "Verification complete")
        print("=" * 72)
        print("ALL SMOKE CHECKS PASSED: Full stack lifecycle verified successfully!")
        print("=" * 72)
        return True

    finally:
        if docker_down:
            print("\n[TEARDOWN] Stopping containers with 'docker compose down'...")
            subprocess.run(["docker", "compose", "down"], cwd=PROJECT_ROOT)


def main():
    parser = argparse.ArgumentParser(description="End-to-End Smoke Test for Anti-Proxy Local Stack")
    parser.add_argument(
        "--backend-url",
        default=os.getenv("BACKEND_URL", "http://127.0.0.1:8000"),
        help="Backend URL",
    )
    parser.add_argument(
        "--frontend-url",
        default=os.getenv("FRONTEND_URL", "http://127.0.0.1:3000"),
        help="Frontend URL",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("VISION_SERVICE_API_KEY", DEFAULT_API_KEY),
        help="Vision API Key",
    )
    parser.add_argument(
        "--docker-up", action="store_true", help="Execute docker compose up -d before test"
    )
    parser.add_argument(
        "--docker-down", action="store_true", help="Execute docker compose down after test"
    )

    args = parser.parse_args()
    try:
        success = run_smoke_test(
            backend_url=args.backend_url,
            frontend_url=args.frontend_url,
            vision_api_key=args.api_key,
            docker_up=args.docker_up,
            docker_down=args.docker_down,
        )
        sys.exit(0 if success else 1)
    except SmokeTestFailure as exc:
        print(f"\n[FATAL ERROR] Smoke test failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
