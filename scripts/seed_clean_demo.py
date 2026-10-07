#!/usr/bin/env python3
"""Bootstrap seeding script for the attendance system.

Always seeds:
  - 1 admin account and 1 teacher account (passwords can be overridden)
  - The academic catalog: branches, sections, classes, subjects
  - No sessions and no attendance records

Optionally seeds four demo students with face embeddings. That needs a local
biometric fixtures folder (VISION_FIXTURES_DIR, see the README). Without it,
or with --no-demo-students, no students are created: each student registers
through the web portal with their own photo.

WARNING: this script first PURGES the application collections in the target
database. Do not run it against a database whose data you want to keep.

Usage:
  python scripts/seed_clean_demo.py --no-demo-students
  python scripts/seed_clean_demo.py --admin-password '<pw>' --teacher-password '<pw>'
  python scripts/seed_clean_demo.py --dry-run
  python scripts/seed_clean_demo.py --inspect
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
from typing import Any

import bcrypt
from pymongo import MongoClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BENCHMARK_DIR = (
    Path(os.environ.get("VISION_FIXTURES_DIR") or "vision-fixtures-not-configured")
    / "recognition_benchmark"
)

# Target demo accounts and identities
ADMIN_EMAIL = "admin@system.local"
ADMIN_USER_ID = "user_admin_001"
DEFAULT_ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "AdminDevPass123!")

TEACHER_EMAIL = "teacher@demo.edu"
TEACHER_USER_ID = "user_teacher_demo"
TEACHER_NAME = "Dr. Example"
DEFAULT_TEACHER_PASSWORD = os.getenv("TEACHER_PASSWORD", "TeacherDevPass123!")

DEFAULT_STUDENT_PASSWORD = os.getenv("STUDENT_PASSWORD", "StudentDevPass123!")

STUDENT_SPECS = [
    {
        "index": 1,
        "name": "Alex Example",
        "email": "student1@demo.edu",
        "user_id": "user_student_001",
        "student_id": "DS202601",
        "roll_number": "12345",
        "branch": "Data Science",
        "section": "B",
        "class_code": "DS-B",
        "identity": "student1",
        "benchmark_folder": "person_01",
        "sample_count": 3,
    },
    {
        "index": 2,
        "name": "Blake Sample",
        "email": "student2@demo.edu",
        "user_id": "user_student_002",
        "student_id": "DS202602",
        "roll_number": "12346",
        "branch": "Data Science",
        "section": "B",
        "class_code": "DS-B",
        "identity": "student2",
        "benchmark_folder": "person_02",
        "sample_count": 5,
    },
    {
        "index": 3,
        "name": "Casey Placeholder",
        "email": "student3@demo.edu",
        "user_id": "user_student_003",
        "student_id": "DS202603",
        "roll_number": "12347",
        "branch": "Data Science",
        "section": "B",
        "class_code": "DS-B",
        "identity": "student3",
        "benchmark_folder": "person_03",
        "sample_count": 3,
    },
    {
        "index": 4,
        "name": "Devon Demo",
        "email": "student4@demo.edu",
        "user_id": "user_student_004",
        "student_id": "DS202604",
        "roll_number": "12348",
        "branch": "Data Science",
        "section": "B",
        "class_code": "DS-B",
        "identity": "student4",
        "benchmark_folder": "person_04",
        "sample_count": 3,
    },
]

ACADEMIC_CLASSES = [
    {"class_code": "DS-A", "branch": "Data Science", "section": "A"},
    {"class_code": "DS-B", "branch": "Data Science", "section": "B"},
    {"class_code": "DS-C", "branch": "Data Science", "section": "C"},
    {"class_code": "CS-A", "branch": "Computer Science", "section": "A"},
    {"class_code": "CS-B", "branch": "Computer Science", "section": "B"},
    {"class_code": "CS-C", "branch": "Computer Science", "section": "C"},
    {"class_code": "AIML-A", "branch": "AI & ML", "section": "A"},
    {"class_code": "AIML-B", "branch": "AI & ML", "section": "B"},
]

SUBJECTS = [
    {"code": "DS-201", "name": "Machine Learning", "branch": "Data Science"},
    {"code": "DS-202", "name": "Deep Learning", "branch": "Data Science"},
    {"code": "CS-101", "name": "Computer Networks", "branch": "Computer Science"},
    {"code": "CS-201", "name": "DBMS", "branch": "Computer Science"},
    {"code": "CS-302", "name": "DevOps", "branch": "Computer Science"},
    {"code": "CS-102", "name": "Data Structures", "branch": "Computer Science"},
    {"code": "AI-201", "name": "Artificial Intelligence", "branch": "AI & ML"},
]

COLLECTIONS_TO_PURGE = [
    "users",
    "student_profiles",
    "teacher_profiles",
    "biometric_profiles",
    "session_rosters",
    "session_roster",
    "sessions",
    "attendance_records",
    "academic_classes",
    "subjects",
    # Legacy surveillance collections to completely eliminate
    "cameras",
    "attendance_events",
    "attendance_corrections",
    "audit_events",
]


def hash_password(password: str) -> str:
    """Hash password using genuine bcrypt gensalt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def normalize_vector(vec: list[float] | Any) -> list[float]:
    """Ensure vector has exactly 512 floats and L2 unit norm = 1.0."""
    if len(vec) != 512:
        raise ValueError(f"Expected 512 dimensions, got {len(vec)}")
    norm = math.sqrt(sum(float(x) * float(x) for x in vec))
    if norm <= 0:
        raise ValueError("Cannot normalize zero-vector")
    return [float(x) / norm for x in vec]


