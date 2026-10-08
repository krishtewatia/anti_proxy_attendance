"""One-time migration of student photos into the uploads volume.

Older versions stored photos under ``backend/uploads/`` in the source tree.
This command copies every photo from that folder into the uploads directory
(the ``anti_proxy_uploads`` volume in Docker), checks each one against the
student record it belongs to, and reports what happened. It also writes out
photos that exist only inside a student record. It never deletes anything.

Run it in the backend container with the old folder mounted read-only (from
the folder that holds docker-compose.yml)::

    docker compose run --rm --no-deps \\
        -v "/path/to/old/backend/uploads:/legacy_uploads:ro" \\
        backend python -m app.tools.migrate_uploads --source /legacy_uploads

Add ``--dry-run`` first to see what it would do.

How a photo is checked against its student record, in this order:

1. The record holds its own copy of the photo: the bytes must be identical.
2. Otherwise the student's enrolled face template is used: the vision service
   extracts a face from the photo and it must match the template.
3. If neither is possible (the vision service is not running, or the student
   has no template) the photo is "unverified" and is not copied unless
   ``--include-unverified`` is given.

A photo that matches no student, or that fails a check, is not copied.

Only identifiers, counts and hashes prefixes are printed. No image data.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import sys
from typing import Any, Awaitable, Callable, Optional

from app.core.uploads import get_student_photos_dir, student_photo_path

IMAGE_SUFFIXES = {".jpg", ".jpeg"}
# Same decision the recognition path uses for "this is the same person".
FACE_MATCH_THRESHOLD = 0.50

COPIED = "copied"
ALREADY_PRESENT = "already_present"
RESTORED_FROM_RECORD = "restored_from_record"
SKIPPED_NO_RECORD = "skipped_no_student_record"
SKIPPED_MISMATCH = "skipped_does_not_match_record"
SKIPPED_UNVERIFIED = "skipped_unverified"
SKIPPED_UNSAFE_NAME = "skipped_unsafe_file_name"
SKIPPED_CONFLICT = "skipped_different_photo_already_in_volume"
FAILED = "failed"

# Outcomes after which the old copy of a file is no longer needed.
SAFE_OUTCOMES = {COPIED, ALREADY_PRESENT}
# Outcomes where the file was deliberately left behind because it belongs to no student.
NOT_A_STUDENT_PHOTO = {SKIPPED_NO_RECORD, SKIPPED_UNSAFE_NAME}

EmbeddingExtractor = Callable[[bytes], Awaitable[Optional[list[float]]]]


@dataclass
class FileResult:
    name: str
    outcome: str
    verified_by: str = ""
    detail: str = ""


@dataclass
class MigrationReport:
    source_files: list[FileResult] = field(default_factory=list)
    restored: list[FileResult] = field(default_factory=list)
    dry_run: bool = False

    def count(self, outcome: str) -> int:
        return sum(1 for r in self.source_files if r.outcome == outcome)

    @property
    def needs_attention(self) -> list[FileResult]:
        handled = SAFE_OUTCOMES | NOT_A_STUDENT_PHOTO
        return [r for r in self.source_files if r.outcome not in handled]

    @property
    def safe_to_delete_source(self) -> bool:
        """True when no student's photo exists only in the old folder."""
        return not self.dry_run and not self.needs_attention


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_record_photo(value: Any) -> Optional[bytes]:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if "," in raw[:100]:
        raw = raw.split(",", 1)[1]
    try:
        return base64.b64decode(raw)
    except ValueError:
        return None


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


async def _find_student(db, stem: str) -> Optional[dict]:
    return await db["student_profiles"].find_one(
        {"$or": [{"student_id": stem}, {"identity": stem}]}
    )


async def _enrolled_template(db, student: dict, stem: str) -> Optional[list[float]]:
    keys = [k for k in {stem, student.get("identity"), student.get("student_id")} if k]
    profile = await db["biometric_profiles"].find_one({"identity": {"$in": keys}})
    template = (profile or {}).get("mean_embedding")
    return template if isinstance(template, list) and template else None


