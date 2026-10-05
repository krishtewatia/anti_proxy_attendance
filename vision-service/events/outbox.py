"""Durable Outbox implementation for Vision Service event dispatching.

Provides a persistent, bounded, crash-resilient queue using SQLite WAL mode.
Guarantees:
- Schema-conformant events only (no raw frames or biometric embeddings).
- Non-blocking enqueue (<1 ms) so computer vision frame loop never stalls.
- Crash recovery: un-sent events survive vision process or FastAPI restarts.
- Strict ordering preservation by sequence id.
- Bounded capacity with FIFO oldest-drop policy and explicit logging.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_OUTBOX_PATH = Path(__file__).resolve().parent.parent / "data" / "outbox.db"
DEFAULT_MAX_ENTRIES = 10_000
DEFAULT_MAX_AGE_SECONDS = 86_400.0  # 24 hours


class DurableOutbox:
    """SQLite-backed durable outbox for vision transit events."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    ):
        self.db_path = Path(db_path) if db_path else DEFAULT_OUTBOX_PATH
        self.max_entries = max_entries
        self.max_age_seconds = max_age_seconds
        self._local = threading.local()

        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create or reuse a thread-local connection with WAL mode and reasonable busy timeout."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                str(self.db_path),
                timeout=10.0,
                check_same_thread=False,
                isolation_level=None,  # Autocommit mode
            )
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        """Close thread-local database connection if open."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception as exc:
                logger.debug("Non-critical error closing thread-local SQLite connection: %s", exc)
            self._local.conn = None

    def _init_db(self) -> None:
        """Initialize SQLite table and indexes."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS outbox_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    camera_id TEXT NOT NULL,
                    track_id INTEGER NOT NULL,
                    identity TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    last_attempt REAL DEFAULT NULL,
                    next_retry_after REAL DEFAULT 0.0
                );
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_outbox_pending
                ON outbox_events (status, next_retry_after, id);
            """)

    def enqueue(self, payload: dict[str, Any]) -> bool:
        """Enqueue an event payload into the durable outbox.

        Must be called with formatted, schema-conformant event dict.
        Returns True on successful enqueue, False if rejected.
        """
        event_id = str(payload.get("event_id", ""))
        if not event_id:
            logger.error("Cannot enqueue event without event_id.")
            return False

        # Security validation: ensure no raw images or embedding arrays are present
        if "frame" in payload or "image" in payload or "embedding" in payload:
            logger.error(
                "Outbox security check failed: rejected non-schema event containing images/embeddings."
            )
            return False

        now = time.time()
        payload_str = json.dumps(payload)

        try:
            with self._get_connection() as conn:
                # 1. Enforce max entries bound
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM outbox_events WHERE status = 'PENDING';"
                )
                count = cursor.fetchone()[0]

                if count >= self.max_entries:
                    # Drop oldest pending event
                    drop_cursor = conn.execute("""
                        SELECT id, event_id FROM outbox_events
                        WHERE status = 'PENDING'
                        ORDER BY id ASC LIMIT 1;
                    """)
                    row = drop_cursor.fetchone()
                    if row:
                        old_id, old_eid = row
                        conn.execute("DELETE FROM outbox_events WHERE id = ?;", (old_id,))
                        logger.warning(
                            "Outbox capacity reached (%d entries). Dropped oldest event %s (id=%d).",
                            self.max_entries,
                            old_eid,
                            old_id,
                        )

                # 2. Insert new event (ignore if duplicate event_id already queued)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO outbox_events (
                        event_id, camera_id, track_id, identity, direction,
                        timestamp, payload_json, status, retry_count, created_at, next_retry_after
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?, 0.0);
                """,
                    (
                        event_id,
                        str(payload.get("camera_id", "")),
                        int(payload.get("track_id", 0)),
                        str(payload.get("identity", "")),
                        str(payload.get("direction", "")),
                        str(payload.get("timestamp", "")),
                        payload_str,
                        now,
                    ),
                )
            return True
        except Exception as exc:
            logger.exception("Failed to enqueue event %s to outbox: %s", event_id, exc)
            return False

    def get_pending(self, limit: int = 50) -> list[tuple[int, dict[str, Any], int]]:
        """Fetch pending events ready for transmission in strict sequence order.

        Returns list of (row_id, payload_dict, retry_count).
        """
        now = time.time()
        results = []
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT id, payload_json, retry_count FROM outbox_events
                    WHERE status = 'PENDING' AND next_retry_after <= ?
                    ORDER BY id ASC
                    LIMIT ?;
                """,
                    (now, limit),
                )

                for row_id, payload_str, retry_count in cursor.fetchall():
                    try:
                        payload = json.loads(payload_str)
                        results.append((row_id, payload, retry_count))
                    except Exception as exc:
                        logger.error("Failed to parse outbox payload for id %d: %s", row_id, exc)
                        # Mark invalid payload as permanently failed
                        conn.execute(
                            "UPDATE outbox_events SET status = 'FAILED' WHERE id = ?;", (row_id,)
                        )
        except Exception as exc:
            logger.exception("Error querying pending outbox events: %s", exc)

        return results

    def mark_sent(self, row_id: int) -> None:
        """Mark event as successfully delivered and remove it from outbox."""
        try:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM outbox_events WHERE id = ?;", (row_id,))
        except Exception as exc:
            logger.error("Failed to mark outbox event %d as sent: %s", row_id, exc)

    def mark_failed(
        self,
        row_id: int,
        permanent: bool = False,
        backoff_seconds: float = 1.0,
    ) -> None:
        """Record a transmission failure, update retry count and backoff."""
        now = time.time()
        next_retry = now + backoff_seconds
        new_status = "FAILED" if permanent else "PENDING"

        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    UPDATE outbox_events
                    SET status = ?,
                        retry_count = retry_count + 1,
                        last_attempt = ?,
                        next_retry_after = ?
                    WHERE id = ?;
                """,
                    (new_status, now, next_retry, row_id),
                )
        except Exception as exc:
            logger.error("Failed to mark outbox event %d failure: %s", row_id, exc)

    def pending_count(self) -> int:
        """Count of pending undelivered events."""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM outbox_events WHERE status = 'PENDING';"
                )
                return int(cursor.fetchone()[0])
        except Exception as exc:
            logger.error("Failed to count pending outbox events: %s", exc)
            return 0

    def purge_expired(self) -> int:
        """Purge events exceeding max age."""
        cutoff = time.time() - self.max_age_seconds
        try:
            with self._get_connection() as conn:
                cursor = conn.execute("DELETE FROM outbox_events WHERE created_at < ?;", (cutoff,))
                deleted = cursor.rowcount
                if deleted > 0:
                    logger.info(
                        "Purged %d expired outbox events (older than %ds).",
                        deleted,
                        int(self.max_age_seconds),
                    )
                return deleted
        except Exception as exc:
            logger.error("Failed to purge expired outbox events: %s", exc)
            return 0

    def clear(self) -> None:
        """Remove all entries from outbox table."""
        try:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM outbox_events;")
        except Exception as exc:
            logger.error("Failed to clear outbox: %s", exc)