def connect_mongo(
    uri_arg: str | None = None, db_name: str = "anti_proxy_attendance"
) -> tuple[MongoClient, str]:
    """Connect to MongoDB with authenticated credentials and fallback logic."""
    candidates: list[str] = []
    if uri_arg:
        candidates.append(uri_arg)
    env_uri = os.getenv("MONGODB_URL") or os.getenv("MONGO_URI")
    if env_uri and env_uri not in candidates:
        candidates.append(env_uri)

    default_app_uri = (
        "mongodb://antiproxy_user:secure_app_mongo_dev_password_12345@localhost:27017/"
        f"{db_name}?authSource={db_name}"
    )
    root_uri = (
        "mongodb://admin:secure_root_mongo_dev_password_12345@localhost:27017/"
        f"{db_name}?authSource=admin"
    )
    unauthenticated_uri = f"mongodb://localhost:27017/{db_name}"

    for u in [default_app_uri, root_uri, unauthenticated_uri]:
        if u not in candidates:
            candidates.append(u)

    last_error: Exception | None = None
    for uri in candidates:
        try:
            client = MongoClient(uri, serverSelectionTimeoutMS=3000)
            client.admin.command("ping")
            return client, uri
        except Exception as exc:
            last_error = exc
            continue

    raise RuntimeError(f"Failed to connect to MongoDB with candidates {candidates}: {last_error}")


def load_tier3_benchmark_json() -> tuple[dict[str, list[float]], str]:
    """Load authentic pre-extracted InsightFace ArcFace 512-d embeddings."""
    candidate_paths = [
        Path(os.environ.get("VISION_FIXTURES_DIR") or "vision-fixtures-not-configured")
        / "benchmark_embeddings.json",
    ]
    id_map = {s.get("benchmark_folder", s["identity"]): s["identity"] for s in STUDENT_SPECS}
    for p in candidate_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
                data = {id_map.get(k, k): v for k, v in raw_data.items()}
                if all(s["identity"] in data for s in STUDENT_SPECS):
                    return {
                        s["identity"]: data[s["identity"]] for s in STUDENT_SPECS
                    }, f"Authentic Vectors File ({p.name})"
            except Exception:
                continue

    raise RuntimeError(
        "Unable to load benchmark embeddings. Biometric fixtures are not stored in git: set "
        "VISION_FIXTURES_DIR to the local fixtures folder containing benchmark_embeddings.json "
        "(see 'Biometric Test Fixtures' in the README)."
    )


def inspect_database(client: MongoClient, db_name: str) -> None:
    """Print current collection inventory and document counts."""
    db = client[db_name]
    print(f"\n{'=' * 70}\nDATABASE INSPECTION: {db_name}\n{'=' * 70}")
    colls = sorted(db.list_collection_names())
    if not colls:
        print("  (Database currently has no collections)")
    for c in colls:
        cnt = db[c].count_documents({})
        doc = db[c].find_one()
        fields = list(doc.keys()) if doc else []
        print(f"  • {c:25s}: {cnt:4d} docs | keys: {fields[:6]}")
    print(f"{'=' * 70}\n")


def purge_database(client: MongoClient, db_name: str) -> dict[str, int]:
    """Purge synthetic mock data, old surveillance collections, and test sessions."""
    db = client[db_name]
    deleted_counts: dict[str, int] = {}
    for col_name in COLLECTIONS_TO_PURGE:
        res = db[col_name].delete_many({})
        deleted_counts[col_name] = res.deleted_count
    return deleted_counts


