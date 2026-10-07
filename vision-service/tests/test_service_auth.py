"""The vision service is an internal API: service key on every route, no browser-facing routes."""

import asyncio
from pathlib import Path
import sys

from aiohttp.test_utils import TestClient, TestServer
import pytest

SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))


from camera.vision_api import VisionApiServer  # noqa: E402

SERVICE_KEY = "vision-internal-test-key"
AUTH = {"X-API-Key": SERVICE_KEY}

PROTECTED_GET = ["/gallery", "/status"]
PROTECTED_POST = ["/process-frame", "/reset", "/extract-embedding", "/enroll-student", "/reload-gallery"]
REMOVED_ROUTES = [
    ("GET", "/"),
    ("POST", "/offer"),
    ("POST", "/transit"),
    ("GET", "/preview.mjpg"),
    ("GET", "/preview.jpg"),
    ("GET", "/funnel"),
]


def _run(coro_factory, monkeypatch, *, key=SERVICE_KEY):
    """Run an async test body against an in-process test server."""
    if key is None:
        monkeypatch.delenv("VISION_SERVICE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("VISION_SERVICE_API_KEY", key)

    async def _main():
        server = VisionApiServer()
        async with TestClient(TestServer(server.app)) as client:
            return await coro_factory(client)

    return asyncio.run(_main())


def test_health_is_the_only_route_served_without_the_key(monkeypatch):
    async def body(client):
        return (await client.get("/health")).status

    assert _run(body, monkeypatch) == 200


def test_every_data_route_rejects_requests_without_the_key(monkeypatch):
    async def body(client):
        statuses = {}
        for path in PROTECTED_GET:
            statuses[path] = (await client.get(path)).status
        for path in PROTECTED_POST:
            statuses[path] = (await client.post(path, data=b"not-a-frame")).status
        return statuses

    statuses = _run(body, monkeypatch)
    assert statuses == {path: 401 for path in PROTECTED_GET + PROTECTED_POST}


def test_wrong_key_is_rejected(monkeypatch):
    async def body(client):
        return (await client.get("/gallery", headers={"X-API-Key": "not-the-key"})).status

    assert _run(body, monkeypatch) == 401


def test_browser_origin_header_no_longer_grants_access(monkeypatch):
    """A forged Origin used to bypass the token check entirely."""

    async def body(client):
        resp = await client.get("/gallery", headers={"Origin": "http://localhost:3000"})
        return resp.status, resp.headers.get("Access-Control-Allow-Origin")

    status, cors_header = _run(body, monkeypatch)
    assert status == 401
    assert cors_header is None


def test_nothing_but_health_is_served_when_no_key_is_configured(monkeypatch):
    """Fail closed: a missing key must not turn into an open service."""

    async def body(client):
        return (
            (await client.get("/health")).status,
            (await client.get("/gallery")).status,
            (await client.get("/gallery", headers={"X-API-Key": ""})).status,
            (await client.get("/gallery", headers=AUTH)).status,
        )

    assert _run(body, monkeypatch, key=None) == (200, 401, 401, 401)


def test_correct_key_reaches_the_handlers_and_no_cors_headers_are_sent(monkeypatch):
    async def body(client):
        gallery = await client.get("/gallery", headers=AUTH)
        return gallery.status, await gallery.json(), gallery.headers.get("Access-Control-Allow-Origin")

    status, payload, cors_header = _run(body, monkeypatch)
    assert status == 200
    assert payload == {"count": 0, "students": []}
    assert cors_header is None


@pytest.mark.parametrize("method,path", REMOVED_ROUTES)
def test_browser_facing_routes_do_not_exist(monkeypatch, method, path):
    async def body(client):
        without_key = await client.request(method, path)
        with_key = await client.request(method, path, headers=AUTH)
        return without_key.status, with_key.status

    without_key, with_key = _run(body, monkeypatch)
    assert without_key == 401
    assert with_key in (404, 405)
