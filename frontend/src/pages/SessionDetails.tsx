import React, { useEffect, useState } from "react";
import { AuditLogs } from "../components/audit";
import { AlwaysOnVideoFeed, SessionAttendance } from "../components/session";
import { api } from "../services";
import type { SessionResponse, UserResponse } from "../types";
import "./session-details.css";

interface SessionDetailsProps {
  sessionId: string;
  user?: UserResponse;
  onNavigate: (path: string) => void;
}

function formatSessionDateTime(isoStr: string): string {
  try {
    const d = new Date(isoStr);
    const dateStr = d.toLocaleDateString(undefined, {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
    const timeStr = d.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
    return `${dateStr} • ${timeStr}`;
  } catch {
    return isoStr;
  }
}

export const SessionDetails: React.FC<SessionDetailsProps> = ({
  sessionId,
  user,
  onNavigate,
}) => {
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorType, setErrorType] = useState<"NOT_FOUND" | "FORBIDDEN" | "GENERAL" | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [banner, setBanner] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [attendanceRefreshKey, setAttendanceRefreshKey] = useState(0);
  const [rosterIdentities, setRosterIdentities] = useState<string[]>([]);

  const isUserAdmin = user?.role === "ADMIN";

  const handleEndSession = async () => {
    if (
      !window.confirm(
        "End session and finalize attendance records now? This locks the session against live camera events and calculates final attendance."
      )
    ) {
      return;
    }
    setActionLoading(true);
    setBanner(null);
    try {
      if (isUserAdmin) {
        await api.adminFinalizeSession(sessionId);
      } else {
        await api.finalizeSession(sessionId);
      }
      setSession((prev) => (prev ? { ...prev, status: "FINALIZED" } : prev));
      setAttendanceRefreshKey((k) => k + 1);
      setBanner({
        type: "success",
        text: "Session ended and attendance finalized! You can now manually adjust attendance records below.",
      });
      fetchSession();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setBanner({ type: "error", text: `Failed to end session: ${msg}` });
    } finally {
      setActionLoading(false);
    }
  };

  const handleDeleteSession = async () => {
    if (!session) return;
    if (
      !window.confirm(
        `Are you sure you want to permanently delete session "${session.course_name}" (${session.session_id})? This will delete all attendance records.`
      )
    ) {
      return;
    }
    setActionLoading(true);
    try {
      if (isUserAdmin) {
        await api.adminDeleteSession(sessionId);
        onNavigate("/dashboard/admin");
      } else {
        await api.deleteSession(sessionId);
        onNavigate("/dashboard/teacher");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setBanner({ type: "error", text: `Failed to delete session: ${msg}` });
      setActionLoading(false);
    }
  };

  const fetchSession = async () => {
    setLoading(true);
    setErrorType(null);
    setErrorMessage(null);

    try {
      const data = await api.getSession(sessionId);
      setSession(data);
      try {
        const rosterData = await api.getSessionRoster(sessionId);
        setRosterIdentities(rosterData?.identities || []);
      } catch {
        // roster might not be set yet
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(msg);

      if (msg.includes("404") || msg.toLowerCase().includes("not found")) {
        setErrorType("NOT_FOUND");
      } else if (
        msg.includes("403") ||
        msg.toLowerCase().includes("own") ||
        msg.toLowerCase().includes("permissions")
      ) {
        setErrorType("FORBIDDEN");
      } else {
        setErrorType("GENERAL");
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSession();
  }, [sessionId]);

  const handleCopyId = async (id: string) => {
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(id);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    } catch {
      // Ignore copy error
    }
  };

  // State 1: Loading
  if (loading) {
    return (
      <div className="session-details-page" aria-live="polite">
        <button
          type="button"
          className="session-back-btn"
          onClick={() => onNavigate("/dashboard/teacher")}
        >
          <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
          </svg>
          <span>Back to Sessions</span>
        </button>

        <div className="session-skeleton-header" />
        <div className="session-skeleton-box" />
      </div>
    );
  }

  // State 2: 404 Not Found
  if (errorType === "NOT_FOUND") {
    return (
      <div className="session-details-page">
        <button
          type="button"
          className="session-back-btn"
          onClick={() => onNavigate("/dashboard/teacher")}
        >
          <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
          </svg>
          <span>Back to Sessions</span>
        </button>

        <div className="session-error-container" role="alert">
          <div className="session-error-icon-wrapper not-found" aria-hidden="true">
            <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M12 18h.01"
              />
            </svg>
          </div>
          <h2 className="session-error-title">Session Not Found</h2>
          <p className="session-error-desc">
            This session may have been deleted or you may not have access to it.
          </p>
          <button
            type="button"
            className="btn-primary-action"
            onClick={() => onNavigate("/dashboard/teacher")}
          >
            Back to Sessions
          </button>
        </div>
      </div>
    );
  }

  // State 3: 403 Forbidden or other API error
  if (errorType || !session) {
    return (
      <div className="session-details-page">
        <button
          type="button"
          className="session-back-btn"
          onClick={() => onNavigate("/dashboard/teacher")}
        >
          <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
          </svg>
          <span>Back to Sessions</span>
        </button>

        <div className="session-error-container" role="alert">
          <div className="session-error-icon-wrapper forbidden" aria-hidden="true">
            <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z"
              />
            </svg>
          </div>
          <h2 className="session-error-title">
            {errorType === "FORBIDDEN" ? "Access Denied" : "Unable to Load Session"}
          </h2>
          <p className="session-error-desc">
            {errorMessage || "You do not have permission to view this attendance session."}
          </p>
          <div className="session-error-actions">
            <button
              type="button"
              className="btn-primary-action"
              onClick={() => onNavigate("/dashboard/teacher")}
            >
              Back to Sessions
            </button>
            <button
              type="button"
              className="btn-secondary-action"
              onClick={fetchSession}
            >
              Retry
            </button>
          </div>
        </div>
      </div>
    );
  }

  // State 4: Success - Display Real Session Information
  return (
    <div className="session-details-page">
      {/* Navigation Top */}
      <button
        type="button"
        className="session-back-btn"
        onClick={() => onNavigate(isUserAdmin ? "/dashboard/admin" : "/dashboard/teacher")}
      >
        <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
        </svg>
        <span>Back to {isUserAdmin ? "Admin Dashboard" : "Sessions"}</span>
      </button>

      {/* Header */}
      <header className="session-details-header">
        <h1 className="session-details-title">Session Details</h1>
        <p className="session-details-subtitle">
          View scheduled parameters, verification criteria, and classroom allocation.
        </p>
      </header>

      {/* Notification Banner */}
      {banner && (
        <div className={`session-banner session-banner-${banner.type}`} role="status">
          <div className="session-banner-content">
            <span className="session-banner-icon" aria-hidden="true">
              {banner.type === "success" ? "✓" : "!"}
            </span>
            <span>{banner.text}</span>
          </div>
          <button
            type="button"
            className="session-banner-close"
            onClick={() => setBanner(null)}
            aria-label="Dismiss banner"
          >
            ✕
          </button>
        </div>
      )}

      {/* Main Info Card */}
      <article className="session-info-card">
        {/* Top: Course Name & Status + Actions */}
        <div className="session-info-top">
          <div className="session-info-top-left">
            <h2 className="session-course-title">{session.course_name}</h2>
            <span className={`status-badge status-${session.status.toLowerCase()}`}>
              <span className="status-dot" aria-hidden="true" />
              {session.status}
            </span>
          </div>

          <div className="session-header-actions">
            {session.status !== "FINALIZED" ? (
              <button
                type="button"
                className="btn-end-session"
                onClick={handleEndSession}
                disabled={actionLoading}
                title="End session and finalize attendance records"
              >
                <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 7.5A2.25 2.25 0 017.5 5.25h9a2.25 2.25 0 012.25 2.25v9a2.25 2.25 0 01-2.25 2.25h-9a2.25 2.25 0 01-2.25-2.25v-9z" />
                </svg>
                <span>{actionLoading ? "Finalizing..." : "End Session & Finalize"}</span>
              </button>
            ) : (
              <span className="session-finalized-tag">
                ✓ Attendance Finalized
              </span>
            )}

            <button
              type="button"
              className="btn-delete-session"
              onClick={handleDeleteSession}
              disabled={actionLoading}
              title="Permanently delete this session and its attendance"
            >
              <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
              </svg>
              <span>Delete Session</span>
            </button>
          </div>
        </div>

        {/* Details Grid */}
        <div className="session-details-grid">
          {/* Classroom */}
          <div className="session-detail-item">
            <span className="detail-label">Classroom</span>
            <div className="detail-value">
              <span className="detail-badge-classroom">{session.classroom_id}</span>
            </div>
          </div>

          {/* Start Time */}
          <div className="session-detail-item">
            <span className="detail-label">Start Time</span>
            <div className="detail-value">
              <span>{formatSessionDateTime(session.start_time)}</span>
            </div>
          </div>

          {/* End Time */}
          <div className="session-detail-item">
            <span className="detail-label">End Time</span>
            <div className="detail-value">
              <span>{formatSessionDateTime(session.end_time)}</span>
            </div>
          </div>

          {/* Required Presence */}
          <div className="session-detail-item">
            <span className="detail-label">Required Presence</span>
            <div className="detail-value">
              <span className="detail-value-highlight">
                {session.required_presence_percentage}%
              </span>
            </div>
          </div>
        </div>

        {/* Session ID Row */}
        <div className="session-detail-item" style={{ paddingTop: "0.5rem" }}>
          <span className="detail-label">Session ID</span>
          <div className="session-id-container">
            <code className="session-id-code">{session.session_id}</code>
            <button
              type="button"
              className="btn-copy-id"
              onClick={() => handleCopyId(session.session_id)}
              title="Copy Session ID"
            >
              <svg width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 01-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 011.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 00-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 01-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 00-3.375-3.375h-1.5a1.125 1.125 0 01-1.125-1.125v-1.5a3.375 3.375 0 00-3.375-3.375H9.75"
                />
              </svg>
              <span>{copied ? "Copied!" : "Copy ID"}</span>
            </button>
          </div>
        </div>
      </article>

      {/* Always-On Optical Video Feed (Laptop Webcam / Simulator) */}
      <AlwaysOnVideoFeed
        sessionId={session.session_id}
        classroomId={session.classroom_id}
        rosterIdentities={rosterIdentities}
        onEventDispatched={() => setAttendanceRefreshKey((k) => k + 1)}
      />

      {/* Real-time Attendance Ledger & Verification */}
      <SessionAttendance
        key={attendanceRefreshKey}
        sessionId={session.session_id}
        requiredPercentage={session.required_presence_percentage}
        onFinalize={handleEndSession}
      />

      {/* Session Audit Trail & Compliance Ledger */}
      <AuditLogs
        sessionId={session.session_id}
        title="Session Audit Trail"
        subtitle="Immutable, append-only history of session creation, finalizations, and manual corrections."
      />
    </div>
  );
};
