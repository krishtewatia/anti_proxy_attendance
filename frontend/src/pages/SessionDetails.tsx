import React, { useEffect, useState } from "react";
import { AuditLogs } from "../components/audit";
import { SessionAttendance, SessionRoster } from "../components/session";
import { api } from "../services";
import type { SessionResponse, UserResponse } from "../types";
import "./session-details.css";

interface SessionDetailsProps {
  sessionId: string;
  user: UserResponse;
  onNavigate: (path: string) => void;
}

function formatSessionDateTime(isoStr: string): string {
  try {
    const d = new Date(isoStr);
    const dateStr = d.toLocaleDateString("en-US", {
      day: "numeric",
      month: "short",
      year: "numeric",
      timeZone: "UTC",
    });
    const timeStr = d.toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
      timeZone: "UTC",
    });
    return `${dateStr} • ${timeStr}`;
  } catch {
    return isoStr;
  }
}

export const SessionDetails: React.FC<SessionDetailsProps> = ({
  sessionId,
  onNavigate,
}) => {
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorType, setErrorType] = useState<"NOT_FOUND" | "FORBIDDEN" | "GENERAL" | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const fetchSession = async () => {
    setLoading(true);
    setErrorType(null);
    setErrorMessage(null);

    try {
      const data = await api.getSession(sessionId);
      setSession(data);
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
        onClick={() => onNavigate("/dashboard/teacher")}
      >
        <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
        </svg>
        <span>Back to Sessions</span>
      </button>

      {/* Header */}
      <header className="session-details-header">
        <h1 className="session-details-title">Session Details</h1>
        <p className="session-details-subtitle">
          View scheduled parameters, verification criteria, and classroom allocation.
        </p>
      </header>

      {/* Main Info Card */}
      <article className="session-info-card">
        {/* Top: Course Name & Status */}
        <div className="session-info-top">
          <h2 className="session-course-title">{session.course_name}</h2>
          <span className={`status-badge status-${session.status.toLowerCase()}`}>
            <span className="status-dot" aria-hidden="true" />
            {session.status}
          </span>
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

      {/* Student Roster Management */}
      <SessionRoster sessionId={session.session_id} />

      {/* Attendance Verification & Records */}
      <SessionAttendance
        sessionId={session.session_id}
        requiredPercentage={session.required_presence_percentage}
      />

      {/* Session Audit Trail & Compliance Ledger */}
      <AuditLogs
        sessionId={session.session_id}
        title="Session Audit Trail"
        subtitle="Immutable, append-only history of session creation, roster changes, finalizations, and corrections."
      />
    </div>
  );
};
