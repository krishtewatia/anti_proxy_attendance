"""The public demo: an admin, a teacher and a student anyone can try.

A visitor signs in with one click (POST /api/v1/auth/demo) and gets a token
marked as a demo token. Every request made with it works on the demo copy of
the collections (``demo__*``, see ``app.database.mongodb.DemoDatabase``), so a
visitor never sees or changes an organisation's real data. The demo copy is
set up on first use with the pilot catalog, its timetable, one administrator,
one teacher with classes and a section of fictional students without photos,
and it is wiped and set up again every PUBLIC_DEMO_RESET_HOURS.

The demo accounts have no usable password: the only way in is the demo
sign-in, and their passwords cannot be changed (see DEMO_BLOCKED_ROUTES).
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.core.account_status import ACCOUNT_APPROVED
from app.database import mongodb
from app.database.users import create_user, get_user_by_email
from app.schemas.auth import TokenResponse
from app.security.passwords import hash_password
from app.seed import pilot_catalog

logger = logging.getLogger(__name__)

DEMO_DOMAIN = "demo.antiproxy.app"
DEMO_ACCOUNTS = {
    "ADMIN": {"email": f"admin@{DEMO_DOMAIN}", "name": "Demo Administrator"},
    "TEACHER": {"email": f"teacher@{DEMO_DOMAIN}", "name": "Dr. Meera Iyer (demo)"},
    "STUDENT": {"email": f"student@{DEMO_DOMAIN}", "name": "Aarav Mehta (demo)"},
}
DEMO_SECTION = "A"
# Fictional classmates of the demo student; no photos, no face templates.
DEMO_CLASSMATES = [
    "Ananya Gupta",
    "Rohan Verma",
    "Ishita Singh",
    "Kabir Khanna",
    "Priya Nair",
    "Vivaan Joshi",
    "Sara Ali",
    "Arjun Reddy",
]
DEMO_ROLL_PREFIX = "99000000000"
# How many of section A's classes the demo teacher teaches.
DEMO_TEACHER_CLASSES = 4
DEMO_STATE = "demo_state"

# Routes a demo token may not use: they would lock other visitors out of the
# shared demo accounts.
DEMO_BLOCKED_ROUTES = (
    ("POST", "/api/v1/auth/change-password"),
    ("POST", "/api/v1/admin/users/", "/reset-password"),
)

_seed_lock = asyncio.Lock()
_SYSTEM_ACTOR = {"user_id": "system:demo", "role": "ADMIN"}


class DemoUnavailable(Exception):
    pass


def is_blocked(method: str, path: str) -> bool:
    for rule in DEMO_BLOCKED_ROUTES:
        if method != rule[0]:
            continue
        if len(rule) == 2 and path.rstrip("/") == rule[1]:
            return True
        if len(rule) == 3 and path.startswith(rule[1]) and path.endswith(rule[2]):
            return True
    return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _ensure_structure(db) -> None:
    """The pilot catalog and its timetable, in force from last week."""
    from app.services import organisation_service as org

    await mongodb.init_indexes(db)
    await org.seed_structure(db)
    # Demo accounts use the demo domain, not the organisation's.
    await db[org.SETTINGS].update_one(
        {"settings_id": org.SETTINGS_ID},
        {"$set": {"settings_id": org.SETTINGS_ID, "college_email_domain": DEMO_DOMAIN}},
        upsert=True,
    )
    today = date.today()
    await org.update_term_dates(
        db, pilot_catalog.TERM["term_id"], today - timedelta(days=60), today + timedelta(days=90)
    )
    if await db[org.VERSIONS].count_documents({}, limit=1) == 0:
        seed_dir = Path(__file__).resolve().parent.parent / "seed"
        text = (seed_dir / pilot_catalog.TIMETABLE_FILE).read_text(encoding="utf-8-sig")
        version = await org.import_timetable(
            db,
            pilot_catalog.COHORT["cohort_id"],
            text,
            source_name="demo timetable",
            actor_user_id=_SYSTEM_ACTOR["user_id"],
        )
        await org.activate_version(
            db,
            version["version_id"],
            today - timedelta(days=7),
            actor_user_id=_SYSTEM_ACTOR["user_id"],
        )


async def _section_class_ids(db) -> list[str]:
    from app.services import organisation_service as org

    query = {"audience.kind": "SECTION", "audience.section": DEMO_SECTION}
    ids = [c["class_id"] async for c in db[org.CLASSES].find(query, {"class_id": 1})]
    return sorted(ids)


async def _make_user(db, role: str, email: str) -> dict:
    user = await get_user_by_email(email)
    if user is None:
        await create_user(
            user_id=f"user_demo_{role.lower()}_{secrets.token_hex(4)}",
            email=email,
            # Unusable: nobody signs in to a demo account with a password.
            password_hash=hash_password(secrets.token_urlsafe(32)),
            role=role,
            status=ACCOUNT_APPROVED,
        )
        user = await get_user_by_email(email)
    await db["users"].update_one(
        {"user_id": user["user_id"]},
        {"$set": {"is_active": True, "status": ACCOUNT_APPROVED, "must_change_password": False}},
    )
    return await get_user_by_email(email)


async def _ensure_student(db, name: str, email: str, roll: str, class_ids: list[str]) -> dict:
    from app.schemas.student import StudentRegisterRequest
    from app.services.student_service import register_student_account

    if await get_user_by_email(email) is None:
        await register_student_account(
            StudentRegisterRequest(
                name=name,
                email=email,
                password=secrets.token_urlsafe(24),
                roll_number=roll,
            ),
            enrolled_by=_SYSTEM_ACTOR["user_id"],
            approved=True,
        )
    user = await get_user_by_email(email)
    profile = await db["student_profiles"].find_one({"user_id": user["user_id"]})
    identity = profile.get("identity") or profile.get("student_id")
    await db["student_profiles"].update_one(
        {"user_id": user["user_id"]},
        {"$set": {"branch": pilot_catalog.BRANCH["code"], "section": DEMO_SECTION}},
    )
    await db["enrolments"].update_one(
        {"user_id": user["user_id"], "term_id": pilot_catalog.TERM["term_id"]},
        {
            "$set": {
                "user_id": user["user_id"],
                "identity": identity,
                "term_id": pilot_catalog.TERM["term_id"],
                "cohort_id": pilot_catalog.COHORT["cohort_id"],
                "section": DEMO_SECTION,
                "choices": {},
                "class_ids": class_ids,
                "approved_request_id": "demo",
            },
            "$setOnInsert": {"since": _now()},
        },
        upsert=True,
    )
    await db["users"].update_one(
        {"user_id": user["user_id"]}, {"$set": {"must_change_password": False}}
    )
    return await get_user_by_email(email)


async def _ensure_teacher(db, class_ids: list[str]) -> dict:
    from app.schemas.teacher import TeacherRegisterRequest
    from app.services import teaching_service as teaching
    from app.services.teacher_service import register_teacher_account

    account = DEMO_ACCOUNTS["TEACHER"]
    if await get_user_by_email(account["email"]) is None:
        await register_teacher_account(
            TeacherRegisterRequest(
                name=account["name"],
                email=account["email"],
                password=secrets.token_urlsafe(24),
                department=pilot_catalog.BRANCH["department"],
            ),
            approved=True,
        )
    user = await _make_user(db, "TEACHER", account["email"])
    mine = class_ids[:DEMO_TEACHER_CLASSES]
    current = {
        c["class_id"] async for c in db["org_classes"].find({"teacher_ids": user["user_id"]})
    }
    if mine and current != set(mine):
        await teaching.set_teacher_classes(db, user["user_id"], mine, _SYSTEM_ACTOR)
    return user


async def ensure_demo() -> dict[str, dict]:
    """Set up whatever is missing in the demo copy; returns the three demo users by role."""
    async with _seed_lock:
        with mongodb.demo_scope():
            db = mongodb.get_database()
            await _ensure_structure(db)
            class_ids = await _section_class_ids(db)
            admin = await _make_user(db, "ADMIN", DEMO_ACCOUNTS["ADMIN"]["email"])
            teacher = await _ensure_teacher(db, class_ids)
            student = await _ensure_student(
                db,
                DEMO_ACCOUNTS["STUDENT"]["name"],
                DEMO_ACCOUNTS["STUDENT"]["email"],
                f"{DEMO_ROLL_PREFIX}00",
                class_ids,
            )
            for n, name in enumerate(DEMO_CLASSMATES, start=1):
                first = name.split()[0].lower()
                await _ensure_student(
                    db, name, f"{first}{n}@{DEMO_DOMAIN}", f"{DEMO_ROLL_PREFIX}{n:02d}", class_ids
                )
            await db[DEMO_STATE].update_one(
                {"_id": "state"},
                {"$setOnInsert": {"created_at": _now()}},
                upsert=True,
            )
            return {"ADMIN": admin, "TEACHER": teacher, "STUDENT": student}


async def sign_in(role: str) -> TokenResponse:
    from app.services.auth_service import issue_token

    from app.core.config import settings

    if not settings.PUBLIC_DEMO_ENABLED:
        raise DemoUnavailable("The demo is not available on this site.")
    role = role.upper()
    if role not in DEMO_ACCOUNTS:
        raise ValueError("Choose ADMIN, TEACHER or STUDENT.")
    users = await ensure_demo()
    return issue_token(users[role], demo=True)


async def _demo_photo_files(db) -> list[Path]:
    from app.core.uploads import student_photo_path

    paths: list[Path] = []
    async for profile in db["student_profiles"].find({}, {"identity": 1, "student_id": 1}):
        key = profile.get("identity") or profile.get("student_id")
        if not key:
            continue
        try:
            paths.append(student_photo_path(str(key)))
        except Exception:  # nosec B112 - an unusable key has no file to remove
            continue
    return paths


async def reset_demo() -> int:
    """Remove every demo collection (and demo student photos); returns how many were dropped."""
    async with _seed_lock:
        with mongodb.demo_scope():
            for path in await _demo_photo_files(mongodb.get_database()):
                path.unlink(missing_ok=True)
        real = mongodb.real_database()
        names = [n for n in await real.list_collection_names() if n.startswith(mongodb.DEMO_PREFIX)]
        for name in names:
            await real.drop_collection(name)
        return len(names)


async def demo_age() -> timedelta | None:
    with mongodb.demo_scope():
        state = await mongodb.get_database()[DEMO_STATE].find_one({"_id": "state"})
    if not state or not state.get("created_at"):
        return None
    created = state["created_at"]
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return _now() - created


async def reset_periodically() -> None:
    """Wipe the demo once it is older than PUBLIC_DEMO_RESET_HOURS; checked every 15 minutes."""
    from app.core.config import settings

    while True:
        try:
            age = await demo_age()
            if age is not None and age > timedelta(hours=settings.PUBLIC_DEMO_RESET_HOURS):
                dropped = await reset_demo()
                logger.info("Public demo reset: %d collections dropped", dropped)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Public demo reset failed")
        await asyncio.sleep(15 * 60)
