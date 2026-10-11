"""Failed sign-ins are limited per account and per client address.

Only failures count. Past the limit the answer is 429 with Retry-After, even
for the right password, until the window has passed. A successful sign-in
clears the account's count. The limit behaves the same for an email that is
not registered, and a made-up X-Forwarded-For header does not get around it.
"""

from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
import pytest

from app.core.config import settings
from app.database import mongodb
from app.database.users import create_user
from app.main import app
from app.security.passwords import hash_password
from app.services import login_throttle as throttle_module

PASSWORD = "CorrectHorse123!"
PROXY = "172.28.0.10"
OUTSIDER = "203.0.113.50"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def fresh_db():
    mongodb._client = AsyncMongoMockClient()
    yield
    mongodb._client = AsyncMongoMockClient()


@pytest.fixture
def clock(monkeypatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(throttle_module.time, "monotonic", fake.monotonic)
    return fake


@pytest.fixture(autouse=True)
def limits(monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES_PER_ACCOUNT", 5)
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES_PER_ADDRESS", 20)
    monkeypatch.setattr(settings, "LOGIN_FAILURE_WINDOW_SECONDS", 900)
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", [])


def _client(peer: str = "127.0.0.1") -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, client=(peer, 40000)), base_url="http://test")


async def _user(email: str, status: str = "APPROVED") -> None:
    await create_user(
        user_id=f"user_{email.split('@')[0]}",
        email=email,
        password_hash=hash_password(PASSWORD),
        role="TEACHER",
        status=status,
    )


async def _login(client: AsyncClient, email: str, password: str = "wrong-password", forwarded: str | None = None):
    headers = {"X-Forwarded-For": forwarded} if forwarded else {}
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password}, headers=headers)


@pytest.mark.anyio
async def test_five_failures_lock_the_account_and_the_sixth_attempt_gets_429(clock):
    await _user("locked@limit.test")
    async with _client() as client:
        failures = [(await _login(client, "locked@limit.test")).status_code for _ in range(5)]
        blocked = await _login(client, "locked@limit.test")
        # The right password does not get through while the account is locked.
        blocked_with_right_password = await _login(client, "locked@limit.test", PASSWORD)

    assert failures == [401] * 5
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "900"
    assert "Too many failed sign-in attempts" in blocked.json()["detail"]
    assert blocked_with_right_password.status_code == 429
    assert "access_token" not in blocked_with_right_password.text


@pytest.mark.anyio
async def test_the_lock_ends_when_the_window_has_passed(clock):
    await _user("window@limit.test")
    async with _client() as client:
        for _ in range(5):
            await _login(client, "window@limit.test")
            clock.now += 60  # one failure a minute: the last at t+240
        clock.now += 300  # t+600: 300 s until the first failure is 900 s old
        still_blocked = await _login(client, "window@limit.test", PASSWORD)
        clock.now += 301
        allowed = await _login(client, "window@limit.test", PASSWORD)

    assert still_blocked.status_code == 429
    assert still_blocked.headers["Retry-After"] == "300"
    assert allowed.status_code == 200 and allowed.json()["access_token"]


@pytest.mark.anyio
async def test_only_failures_are_counted(clock):
    await _user("busy@limit.test")
    async with _client() as client:
        statuses = [(await _login(client, "busy@limit.test", PASSWORD)).status_code for _ in range(30)]
    assert statuses == [200] * 30


@pytest.mark.anyio
async def test_a_successful_sign_in_resets_the_account_count(clock):
    await _user("reset@limit.test")
    async with _client() as client:
        first = [(await _login(client, "reset@limit.test")).status_code for _ in range(4)]
        success = await _login(client, "reset@limit.test", PASSWORD)
        # Without the reset the first of these would be the fifth failure and
        # the second would be refused.
        after = [(await _login(client, "reset@limit.test")).status_code for _ in range(4)]
        still_fine = await _login(client, "reset@limit.test", PASSWORD)

    assert first == [401] * 4
    assert success.status_code == 200
    assert after == [401] * 4
    assert still_fine.status_code == 200


@pytest.mark.anyio
async def test_the_limit_does_not_reveal_whether_an_account_exists(clock):
    """An unregistered email is counted and locked exactly like a registered one."""
    await _user("real@limit.test")
    async with _client() as client:
        real = [await _login(client, "real@limit.test") for _ in range(6)]
    throttle_module.login_throttle.reset()
    async with _client() as client:
        ghost = [await _login(client, "ghost@limit.test") for _ in range(6)]

    assert [r.status_code for r in real] == [r.status_code for r in ghost] == [401] * 5 + [429]
    assert [r.json() for r in real] == [r.json() for r in ghost]
    assert real[-1].headers["Retry-After"] == ghost[-1].headers["Retry-After"]


