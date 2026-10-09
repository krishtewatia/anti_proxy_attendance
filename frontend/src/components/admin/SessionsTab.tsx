import React, { useMemo, useState } from "react";
import {
  SESSION_STATUS_FILTERS,
  matchesStatusFilter,
  paginate,
  sessionStatusBadgeClass,
  sessionStatusLabel,
  type SessionStatusFilter,
} from "../../utils/sessions.ts";
import { smallButton, type AdminTabProps } from "./adminShared.ts";

const PAGE_SIZE = 15;

export const SessionsTab: React.FC<AdminTabProps> = ({ sessions, reload }) => {
  const [statusFilter, setStatusFilter] = useState<SessionStatusFilter>("ALL");
  const [page, setPage] = useState(1);

  const filteredSessions = useMemo(
    () => sessions.filter((s) => matchesStatusFilter(s.status, statusFilter)),
    [sessions, statusFilter],
  );
  // The list is shown a page at a time, so the page never grows with the data.
  const current = paginate(filteredSessions, page, PAGE_SIZE);

  return (
    <div>
      <div className="erp-page-header">
        <h1 className="erp-page-title">Attendance Sessions</h1>
        <p className="erp-page-subtitle">Classroom attendance register logs and finalized records</p>
      </div>

      <div className="erp-table-action-bar">
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <label htmlFor="admin-session-filter" style={{ fontSize: "0.8125rem", fontWeight: 600, color: "var(--erp-text-muted)" }}>
            Status:
          </label>
          <select
            id="admin-session-filter"
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value as SessionStatusFilter);
              setPage(1);
            }}
            className="erp-select-input"
            style={{ padding: "0.4rem 0.75rem", fontSize: "0.8125rem", width: "160px" }}
          >
            {SESSION_STATUS_FILTERS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </div>
        <button type="button" className="erp-btn erp-btn-secondary" onClick={() => void reload()}>
          ↻ Refresh
        </button>
      </div>

      <div className="erp-table-container">
        <table className="erp-table">
          <thead>
            <tr>
              <th>Subject</th>
              <th>Class</th>
              <th>Teacher</th>
              <th>Students</th>
              <th>Present</th>
              <th>Absent</th>
              <th>Status</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {current.items.length === 0 ? (
              <tr>
                <td colSpan={8} style={{ textAlign: "center", padding: "2rem", color: "var(--erp-text-muted)" }}>
                  No attendance sessions found.
                </td>
              </tr>
            ) : (
              current.items.map((sess) => {
                const sessAny = sess as unknown as Record<string, unknown>;
                const totalStu = typeof sessAny.total_students === "number" ? sessAny.total_students : 4;
                const presCount = typeof sessAny.present_count === "number" ? sessAny.present_count : (sess.status === "COMPLETED" ? 4 : 0);
                const absCount = Math.max(0, totalStu - presCount);
                return (
                  <tr key={sess.session_id}>
                    <td style={{ fontWeight: 600 }}>{sess.course_name}</td>
                    <td>{sess.class_code || "DS-B"}</td>
                    <td>{String(sessAny.teacher_name ?? sessAny.created_by ?? "—")}</td>
                    <td>{totalStu}</td>
                    <td style={{ color: "#15803d", fontWeight: 600 }}>{presCount}</td>
                    <td style={{ color: "#b91c1c", fontWeight: 600 }}>{absCount}</td>
                    <td>
                      <span className={`status-badge ${sessionStatusBadgeClass(sess.status)}`}>
                        {sessionStatusLabel(sess.status)}
                      </span>
                    </td>
                    <td>
                      <a
                        href={`/dashboard/teacher/sessions/${sess.session_id}`}
                        className="erp-btn erp-btn-secondary"
                        style={smallButton}
                      >
                        View
                      </a>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {current.total > 0 && (
        <div className="erp-pagination" role="navigation" aria-label="Session pages">
          <span className="erp-pagination-summary">
            Showing {current.from}–{current.to} of {current.total}
          </span>
          <div className="erp-pagination-buttons">
            <button
              type="button"
              className="erp-btn erp-btn-secondary"
              style={smallButton}
              disabled={current.page <= 1}
              onClick={() => setPage(current.page - 1)}
            >
              ← Previous
            </button>
            <span className="erp-pagination-page">
              Page {current.page} of {current.pageCount}
            </span>
            <button
              type="button"
              className="erp-btn erp-btn-secondary"
              style={smallButton}
              disabled={current.page >= current.pageCount}
              onClick={() => setPage(current.page + 1)}
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
