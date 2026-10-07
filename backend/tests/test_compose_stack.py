"""The Compose stack must run the vision service and frontend from their images.

Bind-mounting part of the working tree over an image mixes two versions of the
code: an image built before the vision entry point changed crash-looped against
the mounted ``camera`` package, and the frontend served an empty ``dist``.
"""

from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"
START_SCRIPT = PROJECT_ROOT / "scripts" / "start_dev.ps1"

pytestmark = pytest.mark.skipif(
    not COMPOSE_FILE.exists(), reason="repository root is not available"
)


def _bind_mounts(service: dict) -> list[str]:
    """Volume entries whose source is a host path rather than a named volume."""
    mounts = []
    for volume in service.get("volumes", []):
        source = volume.get("source", "") if isinstance(volume, dict) else volume.split(":")[0]
        if source.startswith((".", "/", "~")):
            mounts.append(source)
    return mounts


@pytest.fixture(scope="module")
def services() -> dict:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))["services"]


@pytest.mark.parametrize("name", ["vision-service", "frontend"])
def test_service_runs_only_what_its_image_contains(services, name):
    assert "build" in services[name]
    assert _bind_mounts(services[name]) == []


def test_vision_service_keeps_its_named_volumes(services):
    targets = {volume.split(":")[1] for volume in services["vision-service"]["volumes"]}
    assert targets == {"/home/visionuser/.insightface", "/app/data"}


def test_start_script_rebuilds_the_images():
    assert "docker compose up -d --build" in START_SCRIPT.read_text(encoding="utf-8")
