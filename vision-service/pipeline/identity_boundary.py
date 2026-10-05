"""Identity-Aware Boundary Crossing Module (Step 2).

Replaces rigid per-track direction state with identity-aware crossing detection:
1. Pending crossings: unconfirmed tracks hold crossings for up to pending_ttl seconds.
   When the track confirms, events are emitted with original crossing timestamps.
2. Identity-keyed side memory: tracks lost across WebRTC frame drops that reappear
   as a confirmed identity on the opposite side within infer_window have crossings inferred.
3. Normalized coordinates & deadband: robust to portrait/landscape phone orientations.
4. Cooldown: prevents duplicate consecutive bursts for the same identity and direction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Optional


def side_of(
    p: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
    deadband: float = 0.02,
) -> int:
    """Classify normalized point p=(x, y) relative to directed line from a to b.

    Convention (matching image/screen coordinates where y points down):
      - For horizontal / slanted lines (a[0] != b[0]):
        y < line_y - deadband (above line in screen coords) -> +1 (SIDE_A)
        y > line_y + deadband (below line in screen coords) -> -1 (SIDE_B)
      - For vertical lines (a[0] == b[0]):
        x < line_x - deadband (left of line) -> +1 (SIDE_A)
        x > line_x + deadband (right of line) -> -1 (SIDE_B)
      - Within corridor -> 0 (DEADBAND / ON_LINE)

    Returns:
      +1: Point is on SIDE_A
      -1: Point is on SIDE_B
       0: Point is within deadband corridor
    """
    x1, y1 = a
    x2, y2 = b
    px, py = p

    if abs(x2 - x1) > 1e-5:
        slope = (y2 - y1) / (x2 - x1)
        line_y = y1 + slope * (px - x1)
        if py < line_y - deadband:
            return 1
        elif py > line_y + deadband:
            return -1
        else:
            return 0
    else:
        line_x = x1
        if px < line_x - deadband:
            return 1
        elif px > line_x + deadband:
            return -1
        else:
            return 0


@dataclass
class _Track:
    last_side: int = 0
    last_seen: float = 0.0
    pending: list[tuple[str, float]] = field(default_factory=list)  # [(direction, timestamp)]


class IdentityBoundary:
    """Identity-aware boundary line tracker."""

    def __init__(
        self,
        a: tuple[float, float] = (0.0, 0.5),
        b: tuple[float, float] = (1.0, 0.5),
        deadband: float = 0.02,
        pending_ttl: float = 4.0,
        infer_window: float = 3.0,
        cooldown: float = 2.0,
        entry_side: str = "SIDE_A",
    ) -> None:
        self.a = (float(a[0]), float(a[1]))
        self.b = (float(b[0]), float(b[1]))
        self.deadband = float(deadband)
        self.pending_ttl = float(pending_ttl)
        self.infer_window = float(infer_window)
        self.cooldown = float(cooldown)
        self.entry_side = entry_side.upper()

        self.tracks: dict[int, _Track] = {}
        self.identity_side: dict[str, tuple[int, float]] = {}  # identity -> (side, timestamp)
        self.last_emit: dict[tuple[str, str], float] = {}  # (identity, direction) -> timestamp

        # Telemetry counters
        self.crossings_detected: int = 0
        self.crossings_discarded_unconfirmed: int = 0
        self.crossings_emitted: int = 0
        self.crossings_inferred: int = 0

    def _dir(self, old: int, new: int) -> Optional[str]:
        """Convert side transition (+1/-1) into ENTRY or EXIT."""
        if self.entry_side == "SIDE_A":
            if (old, new) == (1, -1):
                return "ENTRY"
            elif (old, new) == (-1, 1):
                return "EXIT"
        else:
            if (old, new) == (-1, 1):
                return "ENTRY"
            elif (old, new) == (1, -1):
                return "EXIT"
        return None

    def _emit(
        self,
        identity: str,
        direction: str,
        ts: float,
        out: list[dict[str, Any]],
        inferred: bool = False,
    ) -> None:
        key = (identity, direction)
        if ts - self.last_emit.get(key, -1e9) >= self.cooldown:
            self.last_emit[key] = ts
            self.crossings_emitted += 1
            if inferred:
                self.crossings_inferred += 1
            out.append(
                {
                    "identity": identity,
                    "direction": direction,
                    "ts": ts,
                    "inferred": inferred,
                }
            )

    def update(
        self,
        track_id: int,
        point: tuple[float, float],
        identity: Optional[str],
        now: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        """Process a per-track observation.

        Args:
          track_id: Integer tracker ID from ByteTrack.
          point: Normalized (x/frame_w, y/frame_h) face-box coordinate.
          identity: Confirmed identity string (e.g. 'student1') or None / 'UNKNOWN'.
          now: Unix epoch timestamp in seconds.

        Returns:
          List of emitted event dictionaries: [{"identity": str, "direction": str, "ts": float, "inferred": bool}]
        """
        now = now if now is not None else time.time()
        out: list[dict[str, Any]] = []

        # Filter out UNKNOWN or empty string identities
        confirmed_id = identity if (identity and identity != "UNKNOWN") else None

        t = self.tracks.setdefault(track_id, _Track())
        t.last_seen = now
        side = side_of(point, self.a, self.b, self.deadband)

        if side != 0:
            if t.last_side != 0 and side != t.last_side:
                d = self._dir(t.last_side, side)
                if d:
                    self.crossings_detected += 1
                    if confirmed_id:
                        self._emit(confirmed_id, d, now, out)
                    else:
                        t.pending.append((d, now))
            t.last_side = side

        if confirmed_id:
            # 1. Flush pending crossings made before confirmation (using original timestamps)
            for d, ts in t.pending:
                if now - ts <= self.pending_ttl:
                    self._emit(confirmed_id, d, ts, out)
                else:
                    self.crossings_discarded_unconfirmed += 1
            t.pending.clear()

            # 2. Infer crossing lost to track-ID churn (WebRTC jitter / ByteTrack reset)
            prev = self.identity_side.get(confirmed_id)
            if side != 0:
                if prev and prev[0] != side and (now - prev[1] <= self.infer_window) and not out:
                    d = self._dir(prev[0], side)
                    if d:
                        self._emit(confirmed_id, d, now, out, inferred=True)
                self.identity_side[confirmed_id] = (side, now)
        else:
            # Purge expired unconfirmed crossings
            surviving = []
            for d, ts in t.pending:
                if now - ts <= self.pending_ttl:
                    surviving.append((d, ts))
                else:
                    self.crossings_discarded_unconfirmed += 1
            t.pending = surviving

        return out

    def prune_stale_tracks(self, now: Optional[float] = None, max_age: float = 15.0) -> None:
        """Clean up internal memory for tracks no longer active."""
        now = now if now is not None else time.time()
        dead_ids = [
            tid
            for tid, tr in self.tracks.items()
            if (now - tr.last_seen > max_age and not tr.pending)
        ]
        for tid in dead_ids:
            del self.tracks[tid]
