"""Uploaded student photos must never be stored inside the source tree.

They are personal data. In containers they live on a named Docker volume
mounted at /data/uploads; outside a container they default to a folder in the
user's home directory. These tests fail if an upload lands in the repository,
if the service would start with such a location, or if a student ID could be
used to write outside the uploads directory.
"""

from pathlib import Path
import secrets

from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.core import uploads
from app.core.config import settings
from app.core.uploads import (
    UnsafeUploadsLocation,
    get_student_photos_dir,
    resolve_uploads_root,
    source_tree_root,
    student_photo_path,
)
from app.database import mongodb
from app.database.mongodb import init_indexes
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
# The repository root in a checkout; the backend directory (/app) inside the container.
SOURCE_TREE = source_tree_root()
PLACEHOLDER_PHOTO_B64 = "cGxhY2Vob2xkZXIgcGhvdG8gYnl0ZXM="  # not an image of anyone


def _is_inside(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def _files_in_source_tree() -> set[Path]:
    """Every file under the backend directory that could be an upload."""
    skip = {".venv", "__pycache__", ".pytest_cache", "node_modules", ".git"}
    found = set()
    for path in BACKEND_DIR.rglob("*"):
        if path.is_file() and not (skip & set(path.relative_to(BACKEND_DIR).parts)):
            if path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                found.add(path)
    return found


@pytest.fixture
async def fresh_db():
    mongodb._client = AsyncMongoMockClient()
    await init_indexes(mongodb.get_database())
    yield
    mongodb._client = AsyncMongoMockClient()


async def _admin_headers() -> dict[str, str]:
    """The photo route requires a token; these tests are about where files are stored."""
    await create_user(
        user_id="uploads_admin",
        email="uploads_admin@uploads.test",
        password_hash=hash_password("Password123!"),
        role="ADMIN",
    )
    return {"Authorization": f"Bearer {create_access_token(user_id='uploads_admin', role='ADMIN')}"}


def _registration(student_id: str) -> dict:
    return {
        "name": "Upload Location Student",
        "email": f"{abs(hash(student_id))}@uploads.test",
        "password": "StudentSecurePass123!",
        "student_id": student_id,
        "roll_number": "20260001",
        "branch": "Data Science",
        "section": "B",
        "photo_base64": PLACEHOLDER_PHOTO_B64,
    }


# ------------------------------------------------------------------------------
# Where uploads go
# ------------------------------------------------------------------------------


def test_default_uploads_location_is_outside_the_repository(monkeypatch):
    monkeypatch.delenv("UPLOADS_DIR", raising=False)

    root = resolve_uploads_root()

    assert root.is_absolute()
    assert not _is_inside(root, SOURCE_TREE), f"default uploads location {root} is inside the source tree"
    assert not _is_inside(root, BACKEND_DIR)


def test_source_tree_root_covers_the_whole_checkout():
    assert _is_inside(BACKEND_DIR, source_tree_root())


@pytest.mark.parametrize(
    "inside",
    [
        BACKEND_DIR / "uploads",
        BACKEND_DIR / "uploads" / "student_profiles",
        BACKEND_DIR / "app" / "static",
        BACKEND_DIR,
        BACKEND_DIR / "tests" / ".." / "uploads",
    ],
)
def test_a_location_inside_the_source_tree_is_refused(inside):
    with pytest.raises(UnsafeUploadsLocation):
        resolve_uploads_root(str(inside))


@pytest.mark.parametrize("relative", ["uploads", "./uploads", "backend/uploads", "../uploads"])
def test_a_relative_location_is_refused(relative):
    with pytest.raises(UnsafeUploadsLocation):
        resolve_uploads_root(relative)


def test_service_refuses_to_start_with_uploads_inside_the_source_tree(monkeypatch):
    # Everything else the startup checks need is valid; only the uploads location is wrong.
    monkeypatch.setattr(settings, "RECOGNITION_SIGNING_KEY", secrets.token_hex(32))
    monkeypatch.setenv("UPLOADS_DIR", str(BACKEND_DIR / "uploads"))

    with pytest.raises(UnsafeUploadsLocation):
        with TestClient(app):
            pass


def test_service_starts_with_uploads_outside_the_source_tree(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "RECOGNITION_SIGNING_KEY", secrets.token_hex(32))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads-volume"))
    mongodb._client = AsyncMongoMockClient()

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_the_test_suite_itself_writes_uploads_outside_the_repository():
    """The autouse fixture in conftest.py points uploads at a temporary directory."""
    assert not _is_inside(get_student_photos_dir(), SOURCE_TREE)
    assert not _is_inside(get_student_photos_dir(), BACKEND_DIR)


# ------------------------------------------------------------------------------
# An upload does not land in the repository
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_uploaded_photo_is_written_outside_the_repository(
    fresh_db, stub_vision_embedding, tmp_path, monkeypatch
):
    target = tmp_path / "uploads-volume"
    monkeypatch.setenv("UPLOADS_DIR", str(target))
    before = _files_in_source_tree()

    client = TestClient(app)
    resp = client.post("/api/v1/students/register", json=_registration("UPLOC001"))
    assert resp.status_code == 201, resp.text
    photo = client.get("/api/v1/students/UPLOC001/photo", headers=await _admin_headers())

    stored = target / "student_profiles" / "UPLOC001.jpg"
    assert stored.is_file(), "the photo was not written to the configured uploads directory"
    assert photo.status_code == 200
    assert photo.content == stored.read_bytes()

    new_files = _files_in_source_tree() - before
    assert new_files == set(), f"an upload landed inside the repository: {sorted(new_files)}"
    assert not (BACKEND_DIR / "uploads" / "student_profiles" / "UPLOC001.jpg").exists()


@pytest.mark.anyio
async def test_reading_a_photo_kept_in_the_student_record_writes_no_file(fresh_db, tmp_path, monkeypatch):
    """A GET never writes: copying photos into the uploads directory is the migration command's job."""
    target = tmp_path / "uploads-volume"
    monkeypatch.setenv("UPLOADS_DIR", str(target))
    await mongodb.get_database()["student_profiles"].insert_one(
        {"student_id": "UPLOC002", "identity": "UPLOC002", "photo_base64": PLACEHOLDER_PHOTO_B64}
    )
    before = _files_in_source_tree()

    photo = TestClient(app).get("/api/v1/students/UPLOC002/photo", headers=await _admin_headers())

    assert photo.status_code == 200
    assert photo.content == b"placeholder photo bytes"
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []
    assert _files_in_source_tree() - before == set()


def test_uploads_are_not_served_as_static_files(tmp_path, monkeypatch):
    target = tmp_path / "uploads-volume"
    (target / "student_profiles").mkdir(parents=True)
    (target / "student_profiles" / "UPLOC003.jpg").write_bytes(b"photo bytes")
    monkeypatch.setenv("UPLOADS_DIR", str(target))

    client = TestClient(app)
    for path in ("/uploads/student_profiles/UPLOC003.jpg", "/uploads/UPLOC003.jpg", "/uploads/"):
        assert client.get(path).status_code == 404, path


# ------------------------------------------------------------------------------
# A student ID cannot be used to write somewhere else
# ------------------------------------------------------------------------------

TRAVERSAL_IDS = [
    "../evil",
    "../../app/main",
    "..",
    "a/b",
    "a\\b",
    "C:\\Windows\\evil",
    "/etc/passwd",
    ".hidden",
    "name with spaces",
    "",
    "x" * 200,
]


@pytest.mark.parametrize("student_id", TRAVERSAL_IDS)
def test_unsafe_student_ids_have_no_photo_path(student_id):
    with pytest.raises(ValueError):
        student_photo_path(student_id)


@pytest.mark.parametrize("student_id", ["DS20260125", "DS2026_123", "cs-a.17", "SMOKEA", "42"])
def test_ordinary_student_ids_map_to_a_file_directly_inside_the_photos_directory(student_id):
    path = student_photo_path(student_id)
    assert path.parent.resolve() == get_student_photos_dir().resolve()
    assert path.name == f"{student_id}.jpg"


@pytest.mark.anyio
@pytest.mark.parametrize("student_id", ["../../evil", "..\\..\\evil", "a/b", "../uploads-escape"])
async def test_registration_with_a_path_like_student_id_is_rejected_and_writes_nothing(
    fresh_db, stub_vision_embedding, tmp_path, monkeypatch, student_id
):
    target = tmp_path / "uploads-volume"
    monkeypatch.setenv("UPLOADS_DIR", str(target))
    before = _files_in_source_tree()

    resp = TestClient(app).post("/api/v1/students/register", json=_registration(student_id))

    assert resp.status_code == 422
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []
    assert _files_in_source_tree() - before == set()


@pytest.mark.anyio
async def test_enrollment_refuses_an_unsafe_identity_even_if_validation_is_bypassed(
    stub_vision_embedding, tmp_path, monkeypatch
):
    """Defence in depth: the service itself will not build a path from such an ID."""
    from app.services.student_biometric_service import extract_and_register_student_photo

    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads-volume"))

    ok, message = await extract_and_register_student_photo(
        identity="../../escape", photo_base64=PLACEHOLDER_PHOTO_B64
    )

    assert ok is False
    assert "Student ID" in message
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


@pytest.mark.anyio
async def test_photo_route_does_not_resolve_path_like_ids(fresh_db, tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads-volume"))
    (tmp_path / "secret.jpg").write_bytes(b"not a student photo")
    headers = await _admin_headers()  # an admin passes the access check and reaches the path handling

    client = TestClient(app)
    for student_id in ("..%2Fsecret", "..secret", ".secret"):
        response = client.get(f"/api/v1/students/{student_id}/photo", headers=headers)
        assert response.status_code == 404, student_id


# ------------------------------------------------------------------------------
# Deployment files (skipped where the repository is not available, e.g. in the image)
# ------------------------------------------------------------------------------


def test_compose_stores_uploads_on_a_named_volume_outside_the_source_mount():
    compose = REPO_ROOT / "docker-compose.yml"
    if not compose.is_file():
        pytest.skip("docker-compose.yml is not available here")
    text = compose.read_text(encoding="utf-8")

    assert "- uploads_data:/data/uploads" in text
    assert "UPLOADS_DIR: /data/uploads" in text
    assert "uploads_data:\n    name: anti_proxy_uploads" in text
    # No host directory is mounted as the uploads directory, and nothing maps
    # uploads back under the source mount.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") and ":/data/uploads" in stripped:
            assert stripped == "- uploads_data:/data/uploads", stripped
        assert "/app/uploads" not in stripped, stripped


def test_backend_image_sets_the_uploads_directory_outside_the_app_directory():
    dockerfile = BACKEND_DIR / "Dockerfile"
    if not dockerfile.is_file():
        pytest.skip("the Dockerfile is not available here")
    text = dockerfile.read_text(encoding="utf-8")

    assert "ENV UPLOADS_DIR=/data/uploads" in text
    assert "/app/uploads" not in text


def test_nothing_in_the_application_refers_to_an_uploads_folder_in_the_source_tree():
    offenders = []
    for path in (BACKEND_DIR / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "/app/uploads" in text or 'BACKEND_DIR / "uploads"' in text or 'Path("uploads")' in text:
            offenders.append(path.name)
    assert offenders == []
    assert not hasattr(uploads, "UPLOADS_DIR")
