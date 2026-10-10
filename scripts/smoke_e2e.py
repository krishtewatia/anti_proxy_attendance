#!/usr/bin/env python3
"""End-to-end smoke test of the secured attendance flow.

Runs the flow a teacher and two students go through, over HTTP only:

    register a teacher and students -> an administrator approves them ->
    create and start a session for the teacher's assigned class ->
    send camera frames with the teacher's token -> manual correction ->
    finalize -> CSV export

and checks the security properties around it (no token, removed routes,
internal-only vision service).

Two ways to run it:

    # 1. Throwaway stack: builds the images, starts an isolated Compose
    #    project with generated secrets, runs the checks, removes everything.
    python scripts/smoke_e2e.py --photos /path/to/photos

    # 2. Against a running deployment (for example after a deploy):
    SMOKE_ADMIN_EMAIL=... SMOKE_ADMIN_PASSWORD=... \\
        python scripts/smoke_e2e.py --base-url https://attendance.example.edu --photos /path/to/photos

Registrations need an administrator's approval, so the run needs an admin
account. The throwaway stack creates one for itself. Against a deployment,
supply SMOKE_ADMIN_EMAIL and SMOKE_ADMIN_PASSWORD (and optionally
SMOKE_TEACHER_EMAIL / SMOKE_TEACHER_PASSWORD for an existing approved teacher
who is assigned the class given by --class-code).

Photos are never read from the repository. ``--photos`` (default:
``$VISION_FIXTURES_DIR/recognition_benchmark``) must hold one folder per
person with at least three face photos each. The first two people are
enrolled; a third, if present, is used as the person who is not enrolled.

Against a deployment the script can be run repeatedly. It registers two
smoke-test students once (IDs ``SMOKEA`` and ``SMOKEB`` by default, reused on
later runs) and creates one new session per run. Nothing is deleted, so use a
class and an environment where that is acceptable, and keep using the same
photos: a face that is already enrolled under another ID would be recognized
as that ID.

Liveness: ``--liveness-mode enforce`` starts the throwaway stack with the
liveness gate enforcing (default: observe). With ``--spoof-photos`` (a folder
of photos of a printed or on-screen face; default
``$VISION_FIXTURES_DIR/liveness/print/attempt_01`` if it exists) the run also
checks that a spoof is blocked and nobody is marked for it. That check is
skipped unless the stack enforces liveness.

``--prod-rehearsal`` starts the throwaway stack from the production Compose
file instead (``docker-compose.prod.yml`` with
``docker/docker-compose.prod.rehearsal.yml``): every request goes through
Caddy, as it will on the deployment, and the run also checks that only Caddy
is reachable and that a made-up X-Forwarded-For header is ignored.

Only statuses and identifiers are printed, never image or embedding data.
Exit code 0 means every check passed. Standard library only.
"""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.parse
import uuid

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = PROJECT_ROOT / "docker" / "docker-compose.smoke.yml"
# The production stack, rehearsed locally (--prod-rehearsal).
PROD_REHEARSAL_FILES = [
    PROJECT_ROOT / "docker-compose.prod.yml",
    PROJECT_ROOT / "docker" / "docker-compose.prod.rehearsal.yml",
]
# Compose files of the throwaway stack; main() switches them for a rehearsal.
STACK_FILES: list[Path] = [COMPOSE_FILE]
MODEL_CACHE_VOLUME = "anti_proxy_model_cache"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


class Checks:
    """Collects pass/fail/skip results and prints one line per check."""

    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.retries = 0

    def check(self, name: str, ok: bool, detail: object = "") -> bool:
        if ok:
            self.passed += 1
        else:
            self.failed += 1
        suffix = f" | {detail}" if detail != "" else ""
        print(f"{'PASS' if ok else 'FAIL'} - {name}{suffix}", flush=True)
        return ok

    def skip(self, name: str, reason: str) -> None:
        self.skipped += 1
        print(f"SKIP - {name} | {reason}", flush=True)

    def retry(self, name: str, attempt: int, status: object, body: object = None) -> None:
        """Record that a request made for check ``name`` is being retried, and why."""
        self.retries += 1
        print(
            f"RETRY - {name} | attempt {attempt} got {describe_response(status, body)}", flush=True
        )


RETRYABLE_STATUSES = (None, 502, 503, 504)


def describe_response(status: object, body: object = None) -> str:
    """Short, loggable description of a response: the HTTP status and the server's reason."""
    info = body if isinstance(body, dict) else {}
    if status is None:
        return f"no HTTP response ({info.get('error', 'connection failed')})"
    reason = info.get("detail") or info.get("message") or info.get("error")
    text = f"HTTP {status}"
    return f"{text} ({str(reason)[:120]})" if reason else text


