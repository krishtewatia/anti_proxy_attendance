"""Limit on failed sign-ins, per client address and per account.

Only failures are counted. After too many inside the window, further
attempts are refused with 429 until the oldest failure is old enough, whether
or not the password offered is correct. A successful sign-in clears the
account's count (not the address's: one good password does not excuse an
address that is guessing at other accounts).

The account key is the email exactly as it was typed, lower-cased. It is
counted the same way whether or not such an account exists, so the limit says
nothing about which emails are registered.

Counts are kept in memory: the backend runs as a single process, and losing
them on a restart only gives an attacker one more window.
"""

from __future__ import annotations

import asyncio
from collections import deque
import math
import time

from app.core.config import settings

# Addresses and accounts being tracked at once. When full, entries with no
# recent failure are dropped; if all are recent, the oldest are dropped.
MAX_TRACKED_KEYS = 20_000


class FailureWindow:
    """Failure timestamps per key inside a sliding window."""

    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = {}

    def reset(self) -> None:
        self._failures.clear()

    def _recent(self, key: str, now: float, window: float) -> deque[float] | None:
        entries = self._failures.get(key)
        if entries is None:
            return None
        while entries and entries[0] <= now - window:
            entries.popleft()
        if not entries:
            del self._failures[key]
            return None
        return entries

    def retry_after(self, key: str, limit: int, window: float, now: float) -> int:
        """Seconds until ``key`` may try again; 0 when it is not blocked."""
        if limit <= 0:
            return 0
        entries = self._recent(key, now, window)
        if entries is None or len(entries) < limit:
            return 0
        # Allowed again once the failure that filled the limit leaves the window.
        return max(1, math.ceil(entries[-limit] + window - now))

    def record(self, key: str, now: float, window: float) -> None:
        if key not in self._failures and len(self._failures) >= MAX_TRACKED_KEYS:
            self._make_room(now, window)
        self._failures.setdefault(key, deque()).append(now)

    def clear(self, key: str) -> None:
        self._failures.pop(key, None)

    def _make_room(self, now: float, window: float) -> None:
        for key in list(self._failures):
            self._recent(key, now, window)
        if len(self._failures) >= MAX_TRACKED_KEYS:
            oldest = sorted(self._failures, key=lambda k: self._failures[k][-1])
            for key in oldest[: MAX_TRACKED_KEYS // 10]:
                del self._failures[key]


class LoginThrottle:
    def __init__(self) -> None:
        self._by_address = FailureWindow()
        self._by_account = FailureWindow()
        self._lock = asyncio.Lock()

    def reset(self) -> None:
        self._by_address.reset()
        self._by_account.reset()

    @staticmethod
    def account_key(email: str) -> str:
        return email.strip().lower()

    async def retry_after(self, address: str, email: str) -> int:
        """Seconds the caller must wait before signing in; 0 when allowed."""
        window = float(settings.LOGIN_FAILURE_WINDOW_SECONDS)
        now = time.monotonic()
        async with self._lock:
            return max(
                self._by_address.retry_after(
                    address, settings.LOGIN_MAX_FAILURES_PER_ADDRESS, window, now
                ),
                self._by_account.retry_after(
                    self.account_key(email), settings.LOGIN_MAX_FAILURES_PER_ACCOUNT, window, now
                ),
            )

    async def record_failure(self, address: str, email: str) -> None:
        window = float(settings.LOGIN_FAILURE_WINDOW_SECONDS)
        now = time.monotonic()
        async with self._lock:
            self._by_address.record(address, now, window)
            self._by_account.record(self.account_key(email), now, window)

    async def record_success(self, email: str) -> None:
        async with self._lock:
            self._by_account.clear(self.account_key(email))


login_throttle = LoginThrottle()
