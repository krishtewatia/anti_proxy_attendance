"""Backend-side client for the internal vision service.

The vision service is reachable only over the internal network and requires
the shared service key. Frame bytes are passed through and never logged.
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class VisionServiceUnavailable(Exception):
    """The vision service could not be reached or returned an unusable response."""


def vision_service_headers() -> dict[str, str]:
    """Service-to-service credentials for calls to the vision service."""
    return {"X-API-Key": settings.VISION_SERVICE_API_KEY.strip()}


async def forward_frame_to_vision(
    frame_bytes: bytes,
    content_type: str,
    session_id: str,
) -> dict:
    """Send one camera frame to the vision service and return its recognition result."""
    url = f"{settings.VISION_SERVICE_URL.rstrip('/')}/process-frame"
    headers = {"Content-Type": content_type, **vision_service_headers()}

    try:
        async with httpx.AsyncClient(timeout=settings.VISION_FRAME_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                url,
                content=frame_bytes,
                headers=headers,
                params={"session_id": session_id},
            )
    except httpx.HTTPError as exc:
        logger.warning("Vision service request failed: %s", type(exc).__name__)
        raise VisionServiceUnavailable("vision service unreachable") from exc

    if resp.status_code != 200:
        logger.warning("Vision service returned HTTP %s for a frame", resp.status_code)
        raise VisionServiceUnavailable(f"vision service returned HTTP {resp.status_code}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise VisionServiceUnavailable("vision service returned a non-JSON response") from exc

    if not isinstance(data, dict):
        raise VisionServiceUnavailable("vision service returned an unexpected response")
    return data
