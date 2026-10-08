"""The one-time uploads migration command.

It copies photos from the old in-repo folder into the uploads directory,
checks each against its student record, reports counts, and never deletes
or changes the source. No real photo is used: files hold placeholder bytes
and the vision service is replaced by a stub extractor.
"""

import base64
import hashlib

from mongomock_motor import AsyncMongoMockClient
import pytest

from app.core.uploads import get_student_photos_dir
from app.database import mongodb
from app.tools import migrate_uploads
from app.tools.migrate_uploads import (
    ALREADY_PRESENT,
    COPIED,
    FAILED,
    RESTORED_FROM_RECORD,
    SKIPPED_CONFLICT,
    SKIPPED_MISMATCH,
    SKIPPED_NO_RECORD,
    SKIPPED_UNSAFE_NAME,
    SKIPPED_UNVERIFIED,
    format_report,
    migrate,
)

TEMPLATE = [1.0] + [0.0] * 511
SAME_FACE = [0.9] + [0.1] * 4 + [0.0] * 507
OTHER_FACE = [0.0, 1.0] + [0.0] * 510


def _photo(tag: str) -> bytes:
    return f"placeholder photo bytes for {tag}".encode()


@pytest.fixture
async def db():
    mongodb._client = AsyncMongoMockClient()
    database = mongodb.get_database()
    yield database
    mongodb._client = AsyncMongoMockClient()


@pytest.fixture
def source(tmp_path):
    folder = tmp_path / "legacy_uploads" / "student_profiles"
    folder.mkdir(parents=True)
    return folder


async def _student(db, student_id: str, *, photo: bytes | None = None, template: list | None = None):
    record = {"user_id": f"user_{student_id}", "student_id": student_id, "identity": student_id}
    if photo is not None:
        record["photo_base64"] = base64.b64encode(photo).decode()
    await db["student_profiles"].insert_one(record)
    if template is not None:
        await db["biometric_profiles"].insert_one({"identity": student_id, "mean_embedding": template})


def _extractor(mapping: dict[bytes, list | None]):
    calls = []

    async def extract(photo: bytes):
        calls.append(photo)
        return mapping.get(photo)

    extract.calls = calls
    return extract


def _outcomes(report) -> dict[str, str]:
    return {r.name: r.outcome for r in report.source_files}


def _snapshot(folder) -> dict[str, str]:
    return {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


# ------------------------------------------------------------------------------
# Verification against the student record
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_photo_identical_to_the_one_in_the_record_is_copied(db, source):
    await _student(db, "MIG001", photo=_photo("MIG001"))
    (source / "MIG001.jpg").write_bytes(_photo("MIG001"))

    report = await migrate(db, source.parent)

    assert _outcomes(report) == {"MIG001.jpg": COPIED}
    assert "identical" in report.source_files[0].verified_by
    assert (get_student_photos_dir() / "MIG001.jpg").read_bytes() == _photo("MIG001")
    assert report.safe_to_delete_source is True


@pytest.mark.anyio
async def test_photo_matching_the_enrolled_face_template_is_copied(db, source):
    await _student(db, "MIG002", template=TEMPLATE)
    (source / "MIG002.jpg").write_bytes(_photo("MIG002"))
    extractor = _extractor({_photo("MIG002"): SAME_FACE})

    report = await migrate(db, source.parent, extract_embedding=extractor)

    assert _outcomes(report) == {"MIG002.jpg": COPIED}
    assert "face matches" in report.source_files[0].verified_by
    assert extractor.calls == [_photo("MIG002")]
    assert (get_student_photos_dir() / "MIG002.jpg").is_file()


@pytest.mark.anyio
async def test_photo_of_a_different_face_is_not_copied(db, source):
    """A file named after one student that shows someone else must not become that student's photo."""
    await _student(db, "MIG003", template=TEMPLATE)
    (source / "MIG003.jpg").write_bytes(_photo("someone else"))

    report = await migrate(
        db, source.parent, extract_embedding=_extractor({_photo("someone else"): OTHER_FACE})
    )

    assert _outcomes(report) == {"MIG003.jpg": SKIPPED_MISMATCH}
    assert not (get_student_photos_dir() / "MIG003.jpg").exists()
    assert report.safe_to_delete_source is False


@pytest.mark.anyio
async def test_mismatch_is_not_overridden_by_include_unverified(db, source):
    await _student(db, "MIG003", template=TEMPLATE)
    (source / "MIG003.jpg").write_bytes(_photo("someone else"))

    report = await migrate(
        db,
        source.parent,
        include_unverified=True,
        extract_embedding=_extractor({_photo("someone else"): OTHER_FACE}),
    )

    assert _outcomes(report) == {"MIG003.jpg": SKIPPED_MISMATCH}
    assert not (get_student_photos_dir() / "MIG003.jpg").exists()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "template,extractor_result,use_extractor",
    [
        (None, SAME_FACE, True),  # student has no enrolled template
        (TEMPLATE, None, True),  # no face could be extracted from the file
        (TEMPLATE, SAME_FACE, False),  # the vision service is not running
    ],
    ids=["no_template", "no_face_found", "no_vision_service"],
)
async def test_photo_that_cannot_be_checked_is_left_behind_unless_asked(
    db, source, template, extractor_result, use_extractor
):
    await _student(db, "MIG004", template=template)
    (source / "MIG004.jpg").write_bytes(_photo("MIG004"))
    extractor = _extractor({_photo("MIG004"): extractor_result}) if use_extractor else None

    report = await migrate(db, source.parent, extract_embedding=extractor)
    assert _outcomes(report) == {"MIG004.jpg": SKIPPED_UNVERIFIED}
    assert not (get_student_photos_dir() / "MIG004.jpg").exists()
    assert report.safe_to_delete_source is False

    forced = await migrate(db, source.parent, extract_embedding=extractor, include_unverified=True)
    assert _outcomes(forced) == {"MIG004.jpg": COPIED}
    assert (get_student_photos_dir() / "MIG004.jpg").read_bytes() == _photo("MIG004")


