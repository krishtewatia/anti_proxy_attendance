"""The readiness check used by the uptime monitor: names what is down, never why."""

from httpx import ASGITransport, AsyncClient
import pytest

from app import main


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("database", "vision", "code", "body"),
    [
        (True, True, 200, {"status": "ready", "database": "up", "vision": "up"}),
        (True, False, 503, {"status": "degraded", "database": "up", "vision": "down"}),
        (False, True, 503, {"status": "degraded", "database": "down", "vision": "up"}),
    ],
)
async def test_ready_reports_the_database_and_the_vision_service(monkeypatch, database, vision, code, body):
    async def db_answers() -> bool:
        return database

    async def vision_answers() -> bool:
        return vision

    monkeypatch.setattr(main, "_database_answers", db_answers)
    monkeypatch.setattr(main, "_vision_answers", vision_answers)
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.get("/api/v1/health/ready")
    assert response.status_code == code and response.json() == body


@pytest.mark.anyio
async def test_an_unreachable_vision_service_is_down_not_an_error(monkeypatch):
    monkeypatch.setattr(main.settings, "VISION_SERVICE_URL", "http://127.0.0.1:9")
    assert await main._vision_answers() is False