def call_with_retry(send, checks: Checks, name: str, attempts: int = 3, pause: float = 3.0):
    """Call ``send()`` and retry while the server is briefly unavailable.

    A 502/503/504 or a dropped connection is a retry, not a verdict; every
    retry is logged with the check it belongs to and the status that caused
    it. Any other status is returned as it is. ``send`` returns (status, body).
    """
    status, body = send()
    for attempt in range(1, attempts):
        if status not in RETRYABLE_STATUSES:
            break
        checks.retry(name, attempt, status, body)
        time.sleep(pause * attempt)
        status, body = send()
    return status, body


class Api:
    """Minimal JSON/bytes HTTP client for one base URL (http or https only)."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        parts = urllib.parse.urlsplit(self.base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("base URL must be an http:// or https:// address")
        self._https = parts.scheme == "https"
        self._host = parts.hostname
        self._port = parts.port
        self._prefix = parts.path.rstrip("/")

    def call(self, method, path, data=None, headers=None, timeout=120, raw=False):
        connection_type = http.client.HTTPSConnection if self._https else http.client.HTTPConnection
        conn = connection_type(self._host, self._port, timeout=timeout)
        try:
            conn.request(method, self._prefix + path, body=data, headers=headers or {})
            resp = conn.getresponse()
            body = resp.read()
        except (http.client.HTTPException, OSError) as exc:
            return None, {"error": type(exc).__name__}
        finally:
            conn.close()
        if raw and 200 <= resp.status < 300:
            return resp.status, body
        try:
            return resp.status, json.loads(body or b"{}")
        except ValueError:
            return resp.status, {}

    def post_json(self, path, payload, headers=None, timeout=120):
        merged = {"Content-Type": "application/json", **(headers or {})}
        return self.call("POST", path, json.dumps(payload).encode(), merged, timeout)


def load_photos(photos_dir: Path) -> list[list[bytes]]:
    """Return up to three people, each a list of at least three photos."""
    people: list[list[bytes]] = []
    for person_dir in sorted(p for p in photos_dir.iterdir() if p.is_dir()):
        files = sorted(f for f in person_dir.iterdir() if f.suffix.lower() in IMAGE_SUFFIXES)
        if len(files) >= 3:
            people.append([f.read_bytes() for f in files[:3]])
        if len(people) == 3:
            break
    return people


# ------------------------------------------------------------------ throwaway stack


def compose(project: str, env: dict[str, str], *args: str, capture: bool = False):
    files = [arg for path in STACK_FILES for arg in ("-f", str(path))]
    cmd = ["docker", "compose", "-p", project, *files, *args]
    return subprocess.run(  # nosec B603
        cmd,
        env=env,
        cwd=str(PROJECT_ROOT),
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def start_throwaway_stack(
    project: str, env: dict[str, str], build: bool, entry: tuple[str, str] = ("backend", "8000")
) -> str:
    """Start the isolated stack and return the base URL of its entry point.

    ``entry`` is the service and container port requests are sent to: the
    backend itself, or Caddy when rehearsing the production stack.
    """
    subprocess.run(  # nosec B603 B607
        ["docker", "volume", "create", MODEL_CACHE_VOLUME],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    up_args = ["up", "-d", "--wait", "--wait-timeout", "600"]
    if build:
        up_args.append("--build")
    print(
        f"Starting throwaway stack '{project}' (first run downloads the face models)...", flush=True
    )
    result = compose(project, env, *up_args)
    if result.returncode != 0:
        raise RuntimeError("docker compose up failed")
    port = compose(project, env, "port", *entry, capture=True)
    if port.returncode != 0 or not port.stdout.strip():
        raise RuntimeError(f"could not read the host port of {entry[0]}")
    host_port = port.stdout.strip().rsplit(":", 1)[-1]
    return f"http://127.0.0.1:{host_port}"


def check_liveness_model_in_image(project: str, env: dict[str, str], checks: Checks) -> None:
    """The vision image must be able to read its own liveness model files."""
    probe = (
        "import json, os, urllib.request;"
        "r = urllib.request.Request('http://127.0.0.1:8088/status',"
        " headers={'X-API-Key': os.environ['VISION_SERVICE_API_KEY']});"
        "d = json.load(urllib.request.urlopen(r, timeout=5));"
        "print(json.dumps({k: d.get(k) for k in ('liveness_mode', 'liveness_model_loaded')}))"
    )
    result = compose(
        project, env, "exec", "-T", "vision-service", "python", "-c", probe, capture=True
    )
    try:
        state = json.loads((result.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        state = {}
    checks.check(
        "the vision image loaded its liveness model",
        result.returncode == 0 and state.get("liveness_model_loaded") is True,
        state or {"exit": result.returncode},
    )


def check_production_topology(
    project: str, env: dict[str, str], api: "Api", checks: Checks
) -> None:
    """Rehearsal only: Caddy is the single way in, and it does not pass on a made-up client address."""
    for service, port in (("backend", "8000"), ("frontend", "8080"), ("vision-service", "8088")):
        published = compose(project, env, "port", service, port, capture=True)
        # An unpublished port is reported as an error or as host port 0.
        host_port = (published.stdout or "").strip().rsplit(":", 1)[-1]
        checks.check(
            f"{service} publishes no port (reachable only through Caddy)",
            published.returncode != 0 or not host_port.isdigit() or int(host_port) == 0,
            (published.stdout or "").strip()[:80],
        )

    status, _ = api.call("GET", "/health")
    checks.check("Caddy forwards /health to the backend", status == 200, status)
    status, _ = api.call("GET", "/", raw=True)
    checks.check("Caddy serves the web application at /", status == 200, status)

    # The registration limit is per client address. Every request below claims
    # a different address in X-Forwarded-For; if Caddy or the backend believed
    # it, none would ever be limited. The body is empty, so no account is made.
    statuses = []
    for n in range(45):
        status, _ = api.post_json(
            "/api/v1/auth/register", {}, headers={"X-Forwarded-For": f"198.51.100.{n + 1}"}
        )
        statuses.append(status)
        if status == 429:
            break
    checks.check(
        "a made-up X-Forwarded-For header does not get around the rate limit (429)",
        429 in statuses,
        {"requests": len(statuses), "last": statuses[-1]},
    )


def stop_throwaway_stack(project: str, env: dict[str, str], show_logs: bool) -> None:
    if show_logs:
        logs = compose(
            project,
            env,
            "logs",
            "--no-color",
            "--tail",
            "40",
            "backend",
            "vision-service",
            capture=True,
        )
        print("\n----- last container log lines -----\n" + (logs.stdout or ""), flush=True)
    compose(project, env, "down", "-v", "--remove-orphans", capture=True)
    print(f"Throwaway stack '{project}' removed.", flush=True)


# ------------------------------------------------------------------ the flow


def run_flow(
    api: Api,
    checks: Checks,
    people: list[list[bytes]],
    *,
    service_key: str | None,
    admin_email: str | None,
    admin_password: str | None,
    admin_replacement_password: str | None,
    teacher_email: str | None,
    teacher_password: str | None,
    class_code: str,
    branch: str,
    section: str,
    student_prefix: str,
    other_class_code: str,
    fresh_database: bool,
    model_wait_seconds: int,
    liveness_enforced: bool,
    spoof_photos: list[bytes],
) -> None:
    for _ in range(60):
        if api.call("GET", "/health", timeout=5)[0] == 200:
            break
        time.sleep(2)
    if not checks.check("backend is up", api.call("GET", "/health", timeout=5)[0] == 200):
        return

    suffix = uuid.uuid4().hex[:6]

    # ---- administrator: every registration below needs approval
    admin_auth: dict[str, str] = {}
    if admin_email and admin_password:
        status, login = api.post_json(
            "/api/v1/auth/login", {"email": admin_email, "password": admin_password}
        )
        if not checks.check(
            "administrator logged in", status == 200, describe_response(status, login)
        ):
            return
        admin_auth = {"Authorization": f"Bearer {login.get('access_token', '')}"}

        # An administrator created from the environment must replace that
        # password before the account can do anything else.
        if login.get("must_change_password"):
            if not admin_replacement_password:
                checks.check(
                    "administrator can act",
                    False,
                    "this administrator must change their password first; log in once and change it",
                )
                return
            status, blocked = api.call("GET", "/api/v1/admin/approvals/count", headers=admin_auth)
            checks.check(
                "administrator is blocked until the first password is changed",
                status == 403 and "password_change_required" in json.dumps(blocked),
                describe_response(status, blocked),
            )
            status, changed = api.post_json(
                "/api/v1/auth/change-password",
                {"current_password": admin_password, "new_password": admin_replacement_password},
                admin_auth,
            )
            if not checks.check(
                "administrator changes the first password",
                status == 200 and not changed.get("must_change_password"),
                describe_response(status, changed),
            ):
                return
            status, _ = api.call("GET", "/api/v1/admin/approvals/count", headers=admin_auth)
            checks.check(
                "the token from before the password change is refused",
                status == 401,
                f"HTTP {status}",
            )
            admin_auth = {"Authorization": f"Bearer {changed.get('access_token', '')}"}
    else:
        checks.skip(
            "administrator logged in",
            "no admin account supplied (SMOKE_ADMIN_EMAIL / SMOKE_ADMIN_PASSWORD)",
        )

    def approve(user_id: str, body: dict) -> tuple:
        return api.post_json(f"/api/v1/admin/approvals/{user_id}/approve", body, admin_auth)

    # ---- teacher
    if teacher_email and teacher_password:
        checks.skip("teacher registered", "using the supplied smoke-test teacher account")
    else:
        if not admin_auth:
            checks.check(
                "teacher registered", False, "a new teacher needs an administrator to approve it"
            )
            return
        teacher_email = f"smoke_teacher_{suffix}@smoke.test"
        teacher_password = secrets.token_urlsafe(18) + "aA1!"
        status, registered = api.post_json(
            "/api/v1/teachers/register",
            {
                "name": "Smoke Teacher",
                "email": teacher_email,
                "password": teacher_password,
                "teacher_id": f"T-SMOKE-{suffix.upper()}",
                "department": branch,
                "assigned_classes": [class_code, other_class_code],
                "assigned_subjects": ["Smoke"],
            },
        )
        checks.check(
            "teacher registered", status in (200, 201), describe_response(status, registered)
        )
        status, pending = api.post_json(
            "/api/v1/auth/login", {"email": teacher_email, "password": teacher_password}
        )
        checks.check(
            "a new registration cannot log in before approval (403)",
            status == 403 and "awaiting admin approval" in json.dumps(pending),
            describe_response(status, pending),
        )
        status, approved = approve(
            registered.get("user_id", ""), {"assigned_classes": [class_code]}
        )
        checks.check(
            "administrator approves the teacher and assigns one class",
            status == 200 and approved.get("assigned_classes") == [class_code.upper()],
            describe_response(status, approved),
        )
    status, login = api.post_json(
        "/api/v1/auth/login", {"email": teacher_email, "password": teacher_password}
    )
    if not checks.check("teacher logged in", status == 200, describe_response(status, login)):
        return
    auth = {"Authorization": f"Bearer {login.get('access_token', '')}"}

    # ---- students, enrolled from a photo
    # A deployment that has just started may still be loading the face models;
    # enrollment fails until it has, so retry until the deadline. On a database
    # that outlives the run the students exist from an earlier run (409).
    students: list[str] = []
    enroll_deadline = time.time() + model_wait_seconds
    for index, label in enumerate(("A", "B")):
        student_id = f"{student_prefix}{label}"
        enroll_attempt = 0
        while True:
            status, profile = api.post_json(
                "/api/v1/students/register",
                {
                    "name": f"Smoke Student {label}",
                    "email": f"{student_id.lower()}@smoke.test",
                    "password": secrets.token_urlsafe(18) + "aA1!",
                    "student_id": student_id,
                    "roll_number": f"SMOKE-{label}",
                    "branch": branch,
                    "section": section,
                    "photo_base64": base64.b64encode(people[index][0]).decode(),
                },
            )
            if status not in (400, 502, 503, None) or time.time() > enroll_deadline:
                break
            enroll_attempt += 1
            checks.retry(
                f"student {label} registered with a photo and enrolled",
                enroll_attempt,
                status,
                profile,
            )
            time.sleep(5)
        students.append(student_id)
        if status == 201 and admin_auth:
            approval_status, approved = approve(profile.get("user_id", ""), {})
            if approval_status != 200:
                checks.check(
                    f"administrator approves student {label}",
                    False,
                    describe_response(approval_status, approved),
                )
        if status == 409 and not fresh_database:
            checks.check(f"student {label} already registered by an earlier run", True, student_id)
        else:
            checks.check(
                f"student {label} registered with a photo and enrolled",
                status == 201 and profile.get("has_biometric") is True,
                {
                    "http": status,
                    "class_code": profile.get("class_code"),
                    "detail": profile.get("detail"),
                },
            )

    # ---- session
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    later = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 7200))
    # A session takes only a subject that is in the catalog and active.
    status, subjects = api.call("GET", "/api/v1/academic/subjects", headers=auth)
    subject = subjects[0].get("name", "") if status == 200 and subjects else ""
    if not checks.check("the catalog has an active subject", bool(subject), status):
        return
    status, refused = api.post_json(
        "/api/v1/sessions",
        {
            "course_name": f"Smoke test {suffix} (unknown subject)",
            "classroom_id": "ROOM_SMOKE",
            "class_code": class_code,
            "subject": f"Not A Subject {suffix}",
            "start_time": now,
            "end_time": later,
            "required_presence_percentage": 100.0,
        },
        auth,
    )
    checks.check(
        "a session for a subject that is not in the catalog is refused",
        status == 400,
        describe_response(status, refused),
    )

    status, session = api.post_json(
        "/api/v1/sessions",
        {
            "course_name": f"Smoke test {suffix}",
            "classroom_id": "ROOM_SMOKE",
            "class_code": class_code,
            "subject": subject,
            "start_time": now,
            "end_time": later,
            "required_presence_percentage": 100.0,
        },
        auth,
    )
    session_id = session.get("session_id", "")
    if not checks.check("session created", status == 201 and bool(session_id), status):
        return
    frame_path = f"/api/v1/attendance/{session_id}/process-frame"

    # A teacher may open a session only for a class an administrator assigned.
    status, refused = api.post_json(
        "/api/v1/sessions",
        {
            "course_name": f"Smoke test {suffix} (other class)",
            "classroom_id": "ROOM_SMOKE",
            "class_code": other_class_code,
            "subject": subject,
            "start_time": now,
            "end_time": later,
            "required_presence_percentage": 100.0,
        },
        auth,
    )
    checks.check(
        "session for a class not assigned to the teacher is refused (403)",
        status == 403,
        describe_response(status, refused),
    )

    def frame(person: int, photo: int, check: str, headers: dict | None = None):
        """Send one frame for the named check. The backend answers 503 when the
        vision service is briefly busy; that is retried and logged."""
        merged = {"Content-Type": "image/jpeg", **(auth if headers is None else headers)}
        return call_with_retry(
            lambda: api.call("POST", frame_path, people[person][photo], merged, 120), checks, check
        )

    def outcome(status, body: dict) -> dict:
        """What a frame check reports: always the HTTP status, so a failure shows its cause."""
        report = {"http": status, "faces": summarize(body)}
        reason = body.get("detail") or body.get("error")
        if reason:
            report["reason"] = str(reason)[:120]
        return report

    def summarize(body: dict) -> list[tuple]:
        return [
            (f.get("status"), f.get("identity"), f.get("mark_status"))
            for f in body.get("faces", [])
            if isinstance(f, dict)
        ]

    name = "frame before the session is started is rejected (409)"
    status, body = frame(0, 1, name)
    checks.check(name, status == 409, describe_response(status, body))
    status, _ = api.call("POST", f"/api/v1/sessions/{session_id}/start", headers=auth)
    checks.check("session started", status == 200, status)
    name = "frame without a teacher token is rejected (401)"
    status, body = frame(0, 1, name, headers={})
    checks.check(name, status == 401, describe_response(status, body))

    # ---- recognition and marking (the vision service may still be loading models)
    marked: list[tuple] = []
    body: dict = {}
    deadline = time.time() + model_wait_seconds
    name = "student A recognized from a different photo and marked by the backend"
    waits = 0
    while time.time() < deadline:
        status, body = frame(0, 1, name)
        faces = summarize(body)
        if status == 200 and any(f[2] in ("marked", "already_present") for f in faces):
            marked = faces
            break
        # Not marked yet (models still loading, or the gallery not synced): say what came back.
        waits += 1
        checks.retry(
            name, waits, status, {**body, "detail": f"faces={faces}"} if status == 200 else body
        )
        time.sleep(4)
    checks.check(name, bool(marked) and marked[0][1] == students[0], outcome(status, body))
    serialized = json.dumps(body)
    checks.check(
        "the signed result is not returned to the browser",
        '"recognition"' not in serialized and "signature" not in serialized,
    )

    name = "student A in a third photo is already_present (no duplicate)"
    status, body = frame(0, 2, name)
    faces = summarize(body)
    checks.check(
        name,
        status == 200 and any(f[1] == students[0] and f[2] == "already_present" for f in faces),
        outcome(status, body),
    )

    if len(people) >= 3:
        name = "a person who is not enrolled is not marked"
        status, body = frame(2, 0, name)
        faces = summarize(body)
        checks.check(
            name,
            status == 200 and not any(f[2] in ("marked", "already_present") for f in faces),
            outcome(status, body),
        )
    else:
        checks.skip(
            "a person who is not enrolled is not marked", "needs a third person in --photos"
        )

    # ---- liveness: a photo of a photo must not mark anyone
    spoof_check = "a spoof photo is blocked and marks nobody"
    if not spoof_photos:
        checks.skip(spoof_check, "no spoof photos available (--spoof-photos)")
    elif not liveness_enforced:
        checks.skip(spoof_check, "the stack is not enforcing liveness (--liveness-mode enforce)")
    else:
        blocked = 0
        marked_from_spoof = 0
        for photo in spoof_photos:
            status, body = call_with_retry(
                lambda photo=photo: api.call(
                    "POST", frame_path, photo, {"Content-Type": "image/jpeg", **auth}, 120
                ),
                checks,
                spoof_check,
            )
            for face in body.get("faces", []) if status == 200 else []:
                if face.get("status") == "spoof" and face.get("mark_status") == "blocked":
                    blocked += 1
                if face.get("identity") == students[1] and face.get("mark_status") == "marked":
                    marked_from_spoof += 1
        checks.check(
            spoof_check,
            blocked > 0 and marked_from_spoof == 0,
            {"frames": len(spoof_photos), "blocked": blocked, "marked": marked_from_spoof},
        )

    status, attendance = api.call("GET", f"/api/v1/attendance/{session_id}", headers=auth)
    by_identity = {
        r["identity"]: r["status"]
        for r in attendance.get("records", [])
        if r["identity"] in students
    }
    checks.check(
        "live attendance: A PRESENT, B ABSENT",
        by_identity.get(students[0]) == "PRESENT" and by_identity.get(students[1]) == "ABSENT",
        by_identity,
    )

    name = "student B recognized and marked"
    status, body = frame(1, 1, name)
    faces = summarize(body)
    checks.check(
        name,
        status == 200 and any(f[1] == students[1] and f[2] == "marked" for f in faces),
        outcome(status, body),
    )

    # ---- a manual correction wins over a later recognition
    record_id = f"att_{session_id}_{students[1]}"
    status, _ = api.call(
        "PATCH",
        f"/api/v1/attendance/{session_id}/records/{record_id}",
        json.dumps(
            {
                "new_status": "ABSENT",
                "new_presence_seconds": 0.0,
                "reason": "Smoke test: manual correction",
            }
        ).encode(),
        {"Content-Type": "application/json", **auth},
    )
    checks.check("teacher corrects B to ABSENT", status == 200, status)
    name = "a later recognition of B is blocked by the correction (locked)"
    status, body = frame(1, 2, name)
    faces = summarize(body)
    checks.check(
        name,
        status == 200 and any(f[1] == students[1] and f[2] == "locked" for f in faces),
        outcome(status, body),
    )

    # ---- finalize and export
    status, final = api.call("POST", f"/api/v1/sessions/{session_id}/finalize", headers=auth)
    final_by = {
        r["identity"]: r["status"] for r in final.get("records", []) if r["identity"] in students
    }
    checks.check(
        "finalized: A PRESENT, B ABSENT",
        status == 200
        and final_by.get(students[0]) == "PRESENT"
        and final_by.get(students[1]) == "ABSENT",
        final_by or status,
    )
    name = "frame after finalization is rejected (409)"
    status, body = frame(0, 1, name)
    checks.check(name, status == 409, describe_response(status, body))

    status, csv_bytes = api.call(
        "GET", f"/api/v1/attendance/{session_id}/export", headers=auth, raw=True
    )
    rows = csv_bytes.decode("utf-8").strip().splitlines() if status == 200 else []
    own_rows = [r for r in rows[1:] if r.split(",", 1)[0] in students]
    checks.check(
        "CSV export has a header and one row per student",
        status == 200
        and rows[:1] == ["Student ID,Student Name,Status"]
        and len(own_rows) == 2
        and (len(rows) == 3 or not fresh_database),
        {"http": status, "rows": len(rows), "smoke_rows": len(own_rows)},
    )

    # ---- student photos are biometric data: token and a reason to see them
    photo_path = f"/api/v1/students/{students[0]}/photo"
    status, _ = api.call("GET", photo_path, raw=True)
    checks.check("student photo without a token is rejected (401)", status == 401, status)
    status, photo = api.call("GET", photo_path, headers=auth, raw=True)
    checks.check(
        "the session's teacher can load a rostered student's photo",
        status == 200 and isinstance(photo, bytes) and len(photo) > 0,
        status,
    )
    status, _ = api.call("GET", "/uploads/student_profiles/" + students[0] + ".jpg", raw=True)
    checks.check("photos are not served as static files (404)", status == 404, status)

    # ---- exposure
    host = urllib.parse.urlsplit(api.base_url).hostname or "127.0.0.1"
    sock = socket.socket()
    sock.settimeout(3)
    try:
        reachable = sock.connect_ex((host, 8088)) == 0
    except OSError:
        reachable = False
    finally:
        sock.close()
    checks.check("the vision service port (8088) is not reachable from here", not reachable)

    status, _ = api.call("GET", "/api/v1/attendance/vision-gallery")
    checks.check("/vision-gallery without the service key is rejected (401)", status == 401, status)
    status, _ = api.call("GET", "/api/v1/attendance/vision-gallery", headers=auth)
    checks.check(
        "/vision-gallery with only a teacher token is rejected (401)", status == 401, status
    )
    if service_key:
        status, gallery = api.call(
            "GET", "/api/v1/attendance/vision-gallery", headers={"X-API-Key": service_key}
        )
        checks.check(
            "/vision-gallery with the service key works (count only shown)",
            status == 200
            and (gallery.get("count") == 2 if fresh_database else gallery.get("count", 0) >= 2),
            {"http": status, "count": gallery.get("count")},
        )
    else:
        checks.skip(
            "/vision-gallery with the service key works",
            "service key is not known in --base-url mode",
        )

    for path in ("/api/v1/attendance/mark", f"/api/v1/attendance/{session_id}/mark"):
        status, _ = api.post_json(path, {"identity": students[0], "session_id": session_id}, auth)
        checks.check(
            f"removed route {path.replace(session_id, '<session>')} is gone",
            status in (404, 405),
            status,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="End-to-end smoke test of the secured attendance flow"
    )
    parser.add_argument(
        "--base-url",
        help="Test a running deployment instead of starting a throwaway stack",
    )
    parser.add_argument(
        "--photos",
        help="Folder with one sub-folder of face photos per person "
        "(default: $VISION_FIXTURES_DIR/recognition_benchmark)",
    )
    parser.add_argument("--class-code", default="DS-B", help="Class the session is created for")
    parser.add_argument(
        "--branch", default="Data Science", help="Branch the students register under"
    )
    parser.add_argument("--section", default="B", help="Section the students register under")
    parser.add_argument(
        "--other-class-code",
        default="CS-A",
        help="A class the smoke teacher is NOT assigned, used to check that it is refused",
    )
    parser.add_argument(
        "--student-prefix",
        default="SMOKE",
        help="Prefix of the two smoke-test student IDs (default: SMOKE, giving SMOKEA and SMOKEB)",
    )
    parser.add_argument(
        "--liveness-mode",
        choices=["observe", "enforce"],
        default="observe",
        help="Throwaway stack: liveness mode to start with. With --base-url: the mode the deployment runs in",
    )
    parser.add_argument(
        "--liveness-threshold",
        help="Throwaway stack: liveness threshold to start with (default 0.5)",
    )
    parser.add_argument(
        "--spoof-photos",
        help="Folder of photos of a printed or on-screen face of the SECOND person in --photos "
        "(default: $VISION_FIXTURES_DIR/liveness/print/attempt_01 if it exists)",
    )
    parser.add_argument(
        "--no-build", action="store_true", help="Throwaway stack: reuse existing images"
    )
    parser.add_argument(
        "--keep", action="store_true", help="Throwaway stack: leave it running afterwards"
    )
    parser.add_argument(
        "--prod-rehearsal",
        action="store_true",
        help="Throwaway stack: start the production Compose file (Caddy in front, "
        "nothing else published) instead of the plain test stack",
    )
    parser.add_argument(
        "--model-wait",
        type=int,
        default=240,
        help="Seconds to wait for the first successful recognition (model loading)",
    )
    args = parser.parse_args()

    photos_arg = args.photos
    if not photos_arg and os.environ.get("VISION_FIXTURES_DIR"):
        photos_arg = str(Path(os.environ["VISION_FIXTURES_DIR"]) / "recognition_benchmark")
    if not photos_arg or not Path(photos_arg).is_dir():
        print("ERROR: pass --photos or set VISION_FIXTURES_DIR (see the README).", file=sys.stderr)
        return 2
    people = load_photos(Path(photos_arg))
    if len(people) < 2:
        print("ERROR: --photos needs at least two people with three photos each.", file=sys.stderr)
        return 2

    spoof_dir = args.spoof_photos
    if not spoof_dir and os.environ.get("VISION_FIXTURES_DIR"):
        candidate = Path(os.environ["VISION_FIXTURES_DIR"]) / "liveness" / "print" / "attempt_01"
        spoof_dir = str(candidate) if candidate.is_dir() else None
    spoof_photos: list[bytes] = []
    if spoof_dir and Path(spoof_dir).is_dir():
        spoof_files = sorted(
            f for f in Path(spoof_dir).iterdir() if f.suffix.lower() in IMAGE_SUFFIXES
        )
        spoof_photos = [f.read_bytes() for f in spoof_files[:6]]

    checks = Checks()
    flow_args = {
        "class_code": args.class_code,
        "branch": args.branch,
        "section": args.section,
        "student_prefix": args.student_prefix,
        "other_class_code": args.other_class_code,
        "model_wait_seconds": args.model_wait,
        "liveness_enforced": args.liveness_mode == "enforce",
        "spoof_photos": spoof_photos,
    }

    if args.base_url:
        try:
            deployed = Api(args.base_url)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        run_flow(
            deployed,
            checks,
            people,
            service_key=None,
            admin_email=os.environ.get("SMOKE_ADMIN_EMAIL"),
            admin_password=os.environ.get("SMOKE_ADMIN_PASSWORD"),
            # Never change the password of an administrator on a real deployment.
            admin_replacement_password=None,
            teacher_email=os.environ.get("SMOKE_TEACHER_EMAIL"),
            teacher_password=os.environ.get("SMOKE_TEACHER_PASSWORD"),
            fresh_database=False,
            **flow_args,
        )
    else:
        project = f"smoke-{uuid.uuid4().hex[:8]}"
        service_key = secrets.token_hex(32)
        # The throwaway stack creates its own first administrator from these.
        admin_email = f"smoke_admin_{uuid.uuid4().hex[:6]}@smoke.test"
        admin_password = secrets.token_urlsafe(24)
        # The flow replaces the first password, as every new administrator must.
        admin_current_password = secrets.token_urlsafe(24)
        env = {
            **os.environ,
            "SMOKE_JWT_SECRET_KEY": secrets.token_hex(32),
            "SMOKE_VISION_SERVICE_API_KEY": service_key,
            "SMOKE_RECOGNITION_SIGNING_KEY": secrets.token_hex(32),
            "SMOKE_LIVENESS_MODE": args.liveness_mode,
            "SMOKE_BOOTSTRAP_ADMIN_EMAIL": admin_email,
            "SMOKE_BOOTSTRAP_ADMIN_PASSWORD": admin_password,
        }
        if args.liveness_threshold:
            env["SMOKE_LIVENESS_THRESHOLD"] = args.liveness_threshold
        entry = ("backend", "8000")
        if args.prod_rehearsal:
            STACK_FILES[:] = PROD_REHEARSAL_FILES
            entry = ("caddy", "80")
            # The production file's own variable names, with this run's values.
            env.update(
                {
                    "COMPOSE_PROJECT_NAME": project,
                    "SITE_ADDRESS": ":80",
                    # Loopback only, host ports chosen by Docker.
                    "HTTP_BIND": "127.0.0.1:",
                    "HTTPS_BIND": "127.0.0.1:",
                    "IMAGE_PREFIX": project,
                    "IMAGE_TAG": "rehearsal",
                    "MONGODB_URL": "mongodb://mongodb:27017",
                    "DATABASE_NAME": "smoke_e2e",
                    "JWT_SECRET_KEY": env["SMOKE_JWT_SECRET_KEY"],
                    "VISION_SERVICE_API_KEY": service_key,
                    "RECOGNITION_SIGNING_KEY": env["SMOKE_RECOGNITION_SIGNING_KEY"],
                    "LIVENESS_MODE": args.liveness_mode,
                    "BOOTSTRAP_ADMIN_EMAIL": admin_email,
                    "BOOTSTRAP_ADMIN_PASSWORD": admin_password,
                }
            )
            if args.liveness_threshold:
                env["LIVENESS_THRESHOLD"] = args.liveness_threshold
        base_url = ""
        try:
            base_url = start_throwaway_stack(project, env, build=not args.no_build, entry=entry)
            check_liveness_model_in_image(project, env, checks)
            run_flow(
                Api(base_url),
                checks,
                people,
                service_key=service_key,
                admin_email=admin_email,
                admin_password=admin_password,
                admin_replacement_password=admin_current_password,
                teacher_email=None,
                teacher_password=None,
                fresh_database=True,
                **flow_args,
            )
            if args.prod_rehearsal:
                # Last: it uses up the registration budget on purpose.
                check_production_topology(project, env, Api(base_url), checks)
        except RuntimeError as exc:
            checks.check("throwaway stack started", False, exc)
        finally:
            if args.keep:
                # This stack and its generated administrator exist only until it is
                # removed, so the credentials are shown for running other checks
                # against it (for example the frontend's live suites).
                print(f"Stack '{project}' left running (--keep) at {base_url or '(not started)'}")
                print(f"  administrator: {admin_email} / {admin_current_password}")
                print(f"  service key  : {service_key}")
                print("Remove it with:")
                files = " ".join(f"-f {path}" for path in STACK_FILES)
                print(f"  docker compose -p {project} {files} down -v")
            else:
                stop_throwaway_stack(project, env, show_logs=checks.failed > 0)

    retried = (
        f", {checks.retries} retried request(s), see the RETRY lines above"
        if checks.retries
        else ""
    )
    print(f"\n{checks.passed} passed, {checks.failed} failed, {checks.skipped} skipped{retried}")
    return 0 if checks.failed == 0 and checks.passed > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
