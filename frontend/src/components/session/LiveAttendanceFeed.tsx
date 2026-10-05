import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../services";
import type {
  CameraHealthItem,
  RecentLiveEvent,
  SessionLiveSnapshotResponse,
  StudentLiveItem,
  StudentLiveState,
} from "../../types";
import "./live-attendance-feed.css";

interface LiveAttendanceFeedProps {
  sessionId: string;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  if (m === 0) {
    return `${s}s`;
  }
  return `${m}m ${s}s`;
}

function formatRelativeTime(isoStr?: string | null): string {
  if (!isoStr) return "Never";
  try {
    const diff = (Date.now() - new Date(isoStr).getTime()) / 1000;
    if (diff < 5) return "Just now";
    if (diff < 60) return `${Math.floor(diff)}s ago`;
    const mins = Math.floor(diff / 60);
    if (mins < 60) return `${mins}m ago`;
    return new Date(isoStr).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  } catch {
    return isoStr;
  }
}

export const LiveAttendanceFeed: React.FC<LiveAttendanceFeedProps> = ({ sessionId }) => {
  const [snapshot, setSnapshot] = useState<SessionLiveSnapshotResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterState, setFilterState] = useState<"ALL" | StudentLiveState>("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [isAutoRefreshEnabled, setIsAutoRefreshEnabled] = useState(true);
  const [lastFetchedAt, setLastFetchedAt] = useState<Date | null>(null);

  const backoffDelayRef = useRef(3500); // 3.5s default interval
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isMountedRef = useRef(true);

  const fetchSnapshot = useCallback(
    async (isManual = false) => {
      if (isManual) {
        setRefreshing(true);
      }
      try {
        const data = await api.getSessionLiveSnapshot(sessionId);
        if (!isMountedRef.current) return;

        setSnapshot(data);
        setError(null);
        setLastFetchedAt(new Date());
        backoffDelayRef.current = 3500; // Reset backoff on success
      } catch (err: unknown) {
        if (!isMountedRef.current) return;
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
        // Exponential backoff on failure up to 30s
        backoffDelayRef.current = Math.min(backoffDelayRef.current * 1.5, 30000);
      } finally {
        if (isMountedRef.current) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    },
    [sessionId]
  );

  // Polling loop with visibility listener and backoff
  useEffect(() => {
    isMountedRef.current = true;
    fetchSnapshot();

    const scheduleNext = () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
      if (!isAutoRefreshEnabled) return;

      // Stop auto-polling if session is ENDED
      if (snapshot?.session_state === "ENDED") return;

      timerRef.current = setTimeout(async () => {
        // Pause if document is hidden (background tab)
        if (typeof document !== "undefined" && document.visibilityState === "hidden") {
          return;
        }
        await fetchSnapshot();
        scheduleNext();
      }, backoffDelayRef.current);
    };

    scheduleNext();

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible" && isAutoRefreshEnabled) {
        fetchSnapshot();
        scheduleNext();
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      isMountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [fetchSnapshot, isAutoRefreshEnabled, snapshot?.session_state]);

  if (loading && !snapshot) {
    return (
      <article className="live-feed-card" aria-busy="true" aria-live="polite">
        <div className="live-feed-header">
          <div className="live-feed-header-top">
            <div className="live-feed-title-group">
              <div className="live-feed-icon">
                <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
              </div>
              <h2 className="live-feed-title">Live Attendance & Presence Feed</h2>
            </div>
          </div>
        </div>
        <div style={{ padding: "2rem", textAlign: "center", color: "var(--text-muted)" }}>
          Connecting to real-time session feed...
        </div>
      </article>
    );
  }

  const sessionState = snapshot?.session_state ?? "UPCOMING";
  const cameras = snapshot?.cameras ?? [];
  const students = snapshot?.students ?? [];
  const recentEvents = snapshot?.recent_events ?? [];
  const isStale = snapshot?.is_stale || Boolean(error);

  // Filter students
  const filteredStudents = students.filter((s) => {
    const matchesFilter = filterState === "ALL" || s.state === filterState;
    const matchesSearch = s.identity.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesFilter && matchesSearch;
  });

  const insideCount = students.filter((s) => s.state === "INSIDE").length;
  const outsideCount = students.filter((s) => s.state === "OUTSIDE").length;
  const notSeenCount = students.filter((s) => s.state === "NOT_SEEN").length;

  return (
    <article className="live-feed-card" aria-live="polite">
      {/* Top Header */}
      <header className="live-feed-header">
        <div className="live-feed-header-top">
          <div className="live-feed-title-group">
            <div className="live-feed-icon" aria-hidden="true">
              <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
            </div>
            <div>
              <h2 className="live-feed-title">Live Attendance & Presence Feed</h2>
              <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
                Classroom: <strong style={{ color: "var(--text-main)" }}>{snapshot?.classroom_id}</strong> • Last updated:{" "}
                {lastFetchedAt ? lastFetchedAt.toLocaleTimeString() : "Pending"}
              </div>
            </div>
          </div>

          <div className="live-feed-controls">
            {/* Live State Badge */}
            <div
              className={`live-indicator ${
                !isAutoRefreshEnabled ? "paused" : sessionState === "ENDED" ? "ended" : ""
              }`}
            >
              <span className="pulse-dot" aria-hidden="true" />
              <span>
                {sessionState === "ENDED"
                  ? "Session Ended"
                  : !isAutoRefreshEnabled
                  ? "Updates Paused"
                  : "Live Feed Active"}
              </span>
            </div>

            {/* Toggle Auto-refresh */}
            {sessionState !== "ENDED" && (
              <button
                type="button"
                className="btn-live-toggle"
                onClick={() => setIsAutoRefreshEnabled(!isAutoRefreshEnabled)}
              >
                {isAutoRefreshEnabled ? "Pause" : "Resume"}
              </button>
            )}

            {/* Manual Refresh Button */}
            <button
              type="button"
              className={`btn-live-refresh ${refreshing ? "refreshing" : ""}`}
              onClick={() => fetchSnapshot(true)}
              disabled={refreshing}
              title="Refresh now"
            >
              <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              <span>{refreshing ? "Refreshing..." : "Refresh"}</span>
            </button>
          </div>
        </div>
      </header>

      {/* Stale / Offline Alert Banner */}
      {isStale && (
        <div className="live-stale-banner" role="alert">
          <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <div>
            <strong>Camera telemetry offline or stale.</strong> Vision service heartbeats have not been received in the last 15 seconds. New walk-ins and walk-outs may experience reporting delays until camera connection recovers.
          </div>
        </div>
      )}

      {/* Camera Health Status Strip */}
      <section className="camera-status-strip" aria-label="Camera Operational Status">
        <div className="camera-strip-header">
          <span>Classroom Cameras & Ingestion Health</span>
          <span>{cameras.length} Monitored</span>
        </div>

        {cameras.length === 0 ? (
          <div style={{ fontSize: "0.8125rem", color: "var(--text-muted)", padding: "0.25rem 0" }}>
            No cameras registered for classroom {snapshot?.classroom_id}. Physical or simulated CCTV can be registered via Admin Camera Registry.
          </div>
        ) : (
          <div className="camera-grid">
            {cameras.map((cam: CameraHealthItem) => {
              const statusClass = cam.is_stale
                ? "stale"
                : cam.status.toLowerCase();
              return (
                <div key={cam.camera_id} className="camera-pill">
                  <div className="camera-pill-info">
                    <span className="camera-pill-id">{cam.camera_id}</span>
                    <div className="camera-pill-meta">
                      {cam.role && <span className="cam-role-tag">{cam.role}</span>}
                      <span>{cam.heartbeat_age_seconds !== null ? `${Math.round(cam.heartbeat_age_seconds ?? 0)}s ago` : "Never"}</span>
                    </div>
                  </div>

                  <div className="camera-pill-status">
                    <span className={`cam-state-badge ${statusClass}`}>
                      {cam.is_stale ? "STALE" : cam.status}
                    </span>
                    {cam.fps !== null && cam.fps !== undefined && (
                      <span className="cam-fps">{cam.fps.toFixed(1)} FPS</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Presence Stats & Filter Bar */}
      <div className="live-stats-bar">
        <div className="stats-badges-group">
          <div className="stat-chip inside">
            <span>Inside:</span>
            <strong>{insideCount}</strong>
          </div>
          <div className="stat-chip outside">
            <span>Outside:</span>
            <strong>{outsideCount}</strong>
          </div>
          <div className="stat-chip">
            <span>Not Seen:</span>
            <strong>{notSeenCount}</strong>
          </div>
          <div className="stat-chip">
            <span>Rostered:</span>
            <strong>{students.length}</strong>
          </div>
        </div>

        <div className="live-filters-group">
          <input
            type="search"
            placeholder="Search student..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              padding: "0.3rem 0.65rem",
              fontSize: "0.8125rem",
              background: "rgba(255, 255, 255, 0.05)",
              border: "1px solid rgba(255, 255, 255, 0.12)",
              borderRadius: "var(--radius-sm)",
              color: "var(--text-main)",
            }}
          />

          {(["ALL", "INSIDE", "OUTSIDE", "NOT_SEEN"] as const).map((filter) => (
            <button
              key={filter}
              type="button"
              className={`live-filter-btn ${filterState === filter ? "active" : ""}`}
              onClick={() => setFilterState(filter)}
            >
              {filter.replace("_", " ")}
            </button>
          ))}
        </div>
      </div>

      {/* Students Live Presence Table */}
      <div className="live-table-container">
        <table className="live-table">
          <thead>
            <tr>
              <th>Student Identity</th>
              <th>Live State</th>
              <th>Presence Duration</th>
              <th>Progress</th>
              <th>Projected</th>
              <th>Flags & Observability</th>
              <th>Last Event</th>
            </tr>
          </thead>
          <tbody>
            {filteredStudents.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ textAlign: "center", padding: "2rem", color: "var(--text-muted)" }}>
                  No students matching current filter.
                </td>
              </tr>
            ) : (
              filteredStudents.map((st: StudentLiveItem) => {
                const fillClass =
                  st.projected_status === "PRESENT"
                    ? "present"
                    : st.is_on_track
                    ? "on-track"
                    : "absent";

                return (
                  <tr key={st.identity}>
                    {/* Identity */}
                    <td>
                      <div className="student-identity-cell">
                        <span className="student-identity-text">{st.identity}</span>
                        {!st.is_rostered && <span className="student-subtag">Unrostered Guest</span>}
                      </div>
                    </td>

                    {/* Live State Badge */}
                    <td>
                      <span className={`state-badge ${st.state.toLowerCase()}`}>
                        {st.state === "INSIDE" && "● "}
                        {st.state.replace("_", " ")}
                      </span>
                    </td>

                    {/* Duration */}
                    <td>
                      <strong style={{ fontFamily: "monospace" }}>
                        {formatDuration(st.presence_duration_seconds)}
                      </strong>
                    </td>

                    {/* Progress Bar */}
                    <td>
                      <div className="presence-progress-cell">
                        <div className="progress-track">
                          <div
                            className={`progress-fill ${fillClass}`}
                            style={{ width: `${Math.min(st.presence_percentage, 100)}%` }}
                          />
                        </div>
                        <div className="progress-label-row">
                          <span>{st.presence_percentage.toFixed(1)}%</span>
                          <span>Req: {snapshot?.required_presence_percentage}%</span>
                        </div>
                      </div>
                    </td>

                    {/* Projected Status */}
                    <td>
                      <span
                        style={{
                          fontSize: "0.75rem",
                          fontWeight: 700,
                          padding: "0.2rem 0.5rem",
                          borderRadius: "4px",
                          background:
                            st.projected_status === "PRESENT"
                              ? "rgba(16, 185, 129, 0.15)"
                              : st.is_on_track
                              ? "rgba(59, 130, 246, 0.15)"
                              : "rgba(239, 68, 68, 0.15)",
                          color:
                            st.projected_status === "PRESENT"
                              ? "#34d399"
                              : st.is_on_track
                              ? "#60a5fa"
                              : "#f87171",
                        }}
                      >
                        {st.projected_status === "PRESENT"
                          ? "PRESENT"
                          : st.is_on_track
                          ? "ON TRACK"
                          : "ABSENT"}
                      </span>
                    </td>

                    {/* Flags */}
                    <td>
                      <div className="flags-cell">
                        {st.no_exit_observed && (
                          <span className="flag-tag open-entry">In Room</span>
                        )}
                        {st.anomalies.map((anom) => (
                          <span key={anom} className="flag-tag anomaly">
                            {anom.replace(/_/g, " ")}
                          </span>
                        ))}
                        {!st.no_exit_observed && st.anomalies.length === 0 && (
                          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>—</span>
                        )}
                      </div>
                    </td>

                    {/* Last Event */}
                    <td>
                      <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                        {st.last_event_direction ? (
                          <>
                            <strong style={{ color: "var(--text-main)" }}>
                              {st.last_event_direction}
                            </strong>{" "}
                            • {formatRelativeTime(st.last_event_time)}
                          </>
                        ) : (
                          "None"
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Recent Events Ticker */}
      <section className="recent-events-card" aria-label="Recent Detections Ticker">
        <div className="recent-events-title">
          <span>Recent Optical Transit Events</span>
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 500 }}>
            {recentEvents.length} events logged
          </span>
        </div>

        {recentEvents.length === 0 ? (
          <div style={{ fontSize: "0.8125rem", color: "var(--text-muted)", textAlign: "center", padding: "1rem" }}>
            No transit events recorded yet for this session.
          </div>
        ) : (
          <div className="events-list">
            {recentEvents.map((ev: RecentLiveEvent) => (
              <div key={ev.event_id} className="event-item">
                <div className="event-left">
                  <span className={`event-badge ${ev.direction.toLowerCase()}`}>
                    {ev.direction}
                  </span>
                  <span className="event-identity">{ev.identity}</span>
                </div>

                <div className="event-right">
                  {ev.camera_id && <span>{ev.camera_id}</span>}
                  {ev.confidence !== null && ev.confidence !== undefined && (
                    <span>{(ev.confidence * 100).toFixed(0)}% conf</span>
                  )}
                  <span>{formatRelativeTime(ev.timestamp)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </article>
  );
};
