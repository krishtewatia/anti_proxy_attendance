from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from typing import Any, Optional
import uuid

import requests

DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
EVENT_ENDPOINT = "/api/v1/events"

logger = logging.getLogger(__name__)


class EventDispatchError(Exception):
    """Raised when dispatching an event to the backend fails."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_text: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class EventDispatcher:
    """Send vision sensory events to the FastAPI backend.

    Guarantees:
    - Preserves camera_id, track_id, identity, direction, timestamp, and CV evidence.
    - Sends sensory contract matching VisionEventCreate exactly.
    - Avoids transmitting duplicate events.
    - Handles HTTP and network failures cleanly with informative error messages.
    """

    ALLOWED_FIELDS = {
        "event_id",
        "camera_id",
        "track_id",
        "identity",
        "direction",
        "timestamp",
        "evidence",
    }

    REQUIRED_FIELDS = {
        "camera_id",
        "track_id",
        "identity",
        "direction",
        "timestamp",
        "evidence",
    }

    def __init__(
        self,
        backend_url: str | None = None,
        timeout: float = 5.0,
        raise_on_failure: bool = True,
        dedup_by_track: bool = True,
        session: requests.Session | None = None,
    ):
        self.backend_url = (
            backend_url
            or os.getenv("BACKEND_URL")
            or DEFAULT_BACKEND_URL
        ).rstrip("/")

        self.timeout = timeout
        self.raise_on_failure = raise_on_failure
        self.dedup_by_track = dedup_by_track
        self.session = session or requests.Session()

        self._dispatched_event_ids: set[str] = set()
        self._dispatched_track_events: set[tuple[str, int, str]] = set()

    def reset(self) -> None:
        """Clear local deduplication cache."""
        self._dispatched_event_ids.clear()
        self._dispatched_track_events.clear()

    def format_payload(self, event: dict[str, Any]) -> dict[str, Any]:
        """Validate and construct sensory event contract matching VisionEventCreate."""
        missing = [f for f in self.REQUIRED_FIELDS if f not in event]
        if missing:
            raise ValueError(f"Event missing required sensory fields: {missing}")

        event_id = str(event.get("event_id") or f"evt_{uuid.uuid4().hex[:16]}")
        camera_id = str(event["camera_id"])
        track_id = int(event["track_id"])
        identity = str(event["identity"])
        direction = str(event["direction"]).upper()

        raw_ts = event["timestamp"]
        if isinstance(raw_ts, datetime):
            if raw_ts.tzinfo is None:
                raw_ts = raw_ts.replace(tzinfo=timezone.utc)
            timestamp_str = raw_ts.isoformat()
        else:
            timestamp_str = str(raw_ts)

        # Evidence dictionary preservation
        evidence = event.get("evidence")
        if not isinstance(evidence, dict):
            raise ValueError("Event evidence must be a dictionary.")

        payload = {
            "event_id": event_id,
            "camera_id": camera_id,
            "track_id": track_id,
            "identity": identity,
            "direction": direction,
            "timestamp": timestamp_str,
            "evidence": {
                "peak_similarity": float(evidence.get("peak_similarity", 0.0)),
                "mean_similarity": float(evidence.get("mean_similarity", 0.0)),
                "supporting_frames": int(evidence.get("supporting_frames", 1)),
                "total_frames": int(evidence.get("total_frames", 1)),
                "consistency_pct": float(evidence.get("consistency_pct", 0.0)),
                "margin_over_runner_up": (
                    float(evidence["margin_over_runner_up"])
                    if evidence.get("margin_over_runner_up") is not None
                    else None
                ),
                "runner_up_identity": (
                    str(evidence["runner_up_identity"])
                    if evidence.get("runner_up_identity") is not None
                    else None
                ),
            },
        }

        return payload

    def send_event(
        self,
        event: dict[str, Any],
        raise_on_failure: bool | None = None,
    ) -> dict[str, Any]:
        """Send one vision event to FastAPI backend.

        Returns the parsed response JSON from backend.
        """
        should_raise = (
            self.raise_on_failure
            if raise_on_failure is None
            else raise_on_failure
        )

        payload = self.format_payload(event)
        event_id = payload["event_id"]
        camera_id = payload["camera_id"]
        track_id = payload["track_id"]
        direction = payload["direction"]
        track_key = (camera_id, track_id, direction)

        # 1. Local deduplication check
        if event_id in self._dispatched_event_ids:
            logger.warning(
                "Event %s already dispatched locally, skipping duplicate transmission.",
                event_id,
            )
            return {
                "event_id": event_id,
                "status": "duplicate",
                "message": "Event already dispatched locally",
            }

        if self.dedup_by_track and track_key in self._dispatched_track_events:
            logger.warning(
                "Track %s (%s) on %s already dispatched, skipping duplicate transmission.",
                track_id,
                direction,
                camera_id,
            )
            return {
                "event_id": event_id,
                "status": "duplicate",
                "message": f"Track {track_id} {direction} already dispatched locally",
            }

        # 2. HTTP POST dispatch
        url = f"{self.backend_url}{EVENT_ENDPOINT}"

        try:
            response = self.session.post(
                url,
                json=payload,
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout as exc:
            msg = f"Request to backend timed out after {self.timeout}s ({url})"
            logger.error(msg)
            if should_raise:
                raise EventDispatchError(msg) from exc
            return {
                "event_id": event_id,
                "status": "error",
                "message": msg,
            }
        except requests.exceptions.RequestException as exc:
            msg = f"Connection failed to backend ({url}): {exc}"
            logger.error(msg)
            if should_raise:
                raise EventDispatchError(msg) from exc
            return {
                "event_id": event_id,
                "status": "error",
                "message": msg,
            }

        # 3. Process HTTP Response
        if response.status_code in (200, 201):
            data = response.json()
            # Mark as dispatched
            self._dispatched_event_ids.add(event_id)
            self._dispatched_track_events.add(track_key)
            return data

        # Non-2xx response
        err_msg = (
            f"Backend rejected event with HTTP {response.status_code}: {response.text}"
        )
        logger.error(err_msg)
        if should_raise:
            raise EventDispatchError(
                err_msg,
                status_code=response.status_code,
                response_text=response.text,
            )

        return {
            "event_id": event_id,
            "status": "error",
            "status_code": response.status_code,
            "message": response.text,
        }
