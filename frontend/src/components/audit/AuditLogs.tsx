import { formatDate, formatTime } from "../../utils/dates.ts";
import React, { useEffect, useState } from "react";
import { api } from "../../services";
import type { AuditAction, AuditEventResponse, AuditResourceType } from "../../types";
import "./audit-logs.css";

export interface AuditLogsProps {
  sessionId?: string;
  resourceType?: string;
  resourceId?: string;
  title?: string;
  subtitle?: string;
  showRefresh?: boolean;
}

function formatAuditTimestamp(isoStr: string): {
  dateStr: string;
  timeStr: string;
} {
  return { dateStr: formatDate(isoStr), timeStr: formatTime(isoStr) };
}

function getActionConfig(action: AuditAction): {
  label: string;
  className: string;
} {
  switch (action) {
    case "SESSION_CREATED":
      return { label: "Session Created", className: "action-session-created" };
    case "ROSTER_UPDATED":
      return { label: "Roster Updated", className: "action-roster-updated" };
    case "ATTENDANCE_FINALIZED":
      return { label: "Attendance Finalized", className: "action-attendance-finalized" };
    case "ATTENDANCE_CORRECTED":
      return { label: "Attendance Corrected", className: "action-attendance-corrected" };
    case "USER_REGISTERED":
      return { label: "User Registered", className: "action-user-registered" };
    case "USER_LOGIN":
      return { label: "User Login", className: "action-user-login" };
    default:
      return { label: action, className: "action-default" };
  }
}

function formatResourceType(type: AuditResourceType | string): string {
  switch (type) {
    case "SESSION":
      return "Session";
    case "SESSION_ROSTER":
      return "Session Roster";
    case "ATTENDANCE":
      return "Attendance";
    case "USER":
      return "User";
    case "STUDENT_PROFILE":
      return "Student Profile";
    case "SYSTEM":
      return "System";
    default:
      return type;
  }
}

function formatSecondsToMinutes(seconds: unknown): string {
  if (typeof seconds === "number") {
    const mins = Math.round(seconds / 60);
    return `${mins} min`;
  }
  if (typeof seconds === "string") {
    const parsed = parseFloat(seconds);
    if (!isNaN(parsed)) {
      return `${Math.round(parsed / 60)} min`;
    }
  }
  return String(seconds ?? "0 min");
}

