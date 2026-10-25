"""Seed the pilot's structure and catalog, and import its timetable.

    python -m app.tools.seed_pilot                        structure and catalog only
    python -m app.tools.seed_pilot --timetable            also check the bundled timetable (dry run)
    python -m app.tools.seed_pilot --timetable --apply    also store it as a draft version
    python -m app.tools.seed_pilot --timetable --apply --activate 2026-11-02

Safe to run again. It never assigns teachers and never touches students,
sessions or attendance. The same steps are available to an administrator
through /api/v1/admin/org/*.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date
from pathlib import Path
import sys

from app.database.mongodb import get_database, init_indexes
from app.seed import pilot_catalog
from app.services import organisation_service as org

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"


async def run(args: argparse.Namespace) -> int:
    db = get_database()
    await init_indexes(db)
    seeded = await org.seed_structure(db)
    print(f"Structure: {seeded}")
    if not args.timetable:
        return 0

    path = Path(args.file) if args.file else SEED_DIR / pilot_catalog.TIMETABLE_FILE
    text = path.read_text(encoding="utf-8-sig")
    cohort_id = pilot_catalog.COHORT["cohort_id"]
    report = (await org.plan_timetable_import(db, cohort_id, text)).report()
    print(
        f"Timetable {path.name}: {report['rows']} rows, {report['slots']} slots, "
        f"{report['classes']} classes ({report['section_classes']} section, {report['group_classes']} group)"
    )
    print(f"Flags: {report['flag_counts'] or 'none'}")
    for error in report["errors"]:
        print(f"  ERROR row {error['row']}: {error['message']}")
    if report["errors"]:
        return 1
    if not args.apply:
        print("Dry run: nothing stored. Add --apply to store it as a draft version.")
        return 0

    version = await org.import_timetable(
        db, cohort_id, text, source_name=path.name, actor_user_id="system:seed_pilot"
    )
    print(f"Stored as draft version {version['version_id']}")
    if args.activate:
        active = await org.activate_version(
            db,
            version["version_id"],
            date.fromisoformat(args.activate),
            actor_user_id="system:seed_pilot",
        )
        print(f"Active from {active['effective_from']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--timetable", action="store_true", help="also check the timetable")
    parser.add_argument(
        "--file", help="timetable CSV (default: the bundled DS 3rd-year Sem V sheet)"
    )
    parser.add_argument(
        "--apply", action="store_true", help="store the timetable as a draft version"
    )
    parser.add_argument(
        "--activate", metavar="YYYY-MM-DD", help="activate the stored version from this date"
    )
    args = parser.parse_args()
    if args.activate and not args.apply:
        parser.error("--activate needs --apply")
    try:
        return asyncio.run(run(args))
    except org.OrganisationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
