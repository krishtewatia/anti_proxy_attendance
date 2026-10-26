#!/usr/bin/env python3
"""Load test for one period of the pilot: four sections in class at once.

Measures only; changes nothing in the application. It runs against the local
Docker stack (docker compose up) and refuses any other address. The data it
adds is made up, carries the prefix ``lt_`` and is removed at the end.

What one run does:

* four teachers (Sections A-D) start the same period's session from the
  timetable, open ENTRY, send camera frames at a classroom rate, switch to
  EXIT, send frames again and end the session. Like the teacher's page, each
  camera keeps one frame in flight and sends the next one as soon as the
  answer is back (checking every 250 ms), at 640x480;
* at the same time all students (70 per section) open their dashboard and
  their subject-wise attendance within the first minute;
* afterwards each teacher opens the class overview and the register and makes
  a burst of hand corrections.

The frames are random pictures with no face in them (made by the vision
container's own OpenCV): the pipeline and the vision service do their full
per-frame work, and no biometric data is involved.

Usage (from the repository root, with the stack running):

    backend/.venv/Scripts/python.exe scripts/load_test.py            # Windows
    backend/.venv/bin/python scripts/load_test.py --frame-seconds 60  # shorter

It needs the throwaway load-test copy of the stack (own containers and
volumes, limited to about the t3.small's size) with the pilot timetable:

    docker compose -p antiproxy-loadtest -f docker-compose.yml -f docker-compose.loadtest.yml up -d --build
    docker exec antiproxy-lt-backend python -m app.tools.seed_pilot --timetable --apply --activate 2026-11-02
    ... run the load test ...
    docker compose -p antiproxy-loadtest -f docker-compose.yml -f docker-compose.loadtest.yml down
    docker volume rm antiproxy_lt_mongo_data antiproxy_lt_vision_outbox antiproxy_lt_uploads

Results go to docs/operations/load_test_results.md.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import random
import statistics
import subprocess  # nosec B404 - fixed docker commands only
import sys
import time
from typing import Any
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
PREFIX = "lt_"
SECTIONS = ("A", "B", "C", "D")
VISION_CONTAINER = "antiproxy-lt-vision-service"
TARGETS = {"frame_p95_s": 1.5, "page_p95_s": 1.0}


def is_local(url: str) -> bool:
    return (urllib.parse.urlsplit(url).hostname or "") in LOCAL_HOSTS


def load_env(path: Path) -> dict[str, str]:
    """KEY=VALUE lines of the local .env; values are used, never printed."""
    values: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and not name.startswith("#"):
                values[name.strip()] = value.strip().strip("'\"")
    return values


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return (
        ordered[min(len(ordered) - 1, int(round(share * (len(ordered) - 1))))] if ordered else 0.0
    )


class Recorder:
    def __init__(self) -> None:
        self.calls: dict[str, list[tuple[float, int]]] = {}

    def add(self, name: str, seconds: float, status: int) -> None:
        self.calls.setdefault(name, []).append((seconds, status))

    def rows(self) -> list[dict[str, Any]]:
        out = []
        for name, calls in sorted(self.calls.items()):
            times = [t for t, _ in calls]
            out.append(
                {
                    "name": name,
                    "count": len(calls),
                    "p50": statistics.median(times),
                    "p95": percentile(times, 0.95),
                    "max": max(times),
                    "4xx": sum(1 for _, s in calls if 400 <= s < 500),
                    "5xx": sum(1 for _, s in calls if s >= 500 or s == 0),
                }
            )
        return out


async def timed(rec: Recorder, client, name: str, method: str, url: str, **kwargs):
    started = time.perf_counter()
    try:
        response = await client.request(method, url, **kwargs)
        status = response.status_code
    except Exception:  # a timeout or refused connection counts as a failure
        response, status = None, 0
    rec.add(name, time.perf_counter() - started, status)
    return response


def make_frame() -> bytes:
    code = (
        "import cv2, numpy as np, sys;"
        "img = cv2.GaussianBlur(np.random.default_rng(7).integers(0, 255, (480, 640, 3), dtype=np.uint8), (0, 0), 3);"
        "ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 80]);"
        "sys.stdout.buffer.write(buf.tobytes())"
    )
    result = subprocess.run(  # nosec B603 B607 - fixed command
        ["docker", "exec", VISION_CONTAINER, "python", "-c", code], capture_output=True, check=True
    )
    return result.stdout


def sample_docker_stats(samples: list[dict[str, str]], stop: asyncio.Event) -> asyncio.Task:
    async def loop() -> None:
        while not stop.is_set():
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{json .}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await proc.communicate()
            for line in out.decode(errors="replace").splitlines():
                try:
                    samples.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass

    return asyncio.create_task(loop())


def _peak_stats(samples: list[dict[str, str]]) -> list[tuple[str, float, str]]:
    peak: dict[str, tuple[float, str]] = {}
    for s in samples:
        name = s.get("Name", "?")
        cpu = float(s.get("CPUPerc", "0%").rstrip("%") or 0)
        if cpu >= peak.get(name, (-1.0, ""))[0]:
            peak[name] = (cpu, s.get("MemUsage", ""))
    return [(name, cpu, mem) for name, (cpu, mem) in sorted(peak.items())]


# ------------------------------------------------------------------ data


async def seed(db, students_per_section: int) -> dict[str, Any]:
    from app.database.users import create_user
    from app.services import organisation_service as org

    if await db["timetable_versions"].count_documents({"status": "ACTIVE"}) == 0:
        sys.exit(
            "No active timetable in the local database. Run in the backend folder:\n"
            "  python -m app.tools.seed_pilot --timetable --apply --activate 2026-11-02"
        )
    by_time: dict[tuple[str, str], dict[str, dict]] = {}
    async for slot in db[org.SLOTS].find({"audience.kind": "SECTION"}):
        by_time.setdefault((slot["day"], slot["start"]), {})[slot["audience"]["section"]] = slot
    common = sorted(k for k, v in by_time.items() if all(s in v for s in SECTIONS))
    if not common:
        sys.exit("No period in which all four sections have a class.")
    day_code, start = common[0]
    slots = by_time[(day_code, start)]
    days = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]
    # A date far ahead, on that weekday, that has no session for these slots yet.
    day = date.today() + timedelta(days=60)
    while True:
        day += timedelta(days=(days.index(day_code) - day.weekday()) % 7)
        taken = await db["sessions"].count_documents(
            {"slot_id": {"$in": [s["slot_id"] for s in slots.values()]}, "date": day.isoformat()}
        )
        if not taken:
            break
        day += timedelta(days=7)

    teachers, students = {}, {}
    for section in SECTIONS:
        teacher_id = f"{PREFIX}t_{section}"
        await create_user(
            user_id=teacher_id,
            email=f"{teacher_id}@niet.co.in",
            password_hash="x",
            role="TEACHER",
            status="APPROVED",
        )
        await db[org.CLASSES].update_one(
            {"class_id": slots[section]["class_id"]}, {"$addToSet": {"teacher_ids": teacher_id}}
        )
        teachers[section] = teacher_id
        cohort = (
            slots[section].get("cohort_id")
            or (await db[org.CLASSES].find_one({"class_id": slots[section]["class_id"]}))[
                "cohort_id"
            ]
        )
        class_ids = [
            c["class_id"]
            async for c in db[org.CLASSES].find({"cohort_id": cohort, "audience.section": section})
        ]
        students[section] = []
        for n in range(students_per_section):
            user_id = f"{PREFIX}s_{section}{n:02d}"
            identity = f"{PREFIX}stu_{section.lower()}{n:02d}"
            await create_user(
                user_id=user_id,
                email=f"{user_id}@niet.co.in",
                password_hash="x",
                role="STUDENT",
                status="APPROVED",
            )
            await db["student_profiles"].insert_one(
                {
                    "user_id": user_id,
                    "identity": identity,
                    "student_id": identity,
                    "name": f"Load Test {section}{n:02d}",
                    "roll_number": f"9900{ord(section):03d}{n:03d}",
                    "email": f"{user_id}@niet.co.in",
                }
            )
            await db["enrolments"].insert_one(
                {
                    "user_id": user_id,
                    "identity": identity,
                    "cohort_id": cohort,
                    "section": section,
                    "choices": {},
                    "class_ids": class_ids,
                }
            )
            students[section].append(user_id)
    return {"day": day, "slots": slots, "teachers": teachers, "students": students}


async def cleanup(db) -> None:
    from app.services import organisation_service as org

    users = [
        u["user_id"]
        async for u in db["users"].find({"user_id": {"$regex": f"^{PREFIX}"}}, {"user_id": 1})
    ]
    teachers = [u for u in users if u.startswith(f"{PREFIX}t_")]
    sessions = [
        s["session_id"]
        async for s in db["sessions"].find({"created_by": {"$in": teachers}}, {"session_id": 1})
    ]
    for name in (
        "session_rosters",
        "attendance_records",
        "attendance_corrections",
        "recognition_nonces",
    ):
        await db[name].delete_many({"session_id": {"$in": sessions}})
    await db["sessions"].delete_many({"session_id": {"$in": sessions}})
    for name in ("student_profiles", "enrolments", "teacher_profiles"):
        await db[name].delete_many({"user_id": {"$in": users}})
    await db["audit_events"].delete_many({"actor_user_id": {"$in": users}})
    await db[org.CLASSES].update_many({}, {"$pull": {"teacher_ids": {"$in": teachers}}})
    await db["users"].delete_many({"user_id": {"$in": users}})


# ------------------------------------------------------------------ the period


async def teacher_period(
    client, rec: Recorder, auth: dict, slot: dict, day: date, frame: bytes, seconds: int
) -> str | None:
    started = await timed(
        rec,
        client,
        "teacher: start from slot",
        "POST",
        "/api/v1/teachers/sessions/from-slot",
        headers=auth,
        json={"slot_id": slot["slot_id"], "date": day.isoformat()},
    )
    if started is None or started.status_code >= 400:
        return None
    sid = started.json()["session_id"]
    await timed(
        rec, client, "teacher: start", "POST", f"/api/v1/sessions/{sid}/start", headers=auth
    )
    for round_name in ("ENTRY", "EXIT"):
        await timed(
            rec,
            client,
            "teacher: open round",
            "POST",
            f"/api/v1/sessions/{sid}/rounds/{round_name}/open",
            headers=auth,
        )
        until = time.perf_counter() + seconds / 2
        while time.perf_counter() < until:
            began = time.perf_counter()
            await timed(
                rec,
                client,
                "frame",
                "POST",
                f"/api/v1/attendance/{sid}/process-frame",
                headers={**auth, "Content-Type": "image/jpeg"},
                content=frame,
            )
            await asyncio.sleep(max(0.0, 0.25 - (time.perf_counter() - began)))
        await timed(
            rec, client, "teacher: dashboard", "GET", "/api/v1/teachers/dashboard", headers=auth
        )
    await timed(
        rec,
        client,
        "teacher: end session",
        "POST",
        f"/api/v1/sessions/{sid}/finalize",
        headers=auth,
    )
    return sid


async def student_visit(client, rec: Recorder, auth: dict, within: float) -> None:
    await asyncio.sleep(random.uniform(0, within))  # nosec B311 - spreading load, not security
    for name, path in (
        ("student: me", "/api/v1/students/me"),
        ("student: dashboard", "/api/v1/students/dashboard"),
        ("student: setup", "/api/v1/enrolment/me"),
        ("student: subjects", "/api/v1/students/attendance/subjects"),
    ):
        await timed(rec, client, name, "GET", path, headers=auth)


async def after_class(
    client, rec: Recorder, auth: dict, class_id: str, sid: str, identities: list[str]
) -> None:
    base = f"/api/v1/teachers/classes/{urllib.parse.quote(class_id, safe='')}"
    await timed(rec, client, "teacher: class overview", "GET", f"{base}/students", headers=auth)
    await timed(rec, client, "teacher: register csv", "GET", f"{base}/register.csv", headers=auth)
    await timed(
        rec, client, "teacher: session sheet", "GET", f"{base}/sessions/{sid}", headers=auth
    )
    for identity in identities[:20]:
        await timed(
            rec,
            client,
            "teacher: hand mark",
            "POST",
            f"/api/v1/sessions/{sid}/rounds/EXIT/marks",
            headers=auth,
            json={"identity": identity, "status": "PRESENT"},
        )


def write_report(path: Path, args, plan: dict, rec: Recorder, peaks, wall: float) -> bool:
    rows = rec.rows()
    frame = next((r for r in rows if r["name"] == "frame"), None)
    pages = [r for r in rows if r["name"] != "frame"]
    page_p95 = max((r["p95"] for r in pages), default=0.0)
    errors = sum(r["5xx"] for r in rows)
    ok = (
        bool(frame)
        and frame["p95"] < TARGETS["frame_p95_s"]
        and page_p95 < TARGETS["page_p95_s"]
        and errors == 0
    )
    lines = [
        "# Load test results",
        "",
        f"Run {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} against the local stack "
        f"({'limited to 2 vCPU / 2 GB like the t3.small' if args.limited else 'without size limits'}).",
        "",
        f"One period, four sections at once: {len(SECTIONS)} teachers, {args.students * len(SECTIONS)} students, "
        f"{args.frame_seconds} s of frames per session (640x480, one in flight per camera, no faces). Wall time {wall:.0f} s.",
        "",
        f"Each camera got an answer {frame['count'] / len(SECTIONS) / args.frame_seconds:.2f} times a second on average."
        if frame
        else "No frame was answered.",
        "",
        "| Call | Count | p50 (s) | p95 (s) | max (s) | 4xx | 5xx/failed |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['name']} | {r['count']} | {r['p50']:.3f} | {r['p95']:.3f} | {r['max']:.3f} | {r['4xx']} | {r['5xx']} |"
        )
    lines += [
        "",
        "Peak per container during the run:",
        "",
        "| Container | CPU % | Memory |",
        "|---|---:|---|",
    ]
    for name, cpu, mem in peaks:
        lines.append(f"| {name} | {cpu:.0f} | {mem} |")
    lines += [
        "",
        f"Targets: p95 frame < {TARGETS['frame_p95_s']} s, p95 of every page call < {TARGETS['page_p95_s']} s, no 5xx.",
        f"**Result: {'PASS' if ok else 'NOT MET'}** (frame p95 {frame['p95'] if frame else float('nan'):.2f} s, "
        f"slowest page p95 {page_p95:.2f} s, {errors} failed).",
        "",
        "Made-up data with the prefix `lt_` was added for the run and removed afterwards.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return ok


async def main_async(args) -> int:
    env = load_env(ROOT / ".env")
    db_name = env.get("DATABASE_NAME") or "anti_proxy_attendance"
    user = env.get("MONGO_APP_USERNAME") or "antiproxy_user"
    password = env.get("MONGO_APP_PASSWORD") or "antiproxy_secure_password"
    mongo = args.mongo_url or (
        f"mongodb://{urllib.parse.quote(user)}:{urllib.parse.quote(password)}@127.0.0.1:27017/{db_name}?authSource={db_name}"
    )
    if not is_local(args.base_url) or not is_local(mongo):
        print("The load test runs only against this machine (localhost / 127.0.0.1).")
        return 2
    os.environ.update({"MONGODB_URL": mongo, "DATABASE_NAME": db_name})
    if env.get("JWT_SECRET_KEY"):
        os.environ["JWT_SECRET_KEY"] = env["JWT_SECRET_KEY"]
    sys.path.insert(0, str(ROOT / "backend"))
    import httpx

    from app.database.mongodb import get_database
    from app.security.jwt import create_access_token

    db = get_database()
    await cleanup(db)  # leftovers of an interrupted run
    frame = make_frame()
    print(f"Seeding {args.students} students x {len(SECTIONS)} sections ...")
    plan = await seed(db, args.students)
    auth = {
        u: {"Authorization": f"Bearer {create_access_token(user_id=u, role=r)}"}
        for u, r in [(t, "TEACHER") for t in plan["teachers"].values()]
        + [(s, "STUDENT") for ss in plan["students"].values() for s in ss]
    }
    rec, samples, stop = Recorder(), [], asyncio.Event()
    stats = sample_docker_stats(samples, stop)
    began = time.perf_counter()
    limits = httpx.Limits(max_connections=400, max_keepalive_connections=100)
    try:
        async with httpx.AsyncClient(base_url=args.base_url, timeout=30, limits=limits) as client:
            print(f"Running the period on {plan['day']} ({args.frame_seconds} s of frames) ...")
            teacher_jobs = [
                teacher_period(
                    client,
                    rec,
                    auth[plan["teachers"][s]],
                    plan["slots"][s],
                    plan["day"],
                    frame,
                    args.frame_seconds,
                )
                for s in SECTIONS
            ]
            student_jobs = [
                student_visit(client, rec, auth[u], 60)
                for ss in plan["students"].values()
                for u in ss
            ]
            results = await asyncio.gather(*teacher_jobs, *student_jobs)
            sessions = results[: len(SECTIONS)]
            identities = {
                s: [
                    p["identity"]
                    async for p in db["student_profiles"].find(
                        {"user_id": {"$in": plan["students"][s]}}, {"identity": 1}
                    )
                ]
                for s in SECTIONS
            }
            await asyncio.gather(
                *[
                    after_class(
                        client,
                        rec,
                        auth[plan["teachers"][s]],
                        plan["slots"][s]["class_id"],
                        sid,
                        identities[s],
                    )
                    for s, sid in zip(SECTIONS, sessions)
                    if sid
                ]
            )
    finally:
        stop.set()
        await stats
        if not args.keep_data:
            await cleanup(db)
    ok = write_report(
        ROOT / args.out, args, plan, rec, _peak_stats(samples), time.perf_counter() - began
    )
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--mongo-url", default="", help="default: the local stack's database, from .env"
    )
    parser.add_argument("--students", type=int, default=70, help="students per section")
    parser.add_argument(
        "--frame-seconds", type=int, default=120, help="seconds of frames per session"
    )
    parser.add_argument(
        "--limited",
        action="store_true",
        help="say in the report that the stack ran with the t3.small limits",
    )
    parser.add_argument(
        "--keep-data", action="store_true", help="leave the made-up data for a look afterwards"
    )
    parser.add_argument("--out", default="docs/operations/load_test_results.md")
    args = parser.parse_args(argv)
    if not is_local(args.base_url):
        print("The load test runs only against this machine (localhost / 127.0.0.1).")
        return 2
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