export const AuditLogs: React.FC<AuditLogsProps> = ({
  sessionId,
  resourceType,
  resourceId,
  title = "Audit Trail & Compliance Ledger",
  subtitle = "Immutable, append-only history of administrative actions and attendance operations.",
  showRefresh = true,
}) => {
  const [events, setEvents] = useState<AuditEventResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [sortOrder, setSortOrder] = useState<"desc" | "asc">("desc");
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const fetchAuditLogs = async (refreshing = false) => {
    if (refreshing) {
      setIsRefreshing(true);
    } else {
      setLoading(true);
    }
    setErrorMessage(null);

    try {
      const params: { resource_type?: string; resource_id?: string } = {};
      if (sessionId) {
        params.resource_type = "SESSION";
        params.resource_id = sessionId;
      } else {
        if (resourceType) params.resource_type = resourceType;
        if (resourceId) params.resource_id = resourceId;
      }

      const data = await api.getAuditEvents(params);
      setEvents(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(
        msg || "Unable to load audit logs. Please verify your connection."
      );
    } finally {
      setLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    fetchAuditLogs();
  }, [sessionId, resourceType, resourceId]);

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleCopyId = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(id);
        setCopiedId(id);
        setTimeout(() => setCopiedId(null), 2000);
      }
    } catch {
      // Ignore copy error
    }
  };

  const sortedEvents = [...events].sort((a, b) => {
    const timeA = new Date(a.timestamp).getTime();
    const timeB = new Date(b.timestamp).getTime();
    return sortOrder === "desc" ? timeB - timeA : timeA - timeB;
  });

  return (
    <article className="audit-logs-card" aria-label="System Audit Logs">
      {/* Component Header */}
      <header className="audit-header">
        <div className="audit-header-top">
          <div className="audit-title-group">
            <div className="audit-header-icon" aria-hidden="true">
              <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"
                />
              </svg>
            </div>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <h3 className="audit-title">{title}</h3>
                {!loading && !errorMessage && (
                  <span className="audit-count-badge">
                    {events.length} {events.length === 1 ? "event" : "events"}
                  </span>
                )}
              </div>
              <p className="audit-subtitle">{subtitle}</p>
            </div>
          </div>

          <div className="audit-actions">
            {/* Sort Toggle */}
            <button
              type="button"
              className="audit-btn"
              onClick={() => setSortOrder((prev) => (prev === "desc" ? "asc" : "desc"))}
              title={`Currently showing ${sortOrder === "desc" ? "Newest First" : "Oldest First"}`}
            >
              <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                {sortOrder === "desc" ? (
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 4.5h14.25M3 9h9.75M3 13.5h5.25m5.25-.75L17.25 9m0 0L21 12.75M17.25 9v10.5" />
                ) : (
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 4.5h14.25M3 9h9.75M3 13.5h9.75m4.5-4.5v10.5m0 0L17.25 15m3.75 4.5L24 15" />
                )}
              </svg>
              <span>{sortOrder === "desc" ? "Newest First" : "Oldest First"}</span>
            </button>

            {/* Refresh Button */}
            {showRefresh && (
              <button
                type="button"
                className="audit-btn"
                onClick={() => fetchAuditLogs(true)}
                disabled={loading || isRefreshing}
                title="Refresh audit events"
              >
                <svg
                  className={isRefreshing ? "spin-icon" : ""}
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
                <span>{isRefreshing ? "Refreshing..." : "Refresh"}</span>
              </button>
            )}
          </div>
        </div>
      </header>

      {/* State 1: Loading */}
      {loading && !isRefreshing && (
        <div className="audit-loading-container" aria-live="polite" aria-busy="true">
          <div className="audit-loading-spinner" />
          <span>Loading audit history...</span>
        </div>
      )}

      {/* State 2: Error */}
      {!loading && errorMessage && (
        <div className="audit-error-container" role="alert">
          <svg className="audit-error-icon" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"
            />
          </svg>
          <div className="audit-error-content">
            <h4 className="audit-error-title">Unable to Load Audit Trail</h4>
            <p className="audit-error-msg">{errorMessage}</p>
            <button
              type="button"
              className="audit-retry-btn"
              onClick={() => fetchAuditLogs()}
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {/* State 3: Empty */}
      {!loading && !errorMessage && sortedEvents.length === 0 && (
        <div className="audit-empty-container">
          <div className="audit-empty-icon" aria-hidden="true">
            <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
              />
            </svg>
          </div>
          <h4 className="audit-empty-title">No Audit Events Recorded Yet</h4>
          <p className="audit-empty-desc">
            Administrative actions such as session creation, roster enrollment, attendance finalization, and manual corrections will be recorded here automatically.
          </p>
        </div>
      )}

      {/* State 4: Events List / Table */}
      {!loading && !errorMessage && sortedEvents.length > 0 && (
        <div className="audit-table-wrapper">
          <table className="audit-table">
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Action</th>
                <th scope="col">Resource</th>
                <th scope="col">Actor</th>
                <th scope="col" style={{ textAlign: "right" }}>Details</th>
              </tr>
            </thead>
            <tbody>
              {sortedEvents.map((event) => {
                const isExpanded = expandedIds.has(event.audit_id);
                const { dateStr, timeStr } = formatAuditTimestamp(event.timestamp);
                const actionConfig = getActionConfig(event.action);

                return (
                  <React.Fragment key={event.audit_id}>
                    <tr className={`audit-row ${isExpanded ? "audit-row-expanded" : ""}`}>
                      {/* Timestamp */}
                      <td>
                        <div className="audit-timestamp">
                          <span className="audit-time-main">{timeStr}</span>
                          <span className="audit-time-sub">{dateStr}</span>
                        </div>
                      </td>

                      {/* Action */}
                      <td>
                        <span className={`audit-action-badge ${actionConfig.className}`}>
                          {actionConfig.label}
                        </span>
                      </td>

                      {/* Resource */}
                      <td>
                        <span className="audit-resource-badge">
                          {formatResourceType(event.resource_type)}
                        </span>
                      </td>

                      {/* Actor */}
                      <td>
                        <span className="audit-role-badge">
                          {event.actor_role}
                        </span>
                      </td>

                      {/* View Details Toggle */}
                      <td style={{ textAlign: "right" }}>
                        <button
                          type="button"
                          className={`audit-details-btn ${isExpanded ? "active" : ""}`}
                          onClick={() => toggleExpand(event.audit_id)}
                          aria-expanded={isExpanded}
                          aria-label={`${isExpanded ? "Hide" : "View"} details for ${actionConfig.label}`}
                        >
                          <span>{isExpanded ? "Hide details" : "View details"}</span>
                          <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                          </svg>
                        </button>
                      </td>
                    </tr>

                    {/* Expandable Detail Panel */}
                    {isExpanded && (
                      <tr>
                        <td colSpan={5} className="audit-expanded-cell">
                          <div className="audit-detail-panel">
                            {/* Attendance Correction Metadata */}
                            {event.action === "ATTENDANCE_CORRECTED" && (
                              <>
                                <div className="audit-detail-grid">
                                  {Boolean(event.metadata.identity) && (
                                    <div className="audit-detail-item">
                                      <span className="audit-detail-label">Student</span>
                                      <span className="audit-detail-value">
                                        <code>{String(event.metadata.identity)}</code>
                                      </span>
                                    </div>
                                  )}
                                  {Boolean(event.metadata.previous_status) && (
                                    <div className="audit-detail-item">
                                      <span className="audit-detail-label">Previous Status</span>
                                      <span className={`status-pill ${String(event.metadata.previous_status).toLowerCase()}`}>
                                        {String(event.metadata.previous_status)}
                                      </span>
                                    </div>
                                  )}
                                  {Boolean(event.metadata.new_status) && (
                                    <div className="audit-detail-item">
                                      <span className="audit-detail-label">New Status</span>
                                      <span className={`status-pill ${String(event.metadata.new_status).toLowerCase()}`}>
                                        {String(event.metadata.new_status)}
                                      </span>
                                    </div>
                                  )}
                                  <div className="audit-detail-item">
                                    <span className="audit-detail-label">Presence Adjustment</span>
                                    <span className="audit-detail-value">
                                      {formatSecondsToMinutes(event.metadata.previous_presence_seconds)} → {formatSecondsToMinutes(event.metadata.new_presence_seconds)}
                                    </span>
                                  </div>
                                </div>

                                {Boolean(event.metadata.reason) && (
                                  <div className="audit-reason-box">
                                    <strong>Justification:</strong> {String(event.metadata.reason)}
                                  </div>
                                )}
                              </>
                            )}

                            {/* Attendance Finalized Metadata */}
                            {event.action === "ATTENDANCE_FINALIZED" && (
                              <div className="audit-detail-grid">
                                <div className="audit-detail-item">
                                  <span className="audit-detail-label">Records Finalized</span>
                                  <span className="audit-detail-value">
                                    {String(event.metadata.attendance_record_count ?? "0")} students
                                  </span>
                                </div>
                                <div className="audit-detail-item">
                                  <span className="audit-detail-label">Required Threshold</span>
                                  <span className="audit-detail-value">
                                    {String(event.metadata.required_presence_percentage ?? "0")}%
                                  </span>
                                </div>
                              </div>
                            )}

                            {/* Session Created Metadata */}
                            {event.action === "SESSION_CREATED" && (
                              <div className="audit-detail-grid">
                                {Boolean(event.metadata.course_name) && (
                                  <div className="audit-detail-item">
                                    <span className="audit-detail-label">Course</span>
                                    <span className="audit-detail-value">
                                      {String(event.metadata.course_name)}
                                    </span>
                                  </div>
                                )}
                                {Boolean(event.metadata.required_presence_percentage) && (
                                  <div className="audit-detail-item">
                                    <span className="audit-detail-label">Required Presence</span>
                                    <span className="audit-detail-value">
                                      {String(event.metadata.required_presence_percentage)}%
                                    </span>
                                  </div>
                                )}
                              </div>
                            )}

                            {/* Roster Updated Metadata */}
                            {event.action === "ROSTER_UPDATED" && (
                              <div className="audit-detail-grid">
                                <div className="audit-detail-item">
                                  <span className="audit-detail-label">Enrolled Students</span>
                                  <span className="audit-detail-value">
                                    {String(event.metadata.student_count ?? "0")}
                                  </span>
                                </div>
                              </div>
                            )}

                            {/* User Registered / Login */}
                            {(event.action === "USER_REGISTERED" || event.action === "USER_LOGIN") && (
                              <div className="audit-detail-grid">
                                {Boolean(event.metadata.email) && (
                                  <div className="audit-detail-item">
                                    <span className="audit-detail-label">User Email</span>
                                    <span className="audit-detail-value">
                                      {String(event.metadata.email)}
                                    </span>
                                  </div>
                                )}
                              </div>
                            )}

                            {/* Audit Event ID & Security Metadata Footer */}
                            <div className="audit-id-footer">
                              <div>
                                <span>Audit ID: </span>
                                <code className="audit-id-code">{event.audit_id}</code>
                                <button
                                  type="button"
                                  className="audit-btn"
                                  style={{ padding: "0.15rem 0.45rem", fontSize: "0.7rem", marginLeft: "0.5rem" }}
                                  onClick={(e) => handleCopyId(event.audit_id, e)}
                                >
                                  {copiedId === event.audit_id ? "Copied!" : "Copy"}
                                </button>
                              </div>
                              <div>
                                <span>Resource ID: </span>
                                <code className="audit-id-code">{event.resource_id}</code>
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </article>
  );
};
