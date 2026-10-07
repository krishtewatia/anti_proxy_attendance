#!/usr/bin/env python3
"""End-to-end smoke test of the secured attendance flow.

Runs the flow a teacher and two students go through, over HTTP only:

    register students with a photo -> create and start a session ->
    send camera frames with the teacher's token -> manual correction ->
    finalize -> CSV export

and checks the security properties around it (no token, removed routes,
internal-only vision service).

Two ways to run it:

    # 1. Throwaway stack: builds the images, starts an isolated Compose
    #    project with generated secrets, runs the checks, removes everything.
    python scripts/smoke_e2e.py --photos /path/to/photos

    # 2. Against a running deployment (for example after a deploy):
    SMOKE_TEACHER_EMAIL=... SMOKE_TEACHER_PASSWORD=... \\
        python scripts/smoke_e2e.py --base-url https://attendance.example.edu --photos /path/to/photos

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
MODEL_CACHE_VOLUME = "anti_proxy_model_cache"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


class Checks:
    """Collects pass/fail/skip results and prints one line per check."""

    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.skipped = 0

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
    cmd = ["docker", "compose", "-p", project, "-f", str(COMPOSE_FILE), *args]
    return subprocess.run(  # nosec B603
        cmd,
        env=env,
        cwd=str(PROJECT_ROOT),
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def start_throwaway_stack(project: str, env: dict[str, str], build: bool) -> str:
    """Start the isolated stack and return the backend's base URL."""
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
    port = compose(project, env, "port", "backend", "8000", capture=True)
    if port.returncode != 0 or not port.stdout.strip():
        raise RuntimeError("could not read the backend's host port")
    host_port = port.stdout.strip().rsplit(":", 1)[-1]
    return f"http://127.0.0.1:{host_port}"


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
    teacher_email: str | None,
    teacher_password: str | None,
    class_code: str,
    branch: str,
    section: str,
    student_prefix: str,
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

    # ---- teacher
    if teacher_email and teacher_password:
        checks.skip("teacher registered", "using the supplied smoke-test teacher account")
    else:
        teacher_email = f"smoke_teacher_{suffix}@smoke.test"
        teacher_password = secrets.token_urlsafe(18) + "aA1!"
        status, _ = api.post_json(
            "/api/v1/auth/register",
            {"email": teacher_email, "password": teacher_password, "role": "TEACHER"},
        )
        checks.check("teacher registered", status in (200, 201), status)
    status, login = api.post_json(
        "/api/v1/auth/login", {"email": teacher_email, "password": teacher_password}
    )
    if not checks.check("teacher logged in", status == 200, status):
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
            time.sleep(5)
        students.append(student_id)
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
    status, session = api.post_json(
        "/api/v1/sessions",
        {
            "course_name": f"Smoke test {suffix}",
            "classroom_id": "ROOM_SMOKE",
            "class_code": class_code,
            "subject": "Smoke",
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

    def frame(person: int, photo: int, headers: dict | None = None):
        merged = {"Content-Type": "image/jpeg", **(auth if headers is None else headers)}
        # The backend answers 503 when the vision service is briefly busy; that is
        # a retry, not a verdict. Every other status is returned as it is.
        for attempt in range(3):
            status, body = api.call("POST", frame_path, people[person][photo], merged, 120)
            if status not in (None, 502, 503, 504):
                break
            time.sleep(3 * (attempt + 1))
        return status, body

    def summarize(body: dict) -> list[tuple]:
        return [
            (f.get("status"), f.get("identity"), f.get("mark_status"))
            for f in body.get("faces", [])
            if isinstance(f, dict)
        ]

    status, _ = frame(0, 1)
    checks.check("frame before the session is started is rejected (409)", status == 409, status)
    status, _ = api.call("POST", f"/api/v1/sessions/{session_id}/start", headers=auth)
    checks.check("session started", status == 200, status)
    status, _ = frame(0, 1, headers={})
    checks.check("frame without a teacher token is rejected (401)", status == 401, status)

    # ---- recognition and marking (the vision service may still be loading models)
    marked: list[tuple] = []
    body: dict = {}
    deadline = time.time() + model_wait_seconds
    while time.time() < deadline:
        status, body = frame(0, 1)
        faces = summarize(body)
        if status == 200 and any(f[2] in ("marked", "already_present") for f in faces):
            marked = faces
            break
        time.sleep(4)
    checks.check(
        "student A recognized from a different photo and marked by the backend",
        bool(marked) and marked[0][1] == students[0],
        marked or {"http": status, "detail": body.get("detail")},
    )
    serialized = json.dumps(body)
    checks.check(
        "the signed result is not returned to the browser",
        '"recognition"' not in serialized and "signature" not in serialized,
    )

    status, body = frame(0, 2)
    faces = summarize(body)
    checks.check(
        "student A in a third photo is already_present (no duplicate)",
        status == 200 and any(f[1] == students[0] and f[2] == "already_present" for f in faces),
        faces,
    )

    if len(people) >= 3:
        status, body = frame(2, 0)
        faces = summarize(body)
        checks.check(
            "a person who is not enrolled is not marked",
            status == 200 and not any(f[2] in ("marked", "already_present") for f in faces),
            faces,
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
            status, body = api.call(
                "POST", frame_path, photo, {"Content-Type": "image/jpeg", **auth}, 120
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

    status, body = frame(1, 1)
    faces = summarize(body)
    checks.check(
        "student B recognized and marked",
        status == 200 and any(f[1] == students[1] and f[2] == "marked" for f in faces),
        faces,
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
    status, body = frame(1, 2)
    faces = summarize(body)
    checks.check(
        "a later recognition of B is blocked by the correction (locked)",
        status == 200 and any(f[1] == students[1] and f[2] == "locked" for f in faces),
        faces,
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
    status, _ = frame(0, 1)
    checks.check("frame after finalization is rejected (409)", status == 409, status)

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
            teacher_email=os.environ.get("SMOKE_TEACHER_EMAIL"),
            teacher_password=os.environ.get("SMOKE_TEACHER_PASSWORD"),
            fresh_database=False,
            **flow_args,
        )
    else:
        project = f"smoke-{uuid.uuid4().hex[:8]}"
        service_key = secrets.token_hex(32)
        env = {
            **os.environ,
            "SMOKE_JWT_SECRET_KEY": secrets.token_hex(32),
            "SMOKE_VISION_SERVICE_API_KEY": service_key,
            "SMOKE_RECOGNITION_SIGNING_KEY": secrets.token_hex(32),
            "SMOKE_LIVENESS_MODE": args.liveness_mode,
        }
        if args.liveness_threshold:
            env["SMOKE_LIVENESS_THRESHOLD"] = args.liveness_threshold
        try:
            base_url = start_throwaway_stack(project, env, build=not args.no_build)
            run_flow(
                Api(base_url),
                checks,
                people,
                service_key=service_key,
                teacher_email=None,
                teacher_password=None,
                fresh_database=True,
                **flow_args,
            )
        except RuntimeError as exc:
            checks.check("throwaway stack started", False, exc)
        finally:
            if args.keep:
                print(f"Stack '{project}' left running (--keep). Remove it with:")
                print(f"  docker compose -p {project} -f {COMPOSE_FILE} down -v")
            else:
                stop_throwaway_stack(project, env, show_logs=checks.failed > 0)

    print(f"\n{checks.passed} passed, {checks.failed} failed, {checks.skipped} skipped")
    return 0 if checks.failed == 0 and checks.passed > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
