"""Where uploaded student photos are stored.

Uploads are personal data and must never sit inside the source tree, where a
bind mount (``./backend:/app``) would put them next to the code on the host
and one careless ``git add`` or image build away from leaking.

In containers the directory is a named Docker volume mounted at
``/data/uploads`` (``UPLOADS_DIR`` is set by the image). Outside a container
the default is a folder in the user's home directory. A location inside the
source tree is refused at startup.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
STUDENT_PHOTOS_SUBDIR = "student_profiles"
# A student ID is used as a file name. Anything that could leave the directory
# (separators, "..", drive letters) is never accepted.
_SAFE_PHOTO_STEM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")


class UnsafeUploadsLocation(RuntimeError):
    """The configured uploads directory is inside the source tree."""


def source_tree_root() -> Path:
    """The directory that must not contain uploads.

    The repository root when the backend is run from a checkout, otherwise
    the backend directory itself (``/app`` in the container).
    """
    parent = BACKEND_DIR.parent
    if (parent / ".git").exists() or (parent / "docker-compose.yml").exists():
        return parent
    return BACKEND_DIR


def _is_inside(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def default_uploads_root() -> Path:
    return Path.home() / ".anti_proxy_attendance" / "uploads"


def resolve_uploads_root(configured: Optional[str] = None) -> Path:
    """Return the uploads root, refusing any location inside the source tree."""
    raw = configured if configured is not None else os.getenv("UPLOADS_DIR", "")
    root = Path(raw.strip()).expanduser() if raw and raw.strip() else default_uploads_root()
    if not root.is_absolute():
        raise UnsafeUploadsLocation(
            f"UPLOADS_DIR must be an absolute path outside the source tree (found '{raw}')."
        )
    root = root.resolve()
    forbidden = source_tree_root()
    if _is_inside(root, forbidden):
        raise UnsafeUploadsLocation(
            f"UPLOADS_DIR ({root}) is inside the source tree ({forbidden.resolve()}). "
            "Uploaded photos must be stored outside it: use the named Docker volume "
            "mounted at /data/uploads, or another directory outside the repository."
        )
    return root


def get_student_photos_dir() -> Path:
    """Directory holding student profile photos. Resolved on every call."""
    return resolve_uploads_root() / STUDENT_PHOTOS_SUBDIR


def student_photo_path(student_id: str) -> Path:
    """Path of one student's photo, guaranteed to be directly inside the photos directory."""
    if (
        not isinstance(student_id, str)
        or not _SAFE_PHOTO_STEM.fullmatch(student_id)
        or ".." in student_id
    ):
        raise ValueError("student ID is not usable as a file name")
    directory = get_student_photos_dir()
    path = directory / f"{student_id}.jpg"
    if path.resolve().parent != directory.resolve():
        raise ValueError("student ID is not usable as a file name")
    return path


PENDING_PHOTOS_SUBDIR = "pending_review"


def pending_photo_path(identity: str) -> Path:
    """Path of a replacement photo that is waiting for an administrator's review."""
    if (
        not isinstance(identity, str)
        or not _SAFE_PHOTO_STEM.fullmatch(identity)
        or ".." in identity
    ):
        raise ValueError("student ID is not usable as a file name")
    directory = resolve_uploads_root() / PENDING_PHOTOS_SUBDIR
    path = directory / f"{identity}.jpg"
    if path.resolve().parent != directory.resolve():
        raise ValueError("student ID is not usable as a file name")
    return path