async def verify_against_record(
    db, stem: str, student: dict, photo: bytes, extract_embedding: Optional[EmbeddingExtractor]
) -> tuple[str, str]:
    """Return (verdict, how). verdict is 'match', 'mismatch' or 'unverified'."""
    record_photo = decode_record_photo(student.get("photo_base64"))
    if record_photo is not None:
        if sha256(record_photo) == sha256(photo):
            return "match", "identical to the photo in the student record"
        # A different file is not automatically wrong (the record may hold a
        # re-encoded copy), so fall through to the face check.

    template = await _enrolled_template(db, student, stem)
    if template is None or extract_embedding is None:
        return (
            "unverified",
            "no enrolled face template" if template is None else "vision service not available",
        )
    embedding = await extract_embedding(photo)
    if embedding is None:
        return "unverified", "no face could be extracted from the photo"
    similarity = cosine(embedding, template)
    if similarity >= FACE_MATCH_THRESHOLD:
        return "match", f"face matches the enrolled template (similarity {similarity:.2f})"
    return "mismatch", f"face does not match the enrolled template (similarity {similarity:.2f})"


def _source_photos(source: Path) -> list[Path]:
    return sorted(
        p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    )


async def migrate(
    db,
    source: Path,
    *,
    dry_run: bool = False,
    include_unverified: bool = False,
    restore_from_records: bool = True,
    extract_embedding: Optional[EmbeddingExtractor] = None,
) -> MigrationReport:
    report = MigrationReport(dry_run=dry_run)
    destination_dir = get_student_photos_dir()
    copied_names: set[str] = set()

    for path in _source_photos(source):
        stem = path.stem
        try:
            destination = student_photo_path(stem)
        except ValueError:
            report.source_files.append(FileResult(path.name, SKIPPED_UNSAFE_NAME))
            continue

        student = await _find_student(db, stem)
        if student is None:
            report.source_files.append(FileResult(path.name, SKIPPED_NO_RECORD))
            continue

        try:
            photo = path.read_bytes()
        except OSError as exc:
            report.source_files.append(FileResult(path.name, FAILED, detail=type(exc).__name__))
            continue

        if destination.exists():
            same = sha256(destination.read_bytes()) == sha256(photo)
            report.source_files.append(
                FileResult(path.name, ALREADY_PRESENT if same else SKIPPED_CONFLICT)
            )
            continue

        verdict, how = await verify_against_record(db, stem, student, photo, extract_embedding)
        if verdict == "mismatch":
            report.source_files.append(FileResult(path.name, SKIPPED_MISMATCH, how))
            continue
        if verdict == "unverified" and not include_unverified:
            report.source_files.append(FileResult(path.name, SKIPPED_UNVERIFIED, how))
            continue

        if not dry_run:
            try:
                destination_dir.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(photo)
                if sha256(destination.read_bytes()) != sha256(photo):
                    destination.unlink(missing_ok=True)
                    raise OSError("copy does not match the original")
            except OSError as exc:
                report.source_files.append(FileResult(path.name, FAILED, how, str(exc)))
                continue
        copied_names.add(destination.name)
        report.source_files.append(FileResult(path.name, COPIED, how))

    if restore_from_records:
        cursor = db["student_profiles"].find(
            {"photo_base64": {"$exists": True, "$nin": [None, ""]}}
        )
        async for student in cursor:
            student_id = str(student.get("student_id") or student.get("identity") or "")
            photo = decode_record_photo(student.get("photo_base64"))
            try:
                destination = student_photo_path(student_id)
            except ValueError:
                continue
            # Skip photos already in the volume and ones this run copies from the old folder.
            if photo is None or destination.exists() or destination.name in copied_names:
                continue
            if not dry_run:
                destination_dir.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(photo)
            report.restored.append(FileResult(destination.name, RESTORED_FROM_RECORD))

    return report


