from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import secrets
import threading
import time
from typing import Any, Optional
import uuid

import requests

from events.outbox import DEFAULT_OUTBOX_PATH, DurableOutbox

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
    - Optional SQLite DurableOutbox with background drain worker and exponential backoff.
    - Non-blocking dispatch (<1ms) so CV frame loop never stalls on network I/O.
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
        api_key: str | None = None,
        enable_outbox: bool = False,
        outbox_path: Path | str | None = None,
        max_outbox_entries: int = 10_000,
    ):
        self.backend_url = (backend_url or os.getenv("BACKEND_URL") or DEFAULT_BACKEND_URL).rstrip(
            "/"
        )

        self.timeout = timeout
        self.raise_on_failure = raise_on_failure
        self.dedup_by_track = dedup_by_track
        self.session = session or requests.Session()

        self.api_key = api_key or os.getenv("VISION_SERVICE_API_KEY")
        if self.api_key:
            self.session.headers["X-API-Key"] = self.api_key

        self._dispatched_event_ids: set[str] = set()
        self._dispatched_track_events: set[tuple[str, int, str]] = set()

        # Funnel counters
        self.http_2xx_count: int = 0
        self.backend_stored_count: int = 0
        self.in_active_session_count: int = 0

        # Durable outbox setup
        self.enable_outbox = enable_outbox or (
            os.getenv("ENABLE_EVENT_OUTBOX", "").lower() == "true"
        )
        self.outbox: Optional[DurableOutbox] = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

        if self.enable_outbox:
            self.outbox = DurableOutbox(
                db_path=outbox_path or DEFAULT_OUTBOX_PATH,
                max_entries=max_outbox_entries,
            )
            self._worker_thread = threading.Thread(
                target=self._drain_outbox_worker,
                daemon=True,
                name="EventDispatcher-OutboxWorker",
            )
            self._worker_thread.start()

    def reset(self) -> None:
        """Clear local deduplication cache."""
        self._dispatched_event_ids.clear()
        self._dispatched_track_events.clear()
        if self.outbox is not None:
            self.outbox.clear()

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

    def dispatch(self, event: dict[str, Any]) -> bool:
        """Non-blocking dispatch: format and enqueue to outbox.

        Returns immediately without performing network I/O.
        """
        payload = self.format_payload(event)
        event_id = payload["event_id"]
        camera_id = payload["camera_id"]
        track_id = payload["track_id"]
        direction = payload["direction"]
        track_key = (camera_id, track_id, direction)

        if event_id in self._dispatched_event_ids:
            return True
        if self.dedup_by_track and track_key in self._dispatched_track_events:
            return True

        if self.outbox is not None:
            ok = self.outbox.enqueue(payload)
            if ok:
                self._wake_event.set()
            return ok

        # Fallback to synchronous send if outbox not enabled
        try:
            self._send_payload_sync(payload, raise_on_failure=False)
            return True
        except Exception:
            return False

    def send_event(
        self,
        event: dict[str, Any],
        raise_on_failure: bool | None = None,
        sync: bool | None = None,
    ) -> dict[str, Any]:
        """Send one vision event to FastAPI backend.

        If sync is True (or outbox is disabled), sends synchronously via HTTP.
        If sync is False and outbox is enabled, enqueues non-blocking and returns immediately.
        """
        payload = self.format_payload(event)

        # If outbox is enabled and async requested, enqueue and return immediately
        if self.enable_outbox and sync is False:
            ok = self.dispatch(event)
            return {
                "event_id": payload["event_id"],
                "status": "enqueued" if ok else "error",
                "message": "Enqueued to durable outbox",
            }

        return self._send_payload_sync(payload, raise_on_failure=raise_on_failure)

    def send_camera_heartbeat(
        self,
        camera_id: str,
        state: str,
        fps: float,
        dropped_frames: int = 0,
        metadata: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> bool:
        """Send camera operational health heartbeat to FastAPI backend without video frames."""
        url = f"{self.backend_url}/api/v1/cameras/{camera_id}/heartbeat"
        payload = {
            "camera_id": camera_id,
            "state": state,
            "fps": float(fps),
            "dropped_frames": int(dropped_frames),
            "metadata": metadata or {},
        }
        headers = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        try:
            resp = self.session.post(
                url,
                json=payload,
                headers=headers,
                timeout=timeout or self.timeout,
            )
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("Failed to dispatch heartbeat for camera %s: %s", camera_id, exc)
            return False

    def _send_payload_sync(
        self,
        payload: dict[str, Any],
        raise_on_failure: bool | None = None,
    ) -> dict[str, Any]:
        """Synchronously POST an event payload to the backend."""
        should_raise = self.raise_on_failure if raise_on_failure is None else raise_on_failure

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
            self.http_2xx_count += 1
            data = response.json()
            if data.get("status") in ("accepted", "duplicate"):
                self.backend_stored_count += 1
            if data.get("session_id"):
                self.in_active_session_count += 1
            # Mark as dispatched
            self._dispatched_event_ids.add(event_id)
            self._dispatched_track_events.add(track_key)
            return data

        # Non-2xx response
        err_msg = f"Backend rejected event with HTTP {response.status_code}: {response.text}"
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

    def _drain_outbox_worker(self) -> None:
        """Background worker thread draining the outbox in chronological order."""
        logger.info("Outbox drain worker thread started.")
        while not self._stop_event.is_set():
            if self.outbox is None:
                break

            pending = self.outbox.get_pending(limit=25)
            if not pending:
                # Wait for new events or timeout
                self._wake_event.wait(timeout=0.2)
                self._wake_event.clear()
                continue

            for row_id, payload, retry_count in pending:
                if self._stop_event.is_set():
                    break

                event_id = payload.get("event_id", "")
                camera_id = payload.get("camera_id", "")
                track_id = payload.get("track_id", 0)
                direction = payload.get("direction", "")
                track_key = (camera_id, track_id, direction)

                url = f"{self.backend_url}{EVENT_ENDPOINT}"
                try:
                    resp = self.session.post(url, json=payload, timeout=self.timeout)
                    if resp.status_code in (200, 201):
                        self.outbox.mark_sent(row_id)
                        self._dispatched_event_ids.add(event_id)
                        self._dispatched_track_events.add(track_key)
                    elif 400 <= resp.status_code < 500 and resp.status_code not in (408, 429):
                        # Client permanent error (bad schema, etc)
                        logger.error(
                            "Outbox permanent rejection for event %s (HTTP %d): %s",
                            event_id,
                            resp.status_code,
                            resp.text,
                        )
                        self.outbox.mark_failed(row_id, permanent=True)
                    else:
                        # 5xx, 429, or 408: transient server error, retry with exponential backoff
                        backoff = (
                            min(15.0, 0.5 * (2 ** min(retry_count, 5)))
                            + (secrets.randbelow(200) + 100) / 1000.0
                        )
                        logger.warning(
                            "Outbox transient failure for event %s (HTTP %d), retrying in %.2fs (attempt %d)",
                            event_id,
                            resp.status_code,
                            backoff,
                            retry_count + 1,
                        )
                        self.outbox.mark_failed(row_id, permanent=False, backoff_seconds=backoff)
                        time.sleep(0.1)
                except (requests.exceptions.RequestException, requests.exceptions.Timeout) as exc:
                    backoff = (
                        min(15.0, 0.5 * (2 ** min(retry_count, 5)))
                        + (secrets.randbelow(200) + 100) / 1000.0
                    )
                    logger.warning(
                        "Outbox connection error for event %s: %s. Retrying in %.2fs (attempt %d)",
                        event_id,
                        exc,
                        backoff,
                        retry_count + 1,
                    )
                    self.outbox.mark_failed(row_id, permanent=False, backoff_seconds=backoff)
                    time.sleep(0.2)

    def flush(self, timeout: float = 10.0) -> bool:
        """Wait until all pending events in the durable outbox are sent."""
        if not self.enable_outbox or self.outbox is None:
            return True

        self._wake_event.set()
        deadline = time.time() + timeout
        while time.time() < deadline:
            pending = self.outbox.pending_count()
            if pending == 0:
                return True
            time.sleep(0.05)
            self._wake_event.set()

        remaining = self.outbox.pending_count()
        logger.warning("Flush timed out with %d events still pending in outbox.", remaining)
        return remaining == 0

    def close(self) -> None:
        """Stop worker thread cleanly."""
        self._stop_event.set()
        self._wake_event.set()
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
            self._worker_thread = None
        if self.outbox is not None:
            self.outbox.close()