def seed_database(
    client: MongoClient,
    db_name: str,
    embeddings: dict[str, list[float]],
    admin_pw: str,
    teacher_pw: str,
    student_pw: str,
) -> dict[str, Any]:
    """Insert the admin, the teacher, the academic catalog, and any demo students
    for which an embedding was supplied (none when ``embeddings`` is empty)."""
    db = client[db_name]
    now = dt.datetime.now(dt.timezone.utc)

    # 1. Admin User
    admin_hash = hash_password(admin_pw)
    admin_doc = {
        "user_id": ADMIN_USER_ID,
        "email": ADMIN_EMAIL,
        "name": "System Administrator",
        "password_hash": admin_hash,
        "role": "ADMIN",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    db.users.insert_one(admin_doc)

    # 2. Teacher User & Profile
    teacher_hash = hash_password(teacher_pw)
    teacher_doc = {
        "user_id": TEACHER_USER_ID,
        "email": TEACHER_EMAIL,
        "name": TEACHER_NAME,
        "password_hash": teacher_hash,
        "role": "TEACHER",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    db.users.insert_one(teacher_doc)

    db.teacher_profiles.insert_one(
        {
            "user_id": TEACHER_USER_ID,
            "teacher_id": "T001",
            "name": TEACHER_NAME,
            "email": TEACHER_EMAIL,
            "department": "Data Science",
            "assigned_classes": ["DS-B", "DS-C"],
            "assigned_subjects": ["Machine Learning", "Deep Learning"],
            "created_at": now,
            "updated_at": now,
        }
    )

    # 3. Exactly 4 Students, Student Profiles, and Biometric Profiles (DS-B)
    student_hash = hash_password(student_pw)
    seeded_students: list[dict[str, Any]] = []

    for spec in STUDENT_SPECS:
        ident = spec["identity"]
        if ident not in embeddings:
            # No biometric fixture for this demo student: students register themselves
            continue
        uid = spec["user_id"]
        sid = spec["student_id"]
        roll = spec["roll_number"]
        name = spec["name"]
        email = spec["email"]
        branch = spec["branch"]
        section = spec["section"]
        class_code = spec["class_code"]
        sample_count = spec["sample_count"]

        # Clean normalized 512-d embedding
        unit_emb = normalize_vector(embeddings[ident])

        # users
        db.users.insert_one(
            {
                "user_id": uid,
                "email": email,
                "name": name,
                "student_id": sid,
                "password_hash": student_hash,
                "role": "STUDENT",
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
        )

        # student_profiles
        db.student_profiles.insert_one(
            {
                "user_id": uid,
                "identity": ident,
                "student_id": sid,
                "roll_number": roll,
                "name": name,
                "email": email,
                "branch": branch,
                "section": section,
                "class_code": class_code,
                "has_biometric": True,
                "created_at": now,
                "updated_at": now,
            }
        )

        # biometric_profiles
        db.biometric_profiles.insert_one(
            {
                "identity": ident,
                "student_id": sid,
                "mean_embedding": unit_emb,
                "sample_count": sample_count,
                "quality_score": 0.95,
                "status": "ENROLLED",
                "enrolled_by": TEACHER_USER_ID,
                "created_at": now,
                "updated_at": now,
            }
        )

        seeded_students.append({"name": name, "email": email, "id": sid, "class": class_code})

    # 4. Academic Structure (Classes and Subjects)
    for c in ACADEMIC_CLASSES:
        db.academic_classes.insert_one(
            {
                "class_id": c["class_code"],
                "class_code": c["class_code"],
                "branch": c["branch"],
                "section": c["section"],
                "is_active": True,
                "created_at": now,
            }
        )

    for s in SUBJECTS:
        db.subjects.insert_one(
            {
                "subject_id": s["code"],
                "code": s["code"],
                "name": s["name"],
                "branch": s["branch"],
                "is_active": True,
                "created_at": now,
            }
        )

    # Verification counts
    counts = {
        col: db[col].count_documents({})
        for col in [
            "users",
            "student_profiles",
            "teacher_profiles",
            "biometric_profiles",
            "academic_classes",
            "subjects",
            "sessions",
            "attendance_records",
        ]
    }
    return {
        "admin": ADMIN_EMAIL,
        "teacher": TEACHER_EMAIL,
        "students": seeded_students,
        "counts": counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 2 Clean Database Seeding (No Fake Sessions)"
    )
    parser.add_argument("--mongo-uri", default=None, help="MongoDB connection URI")
    parser.add_argument(
        "--db-name",
        default=os.getenv("DATABASE_NAME") or os.getenv("MONGO_DB") or "anti_proxy_attendance",
        help="Database name (default: anti_proxy_attendance)",
    )
    parser.add_argument("--admin-password", default=DEFAULT_ADMIN_PASSWORD, help="Admin password")
    parser.add_argument(
        "--teacher-password", default=DEFAULT_TEACHER_PASSWORD, help="Teacher password"
    )
    parser.add_argument(
        "--student-password", default=DEFAULT_STUDENT_PASSWORD, help="Student password"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Test connection and biometrics without writing"
    )
    parser.add_argument(
        "--no-demo-students",
        action="store_true",
        help="Seed only the admin, the teacher and the academic catalog (no demo students)",
    )
    parser.add_argument(
        "--inspect", action="store_true", help="Inspect database document counts and exit"
    )

    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("PHASE 2: CLEAN COLLEGE ATTENDANCE DATABASE SEEDING")
    print("=" * 70)

    # 1. Connect to MongoDB
    client, active_uri = connect_mongo(args.mongo_uri, args.db_name)
    sanitized_uri = active_uri.split("@")[-1] if "@" in active_uri else active_uri
    print(f"[OK] Connected to MongoDB ({sanitized_uri}) | Database: {args.db_name}")

    if args.inspect:
        inspect_database(client, args.db_name)
        client.close()
        return

    # 2. Extract Biometric Embeddings
    embeddings: dict[str, list[float]] = {}
    if args.no_demo_students:
        print("[INFO] --no-demo-students: seeding admin, teacher and academic catalog only.")
    else:
        try:
            embeddings, loader_tier = load_tier3_benchmark_json()
            print(f"[OK] Biometric Embeddings Source: {loader_tier}")
        except RuntimeError:
            print(
                "[INFO] No biometric fixtures found (VISION_FIXTURES_DIR is not set or has no "
                "benchmark_embeddings.json)."
            )
            print(
                "       Seeding admin, teacher and academic catalog only. Students register "
                "through the web portal with their own photos."
            )
    for ident, vec in embeddings.items():
        norm = math.sqrt(sum(x * x for x in vec))
        print(f"     • {ident:10s}: {len(vec)}-dimensional vector | L2 norm: {norm:.6f}")

    if args.dry_run:
        print("\n[INFO] Dry run requested. No database records modified.")
        client.close()
        return

    # 3. Purge Collections
    print(f"\n[INFO] Purging old mock/test data from '{args.db_name}'...")
    purged = purge_database(client, args.db_name)
    for col, count in purged.items():
        if count > 0:
            print(f"     • Purged {count:4d} documents from {col}")
    print("[OK] Purge complete. All fake data eradicated.")

    # 4. Seed Database
    print("\n[INFO] Seeding authentic Phase 2 dataset...")
    result = seed_database(
        client=client,
        db_name=args.db_name,
        embeddings=embeddings,
        admin_pw=args.admin_password,
        teacher_pw=args.teacher_password,
        student_pw=args.student_password,
    )
    print("[OK] Seed operation complete.")

    # 5. Display Clean Summary and Credentials Table
    print("\n" + "=" * 70)
    print("DEMO CREDENTIALS & SEED SUMMARY")
    print("=" * 70)
    print("  ADMIN ACCOUNT (Total: 1):")
    print(f"    Email    : {ADMIN_EMAIL}")
    print(f"    Password : {args.admin_password}")
    print("    Role     : ADMIN\n")

    print("  TEACHER ACCOUNT (Total: 1):")
    print(f"    Email    : {TEACHER_EMAIL}")
    print(f"    Password : {args.teacher_password}")
    print(f"    Name     : {TEACHER_NAME}")
    print("    Assigned : DS-B, DS-C | Subjects: Machine Learning, Deep Learning\n")

    seeded_ids = {st["id"] for st in result["students"]}
    if seeded_ids:
        print(f"  DEMO STUDENT ACCOUNTS (Total: {len(seeded_ids)}, All in DS-B):")
        for s in STUDENT_SPECS:
            if s["student_id"] not in seeded_ids:
                continue
            print(
                f"    • {s['name']:14s} | ID: {s['student_id']:8s} | Roll: {s['roll_number']:5s} | "
                f"Class: {s['class_code']} | Email: {s['email']}"
            )
    else:
        print("  STUDENT ACCOUNTS: none seeded.")
        print("    Students register at the web portal with their own photo.")

    print("\n  ACADEMIC STRUCTURE:")
    print("    Classes  : DS-A, DS-B, DS-C, CS-A, CS-B, CS-C, AIML-A, AIML-B")
    print("    Subjects : Machine Learning, Deep Learning, DBMS, DevOps, etc.")

    print("\n  SESSIONS & ATTENDANCE:")
    print("    Active Sessions   : 0 (No fake sessions)")
    print("    Attendance Records: 0 (No fake attendance records)")

    print("\n  FINAL MONGODB COLLECTION COUNTS:")
    for col, count in result["counts"].items():
        print(f"    • {col:22s}: {count:2d} documents")
    print("=" * 70 + "\n")

    client.close()


if __name__ == "__main__":
    main()
