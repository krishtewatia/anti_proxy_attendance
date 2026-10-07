"""The vision service must start with an empty gallery.

Biometric embeddings are loaded only from the backend at runtime. Nothing may
be picked up from a gallery file in the image or the working directory, and
embeddings are never written to disk.
"""

from pathlib import Path
import sys

import numpy as np

SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from camera import vision_api  # noqa: E402
from camera.vision_api import VisionApiServer  # noqa: E402


def _write_npz(path: Path, label: str) -> None:
    vec = np.zeros((1, 512), dtype=np.float32)
    vec[0, 0] = 1.0
    np.savez(path, labels=np.array([label]), embeddings=vec)


def test_gallery_is_empty_at_startup(tmp_path, monkeypatch):
    monkeypatch.delenv("GALLERY_NPZ_PATH", raising=False)

    # A gallery file lying around in the working directory must be ignored
    _write_npz(tmp_path / "gallery.npz", "stray_identity")
    monkeypatch.chdir(tmp_path)

    server = VisionApiServer()

    assert server.gallery == {}
    assert server._get_gallery() == {}
    assert server.student_names == {}
    assert server.student_ids == {}


def test_gallery_file_is_never_loaded_even_when_a_path_is_configured(tmp_path, monkeypatch):
    """The backend is the only source of embeddings; no file path can override that."""
    npz_path = tmp_path / "dev_gallery.npz"
    _write_npz(npz_path, "dev_identity")
    monkeypatch.setenv("GALLERY_NPZ_PATH", str(npz_path))

    server = VisionApiServer()

    assert server.gallery == {}


def test_api_module_has_no_gallery_file_access():
    """The API module must not read or write gallery / embedding files at all."""
    source = Path(vision_api.__file__).read_text(encoding="utf-8")

    for forbidden in ("gallery.npz", ".npz", "np.load", "np.save", "enrolled_gallery", "write_text"):
        assert forbidden not in source, forbidden


def test_nothing_is_written_to_disk_when_the_gallery_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    server = VisionApiServer()
    server.gallery["someone"] = np.ones(512, dtype=np.float32)
    server.student_names["someone"] = "Someone"

    assert list(tmp_path.iterdir()) == []
