import React, { useEffect, useMemo, useState } from "react";
import { api } from "../services";
import type {
  SessionLiveSnapshotResponse,
  SessionResponse,
  StudentLiveItem,
  UserResponse,
} from "../types";
import "./demo-session-view.css";

interface DemoSessionViewProps {
  user: UserResponse;
  onLogout: () => void;
  onNavigate: (path: string) => void;
}

interface FunnelData {
  frames_in?: number;
  faces_detected?: number;
  tracks_active?: number;
  tracks_confirmed?: number;
  crossings_detected?: number;
  crossings_discarded_unconfirmed?: number;
  events_dispatched?: number;
  http_2xx?: number;
  backend_stored?: number;
  in_active_session?: number;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  if (m === 0) return `${s}s`;
  return `${m}m ${s < 10 ? "0" : ""}${s}s`;
}

const TARGET_STUDENTS = ["student1", "student2", "student3", "student4"];

export const DemoSessionView: React.FC<DemoSessionViewProps> = ({
  user,
  onLogout,
  onNavigate,
}) => {
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [snapshot, setSnapshot] = useState<SessionLiveSnapshotResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [funnel, setFunnel] = useState<FunnelData | null>(null);
  const [visionFps, setVisionFps] = useState<number>(0);
  const [lastFrameAge, setLastFrameAge] = useState<number | null>(null);
  const [nowTimestamp, setNowTimestamp] = useState<number>(() => Date.now());

  const previewBaseUrl = useMemo(() => {
    if (typeof window !== "undefined") {
      const envUrl = (import.meta as any).env?.VITE_VISION_PREVIEW_URL;
      if (envUrl) return envUrl.replace(/\/$/, "");
      const host = window.location.hostname || "localhost";
      return `http://${host}:8088`;
    }
    return "http://localhost:8088";
  }, []);

  const previewMjpgUrl = `${previewBaseUrl}/preview.mjpg`;

  // 1. Initial Session Load
  useEffect(() => {
    let isMounted = true;
    async function loadActiveSession() {
      try {
        setLoading(true);
        const sessions = await api.getSessions();
        if (!isMounted) return;
        const active = sessions.find((s) => s.status === "ACTIVE") || sessions[0] || null;
        setSession(active);
        if (!active) {
          setError("No active demo session found. Please run scripts/seed_clean_demo.py.");
        }
      } catch (err: unknown) {
        if (!isMounted) return;
        const msg = err instanceof Error ? err.message : String(err);
        setError(`Failed to fetch sessions: ${msg}`);
      } finally {
        if (isMounted) setLoading(false);
      }
    }
    loadActiveSession();
    return () => {
      isMounted = false;
    };
  }, []);

  // 2. Authoritative 2.5s Polling from backend /live-snapshot
  useEffect(() => {
    if (!session) return;
    let isMounted = true;

    async function pollSnapshot() {
      if (!session) return;
      try {
        const data = await api.getSessionLiveSnapshot(session.session_id);
        if (!isMounted) return;
        setSnapshot(data);
        setError(null);
      } catch (err: unknown) {
        if (!isMounted) return;
        // Don't overwrite state on transient errors, just log
        console.warn("Live snapshot poll error:", err);
      }
    }

    pollSnapshot();
    const interval = setInterval(pollSnapshot, 2500);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [session]);

  // 3. Local 1-second timer tick for live dwell computation
  useEffect(() => {
    const timer = setInterval(() => {
      setNowTimestamp(Date.now());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // 4. Poll Vision Service Funnel & Health on Port 8088
  useEffect(() => {
    let isMounted = true;

    async function fetchVisionStatus() {
      try {
        const res = await fetch(`${previewBaseUrl}/status`, { mode: "cors" });
        if (res.ok) {
          const data = await res.json();
          if (!isMounted) return;
          if (data.funnel) setFunnel(data.funnel);
          if (typeof data.last_frame_age_seconds === "number") {
            setLastFrameAge(data.last_frame_age_seconds);
          }
          if (typeof data.fps === "number") setVisionFps(data.fps);
        }
      } catch {
        // Vision service might be starting up or idle
      }
    }

    fetchVisionStatus();
    const interval = setInterval(fetchVisionStatus, 2500);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [previewBaseUrl]);

  // Map student items for student1..student4
  const studentsLedger = useMemo(() => {
    const snapshotMap = new Map<string, StudentLiveItem>();
    if (snapshot?.students) {
      for (const st of snapshot.students) {
        snapshotMap.set(st.identity, st);
      }
    }

    return TARGET_STUDENTS.map((sid) => {
      const item = snapshotMap.get(sid);
      const isInside = item?.state === "INSIDE";
      const isOutside = item?.state === "OUTSIDE";

      let accumulated = item?.presence_duration_seconds || 0;
      if (isInside && item?.last_event_time) {
        const entryMs = new Date(item.last_event_time).getTime();
        const currentMs = nowTimestamp;
        const dwellDiff = Math.max(0, Math.floor((currentMs - entryMs) / 1000));
        accumulated += dwellDiff;
      }

      const totalDuration = (snapshot?.end_time && snapshot?.start_time)
        ? Math.max(1, Math.round((new Date(snapshot.end_time).getTime() - new Date(snapshot.start_time).getTime()) / 1000))
        : 3600;
      const pct = Math.min(100, Math.round((accumulated / totalDuration) * 100));

      return {
        identity: sid,
        state: item?.state || "NOT_SEEN",
        isInside,
        isOutside,
        accumulated,
        pct,
        lastEventTime: item?.last_event_time,
        lastEventDir: item?.last_event_direction,
      };
    });
  }, [snapshot, nowTimestamp]);

  const cameraStale = snapshot?.is_stale || (lastFrameAge !== null && lastFrameAge > 15);

  return (
    <div className="demo-view-container">
      {/* Top Header */}
      <header className="demo-header">
        <div className="demo-header-left">
          <div className="demo-badge-live">
            <span className="demo-badge-pulse" />
            Live Demo
          </div>
          <div>
            <h1 className="demo-header-title">
              {session?.course_name || "CS-101 Introduction to Computer Science"}
            </h1>
            <div className="demo-header-sub">
              Room: <strong>ROOM_101</strong> • Camera: <strong>CAM_ROOM_101_DOOR</strong> •
              Session: <strong>{session?.session_id || "Active"}</strong> • Teacher: <strong>{user.email}</strong>
            </div>
          </div>
        </div>

        <nav className="demo-header-nav">
          {session && (
            <>
              <button
                type="button"
                className="demo-nav-btn"
                onClick={() => onNavigate(`/dashboard/teacher/sessions/${session.session_id}`)}
              >
                Manual Adjustments
              </button>
              <button
                type="button"
                className="demo-nav-btn"
                onClick={() => onNavigate(`/dashboard/teacher/sessions/${session.session_id}?tab=audit`)}
              >
                Audit Trail
              </button>
            </>
          )}
          <button type="button" className="demo-nav-btn logout" onClick={onLogout}>
            Logout
          </button>
        </nav>
      </header>

      {/* Stale / Offline Banner */}
      {cameraStale && (
        <div className="demo-stale-banner">
          ⚠️ <strong>Doorway Camera Stale:</strong> No recent heartbeats or frames received from CAM_ROOM_101_DOOR in the last 15 seconds. Ensure the phone camera stream is active at http://&lt;LAN-IP&gt;:8088.
        </div>
      )}

      {loading && !session && (
        <div className="demo-stale-banner" style={{ background: "rgba(59, 130, 246, 0.15)", color: "#93c5fd" }}>
          🔄 Loading active demo session...
        </div>
      )}

      {error && (
        <div className="demo-stale-banner" style={{ background: "rgba(239, 68, 68, 0.15)", color: "#fca5a5" }}>
          ⚠️ {error}
        </div>
      )}

      {/* Main 2-Panel Interface */}
      <main className="demo-content-grid">
        {/* Left Panel: Camera Feed & Vision Telemetry */}
        <section className="demo-panel">
          <div className="demo-panel-header">
            <h2 className="demo-panel-title">📹 Live Camera Feed & Bounding Boxes</h2>
            <div style={{ fontSize: "0.8rem", color: "#38bdf8" }}>
              Port 8088 • Ingest
            </div>
          </div>

          <div className="demo-camera-wrapper">
            <img
              src={previewMjpgUrl}
              alt="Vision Service Live Stream"
              className="demo-camera-img"
              onError={() => {
                // Keep image placeholder active if stream disconnects momentarily
                console.debug("Camera preview stream waiting for frames...");
              }}
            />
            <div className="demo-camera-overlay-info">
              {lastFrameAge !== null ? `${lastFrameAge.toFixed(1)}s age` : "Connecting..."}
            </div>
          </div>

          {/* Telemetry Row */}
          <div className="demo-telemetry-box">
            <div className="demo-telemetry-row">
              <span>Stream Ingest URL:</span>
              <span className="demo-telemetry-val">{previewBaseUrl}</span>
            </div>
            <div className="demo-telemetry-row">
              <span>Vision Heartbeat:</span>
              <span className="demo-telemetry-val">
                {lastFrameAge !== null && lastFrameAge < 10 ? "🟢 ACTIVE" : "🟡 IDLE / WAITING"}
              </span>
            </div>
            <div className="demo-telemetry-row">
              <span>Pipeline Rate:</span>
              <span className="demo-telemetry-val">{visionFps > 0 ? `${visionFps.toFixed(1)} FPS` : "Standby / Idle"}</span>
            </div>
            <div className="demo-telemetry-row">
              <span>Doorway Boundary:</span>
              <span className="demo-telemetry-val">Mid-frame (2% deadband)</span>
            </div>
          </div>

          {/* 10-Stage Funnel Counter */}
          <div className="demo-funnel-strip">
            <div className="demo-funnel-title">
              <span>📊 10-Stage Pipeline Funnel</span>
              <span style={{ color: "#94a3b8", fontWeight: 400 }}>Real-time event counters</span>
            </div>
            <div className="demo-funnel-items">
              <div className="demo-funnel-cell">
                <div className="demo-funnel-cell-label">1. Frames</div>
                <div className="demo-funnel-cell-num">{funnel?.frames_in ?? 0}</div>
              </div>
              <div className="demo-funnel-cell">
                <div className="demo-funnel-cell-label">2. Faces</div>
                <div className="demo-funnel-cell-num">{funnel?.faces_detected ?? 0}</div>
              </div>
              <div className="demo-funnel-cell">
                <div className="demo-funnel-cell-label">3. Tracks</div>
                <div className="demo-funnel-cell-num">{funnel?.tracks_active ?? 0}</div>
              </div>
              <div className="demo-funnel-cell">
                <div className="demo-funnel-cell-label">4. Confirmed</div>
                <div className="demo-funnel-cell-num">{funnel?.tracks_confirmed ?? 0}</div>
              </div>
              <div className="demo-funnel-cell">
                <div className="demo-funnel-cell-label">5. Crossings</div>
                <div className="demo-funnel-cell-num">{funnel?.crossings_detected ?? 0}</div>
              </div>
              <div className="demo-funnel-cell">
                <div className="demo-funnel-cell-label">6. Discarded</div>
                <div className="demo-funnel-cell-num" style={{ color: "#f87171" }}>
                  {funnel?.crossings_discarded_unconfirmed ?? 0}
                </div>
              </div>
              <div className="demo-funnel-cell">
                <div className="demo-funnel-cell-label">7. Dispatched</div>
                <div className="demo-funnel-cell-num">{funnel?.events_dispatched ?? 0}</div>
              </div>
              <div className="demo-funnel-cell">
                <div className="demo-funnel-cell-label">8. HTTP 2xx</div>
                <div className="demo-funnel-cell-num">{funnel?.http_2xx ?? 0}</div>
              </div>
              <div className="demo-funnel-cell">
                <div className="demo-funnel-cell-label">9. Stored</div>
                <div className="demo-funnel-cell-num">{funnel?.backend_stored ?? 0}</div>
              </div>
              <div className="demo-funnel-cell">
                <div className="demo-funnel-cell-label">10. Session</div>
                <div className="demo-funnel-cell-num" style={{ color: "#34d399" }}>
                  {funnel?.in_active_session ?? 0}
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Right Panel: 4-Student Ledger */}
        <section className="demo-panel">
          <div className="demo-panel-header">
            <h2 className="demo-panel-title">🎓 Student Presence Ledger</h2>
            <div style={{ fontSize: "0.8rem", color: "#94a3b8" }}>
              Target: <strong>75% presence</strong>
            </div>
          </div>

          <div className="demo-ledger-list">
            {studentsLedger.map((st) => {
              const cardClass = st.isInside
                ? "in-room"
                : st.isOutside
                ? "exited"
                : "not-seen";

              return (
                <div key={st.identity} className={`demo-student-card ${cardClass}`}>
                  <div className="demo-student-header">
                    <div>
                      <div className="demo-student-identity">{st.identity}</div>
                      <div className="demo-student-sub">Enrolled • CS-101 Demo</div>
                    </div>

                    <div>
                      {st.isInside && (
                        <span className="demo-badge-in-room">
                          🟢 IN ROOM
                        </span>
                      )}
                      {st.isOutside && (
                        <span className="demo-badge-exited">
                          🟡 EXITED
                        </span>
                      )}
                      {!st.isInside && !st.isOutside && (
                        <span className="demo-badge-not-seen">
                          ⚪ NOT SEEN
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Dwell Timer & Presence */}
                  <div className="demo-dwell-row">
                    <span className="demo-dwell-label">Accumulated Presence:</span>
                    <span className="demo-dwell-timer">
                      {formatDuration(st.accumulated)} ({st.pct}%)
                    </span>
                  </div>

                  {/* Progress bar */}
                  <div className="demo-progress-track">
                    <div
                      className="demo-progress-fill"
                      style={{ width: `${st.pct}%` }}
                    />
                    <div
                      className="demo-progress-threshold"
                      style={{ left: "75%" }}
                      title="Required: 75%"
                    />
                  </div>

                  <div className="demo-last-event-hint">
                    <span>
                      {st.lastEventDir
                        ? `Last event: ${st.lastEventDir}`
                        : "No transit detected yet"}
                    </span>
                    <span>
                      {st.pct >= 75 ? "✅ On Track" : "⏳ Building Dwell"}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </main>
    </div>
  );
};
