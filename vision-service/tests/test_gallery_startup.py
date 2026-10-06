"""The vision service must start with an empty gallery.

Biometric embeddings are loaded from the backend at runtime. Nothing may be
picked up implicitly from a gallery file that happens to sit in the image or
the working directory.
"""

from pathlib import Path
import sys

import numpy as np
import pytest

SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from camera import PhoneVideoSource  # noqa: E402
from camera import webrtc_receiver  # noqa: E402
from camera.webrtc_receiver import WebRTCSignalingServer  # noqa: E402


def _write_npz(path: Path, label: str) -> None:
    vec = np.zeros((1, 512), dtype=np.float32)
    vec[0, 0] = 1.0
    np.savez(path, labels=np.array([label]), embeddings=vec)


@pytest.fixture
def isolated_server_factory(tmp_path, monkeypatch):
    """Build signaling servers whose enrolled-gallery cache lives in an empty temp dir."""
    monkeypatch.setattr(
        WebRTCSignalingServer,
        "_get_enrolled_gallery_path",
        lambda self: tmp_path / "enrolled_gallery.json",
    )

    def _make() -> WebRTCSignalingServer:
        return WebRTCSignalingServer(video_source=PhoneVideoSource(source_id="test-gallery-startup"))

    return _make


def test_gallery_is_empty_at_startup(isolated_server_factory, tmp_path, monkeypatch):
    monkeypatch.delenv("GALLERY_NPZ_PATH", raising=False)

    # A gallery file lying around in the working directory must be ignored
    _write_npz(tmp_path / "gallery.npz", "stray_identity")
    monkeypatch.chdir(tmp_path)

    server = isolated_server_factory()

    assert server.gallery == {}
    assert server._get_gallery() == {}


def test_no_implicit_gallery_path_in_receiver_source():
    """The receiver must not reference a baked-in gallery file path."""
    source = Path(webrtc_receiver.__file__).read_text(encoding="utf-8")
    assert "/app/gallery.npz" not in source


def test_explicit_gallery_path_is_honoured(isolated_server_factory, tmp_path, monkeypatch):
    npz_path = tmp_path / "dev_gallery.npz"
    _write_npz(npz_path, "dev_identity")
    monkeypatch.setenv("GALLERY_NPZ_PATH", str(npz_path))

    server = isolated_server_factory()

    assert list(server.gallery.keys()) == ["dev_identity"]
