"""X-Forwarded-For is believed only from the reverse proxy.

Behind the proxy every request reaches the backend from the proxy's address,
so the client address is read from the header the proxy writes. From anyone
else the header is ignored: a caller cannot pick the address that the rate
limit and the audit trail see. The backend also refuses to start on an
in-memory database when it is told a real one is required.
"""

import secrets

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest
from starlette.requests import Request

from app.core.client_ip import client_ip
from app.core.config import settings
from app.database import mongodb
from app.main import app, lifespan

PROXY = "172.28.0.10"
OUTSIDER = "203.0.113.50"
PASSWORD = "ProxyTestPass123!"


@pytest.fixture(autouse=True)
def fresh_db():
    mongodb._client = AsyncMongoMockClient()
    yield
    mongodb._client = AsyncMongoMockClient()


def _request(peer: str | None, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded is not None else []
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "client": (peer, 40000) if peer else None,
    }
    return Request(scope)


def _client_from(peer: str) -> AsyncClient:
    """An HTTP client whose requests reach the app from ``peer``."""
    return AsyncClient(transport=ASGITransport(app=app, client=(peer, 40000)), base_url="http://test")


async def _register(client: AsyncClient, n: int, forwarded: str | None) -> int:
    headers = {"X-Forwarded-For": forwarded} if forwarded else {}
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": f"proxy{n}@proxy.test", "password": PASSWORD, "role": "STUDENT"},
        headers=headers,
    )
    return response.status_code


# ------------------------------------------------------------------------------
# The address rule itself
# ------------------------------------------------------------------------------


def test_with_no_trusted_proxy_the_header_is_always_ignored(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", [])
    assert client_ip(_request(OUTSIDER, "198.51.100.7")) == OUTSIDER
    assert client_ip(_request(PROXY, "198.51.100.7")) == PROXY


def test_a_spoofed_header_from_outside_is_ignored(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", [PROXY])
    assert client_ip(_request(OUTSIDER, "198.51.100.7")) == OUTSIDER
    # Pretending to be the proxy inside the header does not help either.
    assert client_ip(_request(OUTSIDER, f"198.51.100.7, {PROXY}")) == OUTSIDER


def test_the_header_is_believed_from_the_proxy(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", [PROXY])
    assert client_ip(_request(PROXY, "198.51.100.7")) == "198.51.100.7"
    assert client_ip(_request(PROXY, "2001:db8::1")) == "2001:db8::1"


def test_only_the_entry_the_proxy_wrote_is_believed(monkeypatch):
    """The proxy appends the address it saw; earlier entries came from the client."""
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", [PROXY])
    assert client_ip(_request(PROXY, "10.1.1.1, 198.51.100.7")) == "198.51.100.7"


def test_a_missing_or_unreadable_header_falls_back_to_the_peer(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", [PROXY])
    assert client_ip(_request(PROXY)) == PROXY
    assert client_ip(_request(PROXY, "")) == PROXY
    assert client_ip(_request(PROXY, "not-an-address")) == PROXY
    assert client_ip(_request(PROXY, "198.51.100.7, <script>")) == PROXY
    assert client_ip(_request(None, "198.51.100.7")) == "unknown"


def test_a_trusted_network_and_a_bad_entry(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", ["not-a-network", "172.28.0.0/24"])
    assert client_ip(_request("172.28.0.99", "198.51.100.7")) == "198.51.100.7"
    assert client_ip(_request("172.29.0.99", "198.51.100.7")) == "172.29.0.99"


# ------------------------------------------------------------------------------
# What it means for the registration rate limit
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_an_outsider_cannot_dodge_the_rate_limit_with_a_spoofed_header(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", [PROXY])
    monkeypatch.setattr(settings, "REGISTRATION_RATE_LIMIT_PER_MINUTE", 2)
    async with _client_from(OUTSIDER) as client:
        # A different made-up address on every request: all counted as one caller.
        statuses = [await _register(client, n, f"198.51.100.{n}") for n in range(1, 5)]
    assert statuses == [201, 201, 429, 429]


@pytest.mark.anyio
async def test_clients_behind_the_proxy_each_get_their_own_budget(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", [PROXY])
    monkeypatch.setattr(settings, "REGISTRATION_RATE_LIMIT_PER_MINUTE", 2)
    async with _client_from(PROXY) as client:
        first_client = [await _register(client, n, "198.51.100.7") for n in range(1, 4)]
        second_client = [await _register(client, n, "198.51.100.8") for n in range(4, 6)]
    # One client's flood does not lock the next client out.
    assert first_client == [201, 201, 429]
    assert second_client == [201, 201]


@pytest.mark.anyio
async def test_without_a_trusted_proxy_everything_from_one_peer_shares_a_budget(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", [])
    monkeypatch.setattr(settings, "REGISTRATION_RATE_LIMIT_PER_MINUTE", 2)
    async with _client_from(PROXY) as client:
        statuses = [await _register(client, n, f"198.51.100.{n}") for n in range(1, 4)]
    assert statuses == [201, 201, 429]


# ------------------------------------------------------------------------------
# No silent in-memory database on a deployment
# ------------------------------------------------------------------------------


class _UnreachableDatabase:
    """Stands in for a database server that cannot be reached."""

    def __getitem__(self, name):
        raise ConnectionError("database unreachable")

    def __getattr__(self, name):
        raise ConnectionError("database unreachable")


@pytest.mark.anyio
async def test_startup_fails_when_a_required_database_is_unreachable(monkeypatch):
    monkeypatch.setattr(settings, "RECOGNITION_SIGNING_KEY", secrets.token_hex(32))
    monkeypatch.setattr(settings, "REQUIRE_DATABASE", True)
    monkeypatch.setattr("app.main.get_database", lambda: _UnreachableDatabase())
    with pytest.raises(RuntimeError, match="REQUIRE_DATABASE"):
        async with lifespan(app):
            pass


@pytest.mark.anyio
async def test_startup_falls_back_to_memory_only_when_a_database_is_not_required(monkeypatch):
    monkeypatch.setattr(settings, "RECOGNITION_SIGNING_KEY", secrets.token_hex(32))
    monkeypatch.setattr(settings, "REQUIRE_DATABASE", False)
    calls = {"n": 0}
    real_get_database = mongodb.get_database

    def flaky():
        calls["n"] += 1
        return _UnreachableDatabase() if calls["n"] == 1 else real_get_database()

    monkeypatch.setattr("app.main.get_database", flaky)
    async with lifespan(app):
        assert isinstance(mongodb._client, AsyncMongoMockClient)