@pytest.mark.anyio
async def test_a_re_encoded_record_photo_falls_back_to_the_face_check(db, source):
    await _student(db, "MIG005", photo=_photo("a re-encoded copy"), template=TEMPLATE)
    (source / "MIG005.jpg").write_bytes(_photo("MIG005"))

    report = await migrate(db, source.parent, extract_embedding=_extractor({_photo("MIG005"): SAME_FACE}))

    assert _outcomes(report) == {"MIG005.jpg": COPIED}


# ------------------------------------------------------------------------------
# Files that are not copied
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_photo_with_no_student_record_is_not_copied(db, source):
    (source / "GHOST999.jpg").write_bytes(_photo("ghost"))

    report = await migrate(db, source.parent, include_unverified=True)

    assert _outcomes(report) == {"GHOST999.jpg": SKIPPED_NO_RECORD}
    assert not get_student_photos_dir().exists() or list(get_student_photos_dir().iterdir()) == []
    # It belongs to nobody, so it does not block deleting the old folder.
    assert report.safe_to_delete_source is True


@pytest.mark.anyio
async def test_unsafe_file_names_are_skipped_and_nothing_escapes_the_uploads_directory(db, source, tmp_path):
    for name in ("..evil.jpg", "name with spaces.jpg", ".hidden.jpg"):
        (source / name).write_bytes(_photo(name))
    before = {p for p in tmp_path.rglob("*") if p.is_file()}

    report = await migrate(db, source.parent, include_unverified=True)

    assert set(_outcomes(report).values()) == {SKIPPED_UNSAFE_NAME}
    assert {p for p in tmp_path.rglob("*") if p.is_file()} == before


@pytest.mark.anyio
async def test_files_that_are_not_photos_are_ignored(db, source):
    (source / ".gitkeep").write_bytes(b"")
    (source / "notes.txt").write_bytes(b"not a photo")

    report = await migrate(db, source.parent)

    assert report.source_files == []


@pytest.mark.anyio
async def test_identical_photo_already_in_the_volume_is_reported_not_rewritten(db, source):
    await _student(db, "MIG006", photo=_photo("MIG006"))
    (source / "MIG006.jpg").write_bytes(_photo("MIG006"))
    first = await migrate(db, source.parent)
    assert _outcomes(first) == {"MIG006.jpg": COPIED}

    again = await migrate(db, source.parent)

    assert _outcomes(again) == {"MIG006.jpg": ALREADY_PRESENT}
    assert again.safe_to_delete_source is True


@pytest.mark.anyio
async def test_a_different_photo_already_in_the_volume_is_never_overwritten(db, source):
    await _student(db, "MIG007", photo=_photo("old"))
    (source / "MIG007.jpg").write_bytes(_photo("old"))
    destination = get_student_photos_dir() / "MIG007.jpg"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(_photo("newer photo uploaded since"))

    report = await migrate(db, source.parent, include_unverified=True)

    assert _outcomes(report) == {"MIG007.jpg": SKIPPED_CONFLICT}
    assert destination.read_bytes() == _photo("newer photo uploaded since")
    assert report.safe_to_delete_source is False