@pytest.mark.anyio
async def test_the_account_key_ignores_case_and_surrounding_spaces(clock):
    await _user("case@limit.test")
    async with _client() as client:
        for email in ("case@limit.test", "CASE@limit.test", " Case@Limit.Test ", "case@LIMIT.test", "cAsE@limit.test"):
            await _login(client, email)
        blocked = await _login(client, "case@limit.test", PASSWORD)
    assert blocked.status_code == 429


@pytest.mark.anyio
async def test_one_address_guessing_at_many_accounts_is_stopped(clock):
    """Each account stays under its own limit; the address does not."""
    async with _client(OUTSIDER) as client:
        statuses = [(await _login(client, f"victim{n}@limit.test")).status_code for n in range(21)]
    async with _client("198.51.100.99") as other:
        from_elsewhere = await _login(other, "someone@limit.test")

    assert statuses == [401] * 20 + [429]
    # Another address is not affected.
    assert from_elsewhere.status_code == 401


@pytest.mark.anyio
async def test_a_successful_sign_in_does_not_clear_the_address_count(clock):
    await _user("insider@limit.test")
    async with _client(OUTSIDER) as client:
        for n in range(19):
            await _login(client, f"victim{n}@limit.test")
        assert (await _login(client, "insider@limit.test", PASSWORD)).status_code == 200
        twentieth = await _login(client, "victim19@limit.test")
        blocked = await _login(client, "victim20@limit.test")
    assert twentieth.status_code == 401
    assert blocked.status_code == 429


@pytest.mark.anyio
async def test_a_spoofed_forwarded_header_from_outside_does_not_bypass_the_limit(clock, monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", [PROXY])
    async with _client(OUTSIDER) as client:
        # A different made-up address on every request, a different account each time.
        statuses = [
            (await _login(client, f"victim{n}@limit.test", forwarded=f"198.51.100.{n + 1}")).status_code
            for n in range(22)
        ]
    assert statuses == [401] * 20 + [429, 429]


@pytest.mark.anyio
async def test_clients_behind_the_proxy_are_limited_separately(clock, monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", [PROXY])
    async with _client(PROXY) as client:
        attacker = [
            (await _login(client, f"victim{n}@limit.test", forwarded="198.51.100.7")).status_code
            for n in range(21)
        ]
        # Someone else, arriving through the same proxy, is not locked out.
        bystander = await _login(client, "bystander@limit.test", forwarded="198.51.100.8")
    assert attacker == [401] * 20 + [429]
    assert bystander.status_code == 401


@pytest.mark.anyio
async def test_a_pending_account_with_the_right_password_is_not_a_failed_guess(clock):
    await _user("pending@limit.test", status="PENDING")
    async with _client() as client:
        statuses = [(await _login(client, "pending@limit.test", PASSWORD)).status_code for _ in range(8)]
    assert statuses == [403] * 8


def test_the_table_of_tracked_keys_cannot_grow_without_bound(monkeypatch):
    monkeypatch.setattr(throttle_module, "MAX_TRACKED_KEYS", 100)
    window = throttle_module.FailureWindow()
    for n in range(1000):
        window.record(f"key{n}", now=float(n), window=10_000.0)
    assert len(window._failures) <= 100
    # The most recent key is still tracked.
    assert window.retry_after("key999", limit=1, window=10_000.0, now=1000.0) > 0


@pytest.mark.anyio
async def test_an_unknown_email_costs_the_same_password_work_as_a_wrong_password(clock, monkeypatch):
    """Otherwise the time an answer takes would show which emails are registered."""
    from app.services import auth_service

    await _user("known@limit.test")
    checked: list[str] = []
    real_verify = auth_service.verify_password

    def counting_verify(password: str, password_hash: str) -> bool:
        checked.append(password_hash)
        return real_verify(password, password_hash)

    monkeypatch.setattr(auth_service, "verify_password", counting_verify)
    async with _client() as client:
        known = await _login(client, "known@limit.test")
        unknown = await _login(client, "nobody@limit.test")

    assert (known.status_code, unknown.status_code) == (401, 401)
    assert known.json() == unknown.json()
    # One password check each; the unknown email is checked against a stand-in hash.
    assert len(checked) == 2 and checked[0] != checked[1]
