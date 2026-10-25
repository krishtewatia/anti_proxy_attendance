"""Rate limiting dependency for event ingestion and sensitive endpoints."""

from __future__ import annotations

import asyncio
from collections import deque
import time
from fastapi import HTTPException, Request, status

from app.core.client_ip import client_ip
from app.core.config import settings


class SlidingWindowRateLimiter:
    """Sliding-window in-memory rate limiter per key (client IP or camera_id)."""

    def __init__(self, limit_per_minute: int | None = None, window_seconds: float = 60.0):
        self.limit_per_minute = limit_per_minute
        self.window_seconds = window_seconds
        self._history: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    def get_limit(self) -> int:
        if self.limit_per_minute is not None:
            return self.limit_per_minute
        return settings.EVENTS_RATE_LIMIT_PER_MINUTE

    def reset(self) -> None:
        """Reset all rate limiter tracking."""
        self._history.clear()

    async def check(self, key: str, what: str = "requests") -> None:
        limit = self.get_limit()
        if limit <= 0:
            return  # Rate limiting disabled

        now = time.monotonic()
        cutoff = now - self.window_seconds

        async with self._lock:
            timestamps = self._history.setdefault(key, deque())
            # Evict timestamps outside the window
            while timestamps and timestamps[0] < cutoff:
                timestamps.popleft()

            if len(timestamps) >= limit:
                period = (
                    "minute"
                    if self.window_seconds == 60
                    else "hour"
                    if self.window_seconds == 3600
                    else f"{int(self.window_seconds)} seconds"
                )
                wait = max(1, int(timestamps[0] + self.window_seconds - now) + 1)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded: maximum {limit} {what} per {period} allowed.",
                    headers={"Retry-After": str(wait)},
                )

            timestamps.append(now)


events_rate_limiter = SlidingWindowRateLimiter()


async def check_events_rate_limit(request: Request) -> None:
    client_host = client_ip(request)
    await events_rate_limiter.check(client_host)


class _SettingLimiter(SlidingWindowRateLimiter):
    """Sliding-window limiter whose limit is read from a settings attribute at check time."""

    def __init__(self, setting_name: str, window_seconds: float = 60.0):
        super().__init__(window_seconds=window_seconds)
        self._setting_name = setting_name

    def get_limit(self) -> int:
        return int(getattr(settings, self._setting_name))


# Frame path: one budget per session and one per teacher.
frame_session_rate_limiter = _SettingLimiter("FRAME_RATE_LIMIT_PER_MINUTE")
frame_teacher_rate_limiter = _SettingLimiter("TEACHER_FRAME_RATE_LIMIT_PER_MINUTE")

# Public registration. A whole class signs up from one campus address, so the
# per-address budget (shared by the three registration routes) is a high
# ceiling against floods; the tight limits are per email and per roll number.
registration_rate_limiter = _SettingLimiter("REGISTRATION_RATE_LIMIT_PER_HOUR", window_seconds=3600)
registration_identity_rate_limiter = _SettingLimiter(
    "REGISTRATION_ATTEMPTS_PER_IDENTITY_PER_HOUR", window_seconds=3600
)
# Face photo checks during the student setup: per signed-in student, not per address.
photo_check_rate_limiter = _SettingLimiter("PHOTO_CHECKS_PER_HOUR", window_seconds=3600)


async def check_registration_rate_limit(request: Request) -> None:
    client_host = client_ip(request)
    await registration_rate_limiter.check(f"register:{client_host}", "sign-ups from one address")


async def check_registration_identity(email: str, roll_number: str | None = None) -> None:
    """Count an attempt for this email and roll number, whether or not it succeeds.

    Says nothing about whether either is registered: every attempt counts the same.
    """
    await registration_identity_rate_limiter.check(
        f"email:{(email or '').strip().lower()}", "sign-up attempts for one email"
    )
    if roll_number:
        await registration_identity_rate_limiter.check(
            f"roll:{roll_number.strip()}", "sign-up attempts for one roll number"
        )
