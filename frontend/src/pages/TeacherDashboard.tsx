import { isSessionCompleted } from "../utils/sessions.ts";
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
  const completedCount = sessions.filter((s) => isSessionCompleted(s.status)).length;

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
