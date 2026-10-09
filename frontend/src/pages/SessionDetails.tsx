import React, { useCallback, useEffect, useState } from "react";
import { AuditLogs } from "../components/audit";
import { AlwaysOnVideoFeed, SessionAttendance } from "../components/session";
import { api } from "../services";
import type { SessionResponse, UserResponse } from "../types";
import { formatDate, formatTime } from "../utils/dates.ts";
import { isSessionActive, isSessionCompleted, sessionStatusBadgeClass, sessionStatusLabel } from "../utils/sessions.ts";
// The page is built from the classes the dashboards already use.
import "./admin-dashboard.css";
import "./teacher-attendance-flow.css";

interface SessionDetailsProps {
  sessionId: string;
  user?: UserResponse;
  onNavigate: (path: string) => void;
}

const field: React.CSSProperties = { display: "flex", flexDirection: "column", gap: "0.2rem" };
const fieldLabel: React.CSSProperties = {
  fontSize: "0.75rem",
  fontWeight: 600,
  color: "var(--erp-text-muted)",
  textTransform: "uppercase",
  letterSpacing: "0.04em",
};
const fieldValue: React.CSSProperties = { fontSize: "0.9375rem", fontWeight: 600, color: "var(--erp-text-main)" };

// What the line under the title says, by status.
export function sessionPageSubtitle(status: string): string {
  if (isSessionCompleted(status)) return "Final attendance for this session, with its correction history.";
  if (isSessionActive(status)) return "Attendance is being taken now.";
  return "This session has not been started yet.";
}

export const SessionDetails: React.FC<SessionDetailsProps> = ({ sessionId, user, onNavigate }) => {
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [banner, setBanner] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [attendanceRefreshKey, setAttendanceRefreshKey] = useState(0);

  const isUserAdmin = user?.role === "ADMIN";
  const backPath = isUserAdmin ? "/dashboard/admin" : "/dashboard/teacher";

  const fetchSession = useCallback(async () => {
    setLoading(true);
    setErrorMessage(null);
    setNotFound(false);
    try {
      setSession(await api.getSession(sessionId));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(msg);
      setNotFound(msg.includes("404") || msg.toLowerCase().includes("not found"));
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void fetchSession();
  }, [fetchSession]);

  const handleEndSession = async () => {
    if (
      !window.confirm(
        "End this session and finalize its attendance now? Students not marked present are recorded as absent.",
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
      setAttendanceRefreshKey((k) => k + 1);
      setBanner({ type: "success", text: "Session finalized. Records can still be corrected below." });
      await fetchSession();
    } catch (err: unknown) {
      setBanner({ type: "error", text: `Failed to finalize the session: ${err instanceof Error ? err.message : String(err)}` });
    } finally {
      setActionLoading(false);
    }
  };

  const handleDeleteSession = async () => {
    if (!session) return;
    if (
      !window.confirm(
        `Delete the session "${session.course_name}"?\n\nIts roster and all its attendance records are deleted too. This cannot be undone.`,
      )
    ) {
      return;
    }
    setActionLoading(true);
    try {
      if (isUserAdmin) {
        await api.adminDeleteSession(sessionId);
      } else {
        await api.deleteSession(sessionId);
      }
      onNavigate(backPath);
    } catch (err: unknown) {
      setBanner({ type: "error", text: `Failed to delete the session: ${err instanceof Error ? err.message : String(err)}` });
      setActionLoading(false);
    }
  };

  const backButton = (
    <button
      type="button"
      className="erp-btn erp-btn-secondary"
      style={{ marginBottom: "1.25rem" }}
      onClick={() => onNavigate(backPath)}
    >
      ← Back to {isUserAdmin ? "Admin Dashboard" : "Dashboard"}
    </button>
  );

  if (loading && !session) {
    return (
      <div aria-live="polite">
        {backButton}
        <div className="erp-empty-box">Loading session...</div>
      </div>
    );
  }

  if (!session) {
    return (
      <div>
        {backButton}
        <div className="erp-card" style={{ padding: "2rem", textAlign: "center" }} role="alert">
          <h2 style={{ fontSize: "1.125rem", fontWeight: 700, color: "var(--erp-text-main)", marginBottom: "0.5rem" }}>
            {notFound ? "Session Not Found" : "Unable to Load Session"}
          </h2>
          <p style={{ color: "var(--erp-text-muted)", fontSize: "0.875rem", marginBottom: "1.25rem" }}>
            {notFound
              ? "This session may have been deleted."
              : errorMessage || "You do not have permission to view this session."}
          </p>
          {!notFound && (
            <button type="button" className="erp-btn erp-btn-secondary" onClick={() => void fetchSession()}>
              Retry
            </button>
          )}
        </div>
      </div>
    );
  }

  const completed = isSessionCompleted(session.status);

  return (
    <div>
      {backButton}

      <div className="erp-page-header">
        <h1 className="erp-page-title">{session.course_name}</h1>
        <p className="erp-page-subtitle">{sessionPageSubtitle(session.status)}</p>
      </div>

      {banner && (
        <div className={`alert-banner ${banner.type}`} role="status" style={{ marginBottom: "1.5rem" }}>
          <span>{banner.text}</span>
          <button
            type="button"
            onClick={() => setBanner(null)}
            aria-label="Dismiss"
            style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", fontWeight: 700 }}
          >
            ✕
          </button>
        </div>
      )}

      <div className="erp-card" style={{ padding: "1.5rem", marginBottom: "2rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "1rem", flexWrap: "wrap" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "1.25rem 2rem", flex: "1 1 420px" }}>
            <div style={field}>
              <span style={fieldLabel}>Status</span>
              <span>
                <span className={`status-badge ${sessionStatusBadgeClass(session.status)}`}>
                  {sessionStatusLabel(session.status)}
                </span>
              </span>
            </div>
            <div style={field}>
              <span style={fieldLabel}>Class</span>
              <span style={fieldValue}>{session.class_code || "—"}</span>
            </div>
            <div style={field}>
              <span style={fieldLabel}>Subject</span>
              <span style={fieldValue}>{session.subject || "—"}</span>
            </div>
            <div style={field}>
              <span style={fieldLabel}>Date</span>
              <span style={fieldValue}>{formatDate(session.start_time)}</span>
            </div>
            <div style={field}>
              <span style={fieldLabel}>Time</span>
              <span style={fieldValue}>
                {formatTime(session.start_time)} – {formatTime(session.end_time)}
              </span>
            </div>
          </div>

          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {!completed && (
              <button type="button" className="erp-btn erp-btn-primary" onClick={handleEndSession} disabled={actionLoading}>
                {actionLoading ? "Finalizing..." : "End Session & Finalize"}
              </button>
            )}
            <button
              type="button"
              className="erp-btn erp-btn-secondary"
              style={{ color: "var(--erp-absent-text)" }}
              onClick={handleDeleteSession}
              disabled={actionLoading}
            >
              Delete Session
            </button>
          </div>
        </div>
      </div>

      {/* The camera belongs to the teacher taking attendance. An administrator
          opens a session to read it, so their webcam is never switched on. */}
      {!isUserAdmin && isSessionActive(session.status) && <AlwaysOnVideoFeed sessionId={session.session_id} />}

      <SessionAttendance
        key={attendanceRefreshKey}
        sessionId={session.session_id}
        viewerRole={isUserAdmin ? "ADMIN" : "TEACHER"}
      />

      <AuditLogs
        sessionId={session.session_id}
        title="Session Audit Trail"
        subtitle="Every change to this session and its attendance, in order."
      />
    </div>
  );
};