# ------------------------------------------------------------------------------
# Never destructive
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_the_source_folder_is_never_changed(db, source):
    await _student(db, "MIG001", photo=_photo("MIG001"))
    await _student(db, "MIG003", template=TEMPLATE)
    (source / "MIG001.jpg").write_bytes(_photo("MIG001"))
    (source / "MIG003.jpg").write_bytes(_photo("someone else"))
    (source / "GHOST999.jpg").write_bytes(_photo("ghost"))
    (source.parent / "top_level.jpg").write_bytes(_photo("top"))
    before = _snapshot(source.parent)

    await migrate(db, source.parent, extract_embedding=_extractor({_photo("someone else"): OTHER_FACE}))
    await migrate(db, source.parent, include_unverified=True)

    assert _snapshot(source.parent) == before


@pytest.mark.anyio
async def test_dry_run_writes_nothing_and_never_says_it_is_safe_to_delete(db, source):
    await _student(db, "MIG001", photo=_photo("MIG001"))
    await _student(db, "MIG008", photo=_photo("only in the record"))
    (source / "MIG001.jpg").write_bytes(_photo("MIG001"))

    report = await migrate(db, source.parent, dry_run=True)

    assert _outcomes(report) == {"MIG001.jpg": COPIED}
    assert [r.outcome for r in report.restored] == [RESTORED_FROM_RECORD]
    assert not get_student_photos_dir().exists() or list(get_student_photos_dir().iterdir()) == []
    assert report.safe_to_delete_source is False
    text = format_report(report, source.parent)
    assert "DRY RUN" in text and "SAFE TO DELETE" not in text


# ------------------------------------------------------------------------------
# Photos that exist only inside a student record
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_photos_kept_only_in_student_records_are_written_out(db, source):
    await _student(db, "MIG008", photo=_photo("only in the record"))
    await _student(db, "MIG009")  # no photo anywhere

    report = await migrate(db, source.parent)

    assert [(r.name, r.outcome) for r in report.restored] == [("MIG008.jpg", RESTORED_FROM_RECORD)]
    assert (get_student_photos_dir() / "MIG008.jpg").read_bytes() == _photo("only in the record")
    assert not (get_student_photos_dir() / "MIG009.jpg").exists()

    skipped = await migrate(db, source.parent, restore_from_records=False)
    assert skipped.restored == []


# ------------------------------------------------------------------------------
# The report
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_report_counts_and_verdict(db, source):
    await _student(db, "MIG001", photo=_photo("MIG001"))
    await _student(db, "MIG002", template=TEMPLATE)
    await _student(db, "MIG003", template=TEMPLATE)
    await _student(db, "MIG004")
    (source / "MIG001.jpg").write_bytes(_photo("MIG001"))
    (source / "MIG002.jpg").write_bytes(_photo("MIG002"))
    (source / "MIG003.jpg").write_bytes(_photo("someone else"))
    (source / "MIG004.jpg").write_bytes(_photo("MIG004"))
    (source / "GHOST999.jpg").write_bytes(_photo("ghost"))
    extractor = _extractor({_photo("MIG002"): SAME_FACE, _photo("someone else"): OTHER_FACE})

    report = await migrate(db, source.parent, extract_embedding=extractor)

    assert len(report.source_files) == 5
    assert report.count(COPIED) == 2
    assert report.count(SKIPPED_MISMATCH) == 1
    assert report.count(SKIPPED_UNVERIFIED) == 1
    assert report.count(SKIPPED_NO_RECORD) == 1
    assert report.count(FAILED) == 0
    assert sorted(r.name for r in report.needs_attention) == ["MIG003.jpg", "MIG004.jpg"]

    text = format_report(report, source.parent)
    assert "Photos found in the old folder        : 5" in text
    assert "NOT safe to delete" in text
    assert "MIG003.jpg: skipped_does_not_match_record" in text
    # Identifiers and counts only
    assert "placeholder photo bytes" not in text
    assert "0.9" not in text.replace("similarity 0.9", "")


@pytest.mark.anyio
async def test_report_says_safe_to_delete_only_when_nothing_needs_attention(db, source):
    await _student(db, "MIG001", photo=_photo("MIG001"))
    (source / "MIG001.jpg").write_bytes(_photo("MIG001"))
    (source / "GHOST999.jpg").write_bytes(_photo("ghost"))

    report = await migrate(db, source.parent)

    assert report.safe_to_delete_source is True
    assert "SAFE TO DELETE" in format_report(report, source.parent)


def test_the_command_never_deletes_or_moves_files():
    source_code = open(migrate_uploads.__file__, encoding="utf-8").read()
    for forbidden in ("shutil.rmtree", "shutil.move", "os.remove", ".rmdir(", "os.rename", ".rename("):
        assert forbidden not in source_code, forbidden
    # The only unlink removes a destination copy that failed its own integrity check.
    assert source_code.count(".unlink(") == 1
    assert "destination.unlink(missing_ok=True)" in source_code