def format_report(report: MigrationReport, source: Path) -> str:
    lines = []
    title = "DRY RUN - nothing was written" if report.dry_run else "Migration finished"
    lines.append(f"{title}. Source: {source}  ->  {get_student_photos_dir()}")
    lines.append("")
    for result in report.source_files:
        note = f"  ({result.verified_by})" if result.verified_by else ""
        extra = f"  [{result.detail}]" if result.detail else ""
        lines.append(f"  {result.name:<32} {result.outcome}{note}{extra}")
    for result in report.restored:
        lines.append(f"  {result.name:<32} {result.outcome}")
    lines.append("")
    lines.append(f"Photos found in the old folder        : {len(report.source_files)}")
    for label, outcome in (
        ("  copied to the volume", COPIED),
        ("  already in the volume (identical)", ALREADY_PRESENT),
        ("  not copied: no student record", SKIPPED_NO_RECORD),
        ("  not copied: does not match record", SKIPPED_MISMATCH),
        ("  not copied: could not be verified", SKIPPED_UNVERIFIED),
        ("  not copied: different photo in volume", SKIPPED_CONFLICT),
        ("  not copied: unsafe file name", SKIPPED_UNSAFE_NAME),
        ("  failed", FAILED),
    ):
        lines.append(f"{label:<38}: {report.count(outcome)}")
    lines.append(f"Photos written from student records   : {len(report.restored)}")
    lines.append("")
    if report.dry_run:
        lines.append("Run again without --dry-run to copy the photos.")
    elif report.safe_to_delete_source:
        lines.append(
            "SAFE TO DELETE the old folder: every photo in it is either in the volume, "
            "verified against its student record, or belongs to no student."
        )
    else:
        lines.append(
            f"NOT safe to delete the old folder yet: {len(report.needs_attention)} photo(s) need attention:"
        )
        for result in report.needs_attention:
            lines.append(f"  {result.name}: {result.outcome}")
    return "\n".join(lines)


async def _vision_extractor() -> Optional[EmbeddingExtractor]:
    """An extractor backed by the vision service, or None if it cannot be reached."""
    import httpx

    from app.core.config import settings
    from app.services.vision_client import vision_service_headers

    base = settings.VISION_SERVICE_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            if (await client.get(f"{base}/health")).status_code != 200:
                return None
    except httpx.HTTPError:
        return None

    async def extract(photo: bytes) -> Optional[list[float]]:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{base}/extract-embedding",
                    content=photo,
                    headers={"Content-Type": "image/jpeg", **vision_service_headers()},
                )
            data = response.json() if response.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            return None
        embedding = data.get("embedding") if data.get("status") == "ok" else None
        return embedding if isinstance(embedding, list) and embedding else None

    return extract


async def _main_async(args: argparse.Namespace) -> int:
    from app.database.mongodb import get_database

    source = Path(args.source)
    if not source.is_dir():
        print(f"ERROR: source folder not found: {source}", file=sys.stderr)
        return 2

    extractor = await _vision_extractor()
    if extractor is None:
        print(
            "NOTE: the vision service is not reachable; photos can only be checked byte-for-byte."
        )
    report = await migrate(
        get_database(),
        source,
        dry_run=args.dry_run,
        include_unverified=args.include_unverified,
        restore_from_records=not args.no_restore_from_records,
        extract_embedding=extractor,
    )
    print(format_report(report, source))
    if report.dry_run:
        return 0
    return 0 if report.safe_to_delete_source else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy old student photos into the uploads volume")
    parser.add_argument(
        "--source", required=True, help="The old uploads folder (mounted read-only)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would happen; write nothing"
    )
    parser.add_argument(
        "--include-unverified",
        action="store_true",
        help="Also copy photos of known students that could not be checked against the record",
    )
    parser.add_argument(
        "--no-restore-from-records",
        action="store_true",
        help="Do not write out photos that exist only inside student records",
    )
    return asyncio.run(_main_async(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
