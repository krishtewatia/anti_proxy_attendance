import React, { useEffect, useState } from "react";
import { AuditLogs } from "../components/audit";
import { CreateSessionModal } from "../components/session";
import { api } from "../services";
import type { SessionResponse, UserResponse } from "../types";
import "./teacher-dashboard.css";

interface TeacherDashboardProps {
  user: UserResponse;
  onLogout: () => void;
  onNavigate?: (path: string) => void;
  activeNavId?: string;
}

function formatSessionDateTime(startIso: string, endIso: string): {
  dateStr: string;
  timeRangeStr: string;
} {
  try {
    const startDate = new Date(startIso);
    const endDate = new Date(endIso);

    const dateStr = startDate.toLocaleDateString(undefined, {
      day: "numeric",
      month: "short",
      year: "numeric",
    });

    const startTimeStr = startDate.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });

    const endTimeStr = endDate.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });

    return {
      dateStr,
      timeRangeStr: `${startTimeStr} – ${endTimeStr}`,
    };
  } catch {
    return {
      dateStr: startIso.slice(0, 10),
      timeRangeStr: `${startIso.slice(11, 16)} – ${endIso.slice(11, 16)}`,
    };
  }
}

export const TeacherDashboard: React.FC<TeacherDashboardProps> = ({
  user,
  onNavigate,
  activeNavId: _activeNavId,
}) => {
  const [sessions, setSessions] = useState<SessionResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isCreateSessionOpen, setIsCreateSessionOpen] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [cameraUrlCopied, setCameraUrlCopied] = useState(false);
  const [showAuditLogs, setShowAuditLogs] = useState(false);
  const [instantStarting, setInstantStarting] = useState(false);

  const handleInstantStart = async () => {
    setInstantStarting(true);
    setErrorMessage(null);
    try {
      const now = new Date();
      const in2h = new Date(now.getTime() + 120 * 60 * 1000);
      const instantPayload = {
        course_name: `Live Lecture Session (${now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })})`,
        classroom_id: "ROOM_101",
        start_time: now.toISOString(),
        end_time: in2h.toISOString(),
        required_presence_percentage: 75.0,
      };

      const created = await api.createSession(instantPayload);

      // Auto-enroll all directory students
      try {
        const directory = await api.getStudentsDirectory();
        if (directory.length > 0) {
          await api.updateSessionRoster(created.session_id, directory.map((s) => s.identity));
        }
      } catch {
        // fallback
      }

      setSuccessMessage("Session started instantly in Room 101!");
      const targetUrl = `/dashboard/teacher/sessions/${created.session_id}`;
      if (onNavigate) {
        onNavigate(targetUrl);
      } else if (typeof window !== "undefined") {
        window.history.pushState({}, "", targetUrl);
        window.dispatchEvent(new PopStateEvent("popstate"));
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(`Failed to start instant session: ${msg}`);
    } finally {
      setInstantStarting(false);
    }
  };

  const cameraUrl =
    typeof window !== "undefined"
      ? `http://${window.location.hostname}:8088`
      : "http://localhost:8088";

  const handleCopyCameraUrl = async () => {
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(cameraUrl);
        setCameraUrlCopied(true);
        setTimeout(() => setCameraUrlCopied(false), 2500);
      }
    } catch {
      // fallback
    }
  };

  const fetchSessions = async () => {
    setLoading(true);
    setErrorMessage(null);

    try {
      const data = await api.getSessions();
      setSessions(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(
        msg || "Unable to load attendance sessions. Please verify your connection."
      );
    } finally {
      setLoading(false);
    }
  };

  const handleQuickEndSession = async (e: React.MouseEvent, s: SessionResponse) => {
    e.stopPropagation();
    if (
      !window.confirm(
        `End session "${s.course_name}" and finalize attendance records now?`
      )
    ) {
      return;
    }
    try {
      await api.finalizeSession(s.session_id);
      setSuccessMessage(`Session "${s.course_name}" ended and attendance finalized.`);
      fetchSessions();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(`Failed to end session: ${msg}`);
    }
  };

  const handleQuickDeleteSession = async (e: React.MouseEvent, s: SessionResponse) => {
    e.stopPropagation();
    if (
      !window.confirm(
        `Are you sure you want to permanently delete session "${s.course_name}" (${s.session_id})?`
      )
    ) {
      return;
    }
    try {
      await api.deleteSession(s.session_id);
      setSuccessMessage(`Session "${s.course_name}" deleted.`);
      fetchSessions();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(`Failed to delete session: ${msg}`);
    }
  };

  useEffect(() => {
    fetchSessions();
  }, []);

  // Auto-dismiss success notification
  useEffect(() => {
    if (successMessage) {
      const timer = setTimeout(() => {
        setSuccessMessage(null);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [successMessage]);

  const handleSessionCreated = (_newSession: SessionResponse) => {
    setSuccessMessage("Session created successfully.");
    fetchSessions();
  };

  // Compute live aggregates from authentic backend session responses
  const scheduledCount = sessions.filter((s) => s.status === "SCHEDULED").length;
  const activeCount = sessions.filter((s) => s.status === "ACTIVE").length;
  const completedCount = sessions.filter((s) => s.status === "COMPLETED").length;

  return (
    <div className="teacher-dashboard">
      {/* Top Header */}
      <header className="teacher-dashboard-header">
        <h1 className="teacher-title">Teacher Dashboard</h1>
        <p className="teacher-subtitle">
          Welcome back, <span className="teacher-email-highlight">{user.email}</span>.
          {" "}Manage sessions and monitor student attendance verification in real-time.
        </p>
      </header>

      {/* Success Notification Banner */}
      {successMessage && (
        <div className="dashboard-success-banner" role="status">
          <div className="dashboard-success-content">
            <div className="dashboard-success-icon" aria-hidden="true">
              <svg fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
            </div>
            <span className="dashboard-success-text">{successMessage}</span>
          </div>
          <button
            type="button"
            className="dashboard-banner-close"
            onClick={() => setSuccessMessage(null)}
            aria-label="Dismiss notification"
          >
            <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}

      {/* 3 Metric Cards Computed From Real Sessions */}
      <section className="stats-grid" aria-label="Session Statistics">
        <div className="stat-card stat-scheduled">
          <div className="stat-icon-wrapper" aria-hidden="true">
            <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <div className="stat-info">
            <span className="stat-value">{loading ? "—" : scheduledCount}</span>
            <span className="stat-label">Scheduled Sessions</span>
          </div>
        </div>

        <div className="stat-card stat-active">
          <div className="stat-icon-wrapper" aria-hidden="true">
            <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
            </svg>
          </div>
          <div className="stat-info">
            <span className="stat-value">{loading ? "—" : activeCount}</span>
            <span className="stat-label">Active Now</span>
          </div>
        </div>

        <div className="stat-card stat-completed">
          <div className="stat-icon-wrapper" aria-hidden="true">
            <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <div className="stat-info">
            <span className="stat-value">{loading ? "—" : completedCount}</span>
            <span className="stat-label">Completed</span>
          </div>
        </div>
      </section>

      {/* Mobile WebRTC Camera Node Banner */}
      <section className="dashboard-camera-banner" aria-label="Mobile Camera WebRTC Link">
        <div className="camera-banner-content">
          <div className="camera-banner-icon" aria-hidden="true">
            <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316z" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0zM18.75 10.5h.008v.008h-.008V10.5z" />
            </svg>
          </div>
          <div className="camera-banner-text">
            <div className="camera-banner-title-line">
              <h3 className="camera-banner-title">Connect Mobile Phone as Classroom Camera</h3>
              <span className="camera-banner-pill">WebRTC Port 8088</span>
            </div>
            <p className="camera-banner-desc">
              Transform any smartphone into a live entrance recognition camera. Open this link on your phone browser while connected to the same local Wi-Fi.
            </p>
            <div className="camera-banner-url-box">
              <span className="camera-url-label">Direct Link:</span>
              <code className="camera-url-val">{cameraUrl}</code>
            </div>
          </div>
        </div>
        <div className="camera-banner-actions">
          <a
            href={cameraUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-open-camera"
            title="Open camera streamer in a new window"
          >
            <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2.2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
            </svg>
            <span>Open Mobile Camera</span>
          </a>
          <button
            type="button"
            className="btn-copy-camera"
            onClick={handleCopyCameraUrl}
            title="Copy URL to clipboard"
          >
            <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 01-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 011.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 00-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 01-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 00-3.375-3.375h-1.5a1.125 1.125 0 01-1.125-1.125v-1.5a3.375 3.375 0 00-3.375-3.375H9.75" />
            </svg>
            <span>{cameraUrlCopied ? "Copied Link!" : "Copy Link"}</span>
          </button>
        </div>
      </section>

      {/* Sessions Section */}
      <section className="sessions-section" aria-label="Session List">
        <div className="sessions-section-header">
          <div className="sessions-section-title-wrapper">
            <h2 className="sessions-section-title">Your Sessions</h2>
            {!loading && !errorMessage && (
              <span className="sessions-count-pill">{sessions.length} total</span>
            )}
          </div>
          <div className="sessions-actions">
            <a
              href={cameraUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-mobile-camera-header"
              title="Open Mobile WebRTC Camera Streamer on port 8088"
            >
              <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.2" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 1.5H8.25A2.25 2.25 0 006 3.75v16.5a2.25 2.25 0 002.25 2.25h7.5A2.25 2.25 0 0018 20.25V3.75a2.25 2.25 0 00-2.25-2.25H13.5m-3 0V3h3V1.5m-3 0h3m-3 18.75h3" />
              </svg>
              <span>📱 Open Mobile Camera (8088)</span>
            </a>
            <button
              type="button"
              className="btn-quick-start-session"
              onClick={handleInstantStart}
              disabled={instantStarting}
              title="Instantly launch session right now in ROOM_101 without manual typing"
            >
              <span>{instantStarting ? "Launching..." : "⚡ Quick Start Session"}</span>
            </button>
            <button
              type="button"
              className="btn-create-session"
              onClick={() => setIsCreateSessionOpen(true)}
            >
              <svg
                width="14"
                height="14"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              <span>+ Custom Session</span>
            </button>
            <button
              type="button"
              className="btn-refresh"
              onClick={fetchSessions}
              disabled={loading}
              title="Refresh session list"
            >
              <svg
                className={loading ? "spinner" : ""}
                width="14"
                height="14"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99"
                />
              </svg>
              <span>{loading ? "Refreshing..." : "Refresh"}</span>
            </button>
          </div>
        </div>

        {/* State 1: Loading */}
        {loading && (
          <div className="dashboard-loading" aria-live="polite">
            <div className="skeleton-grid">
              <div className="skeleton-card" />
              <div className="skeleton-card" />
              <div className="skeleton-card" />
            </div>
          </div>
        )}

        {/* State 2: Error */}
        {!loading && errorMessage && (
          <div className="dashboard-error-card" role="alert">
            <div className="error-icon-wrapper" aria-hidden="true">
              <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 7.5h.008v.008H12v-.008z" />
              </svg>
            </div>
            <div>
              <h3 className="error-title">Unable to load sessions</h3>
              <p className="error-desc">{errorMessage}</p>
            </div>
            <button type="button" className="btn-retry" onClick={fetchSessions}>
              Retry
            </button>
          </div>
        )}

        {/* State 3: Empty */}
        {!loading && !errorMessage && sessions.length === 0 && (
          <div className="dashboard-empty-card">
            <div className="empty-icon-wrapper" aria-hidden="true">
              <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
              </svg>
            </div>
            <h3 className="empty-title">No sessions yet</h3>
            <p className="empty-desc">
              You haven't scheduled any attendance sessions yet. Use the session creator to get started.
            </p>
            <button
              type="button"
              className="btn-create-session-empty"
              onClick={() => setIsCreateSessionOpen(true)}
            >
              <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2.2" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              <span>+ New Session</span>
            </button>
          </div>
        )}

        {/* State 4: Success - Session Cards */}
        {!loading && !errorMessage && sessions.length > 0 && (
          <div className="sessions-grid">
            {sessions.map((session) => {
              const { dateStr, timeRangeStr } = formatSessionDateTime(
                session.start_time,
                session.end_time
              );

              const handleCardClick = () => {
                const targetUrl = `/dashboard/teacher/sessions/${session.session_id}`;
                if (onNavigate) {
                  onNavigate(targetUrl);
                } else if (typeof window !== "undefined") {
                  window.history.pushState({}, "", targetUrl);
                  window.dispatchEvent(new PopStateEvent("popstate"));
                }
              };

              return (
                <article
                  key={session.session_id}
                  className="session-card session-card-clickable"
                  onClick={handleCardClick}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      handleCardClick();
                    }
                  }}
                  title={`View details for ${session.course_name}`}
                >
                  <div>
                    <div className="session-card-top">
                      <h3 className="session-course-name">{session.course_name}</h3>
                      <span className="session-classroom-badge">
                        {session.classroom_id}
                      </span>
                    </div>

                    <div className="session-meta-list" style={{ marginTop: "1rem" }}>
                      <div className="session-meta-row">
                        <svg
                          className="session-meta-icon"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          viewBox="0 0 24 24"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5"
                          />
                        </svg>
                        <span>{dateStr}</span>
                      </div>

                      <div className="session-meta-row">
                        <svg
                          className="session-meta-icon"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          viewBox="0 0 24 24"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z"
                          />
                        </svg>
                        <span>{timeRangeStr}</span>
                      </div>
                    </div>
                  </div>

                  <div className="session-card-bottom">
                    <span className="session-presence-req">
                      Required presence:{" "}
                      <span className="session-presence-val">
                        {session.required_presence_percentage}%
                      </span>
                    </span>

                    <span
                      className={`status-badge status-${session.status.toLowerCase()}`}
                    >
                      <span className="status-dot" aria-hidden="true" />
                      {session.status}
                    </span>
                  </div>

                  {/* Card Quick Action Bar */}
                  <div className="session-card-quick-actions" onClick={(e) => e.stopPropagation()}>
                    <button
                      type="button"
                      className="btn-card-action btn-card-details"
                      onClick={handleCardClick}
                      title="Manage session and attendance records"
                    >
                      Manage →
                    </button>
                    {session.status !== "FINALIZED" && (
                      <button
                        type="button"
                        className="btn-card-action btn-card-end"
                        onClick={(e) => handleQuickEndSession(e, session)}
                        title="End session and finalize attendance"
                      >
                        End Session
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn-card-action btn-card-del"
                      onClick={(e) => handleQuickDeleteSession(e, session)}
                      title="Delete session"
                    >
                      Delete
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      {/* Teacher Global Audit Trail Section (Collapsible for Clean, Minimal UI) */}
      <section className="dashboard-audit-section" style={{ marginTop: "2rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
          <button
            type="button"
            className="btn-toggle-audit"
            onClick={() => setShowAuditLogs(!showAuditLogs)}
            style={{
              background: "rgba(255, 255, 255, 0.04)",
              border: "1px solid var(--border-subtle, rgba(255, 255, 255, 0.1))",
              color: "var(--text-muted, #94a3b8)",
              padding: "0.5rem 1rem",
              borderRadius: "8px",
              cursor: "pointer",
              fontSize: "0.85rem",
              fontWeight: 600,
              display: "inline-flex",
              alignItems: "center",
              gap: "0.5rem",
              transition: "all 0.15s ease",
            }}
          >
            <span>{showAuditLogs ? "▼ Hide Audit & Activity Trail" : "▶ View Audit & Activity Trail"}</span>
          </button>
        </div>

        {showAuditLogs && (
          <AuditLogs
            title="Recent Audit Activity"
            subtitle="Chronological audit records across all sessions, roster updates, finalizations, and corrections."
          />
        )}
      </section>

      {/* Create Attendance Session Modal */}
      <CreateSessionModal
        isOpen={isCreateSessionOpen}
        onClose={() => setIsCreateSessionOpen(false)}
        onSessionCreated={handleSessionCreated}
      />
    </div>
  );
};
