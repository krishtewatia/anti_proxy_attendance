import React, { useMemo, useState } from "react";
import {
  SESSION_STATUS_FILTERS,
  matchesStatusFilter,
  paginate,
  sessionStatusBadgeClass,
  sessionStatusLabel,
  type SessionStatusFilter,
} from "../../utils/sessions.ts";
import { formatDate } from "../../utils/dates.ts";
import { Pagination } from "../common/Pagination";
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
        <p className="erp-page-subtitle">Every teacher's attendance sessions</p>
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
              <th>Date</th>
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
                <td colSpan={9} style={{ textAlign: "center", padding: "2rem", color: "var(--erp-text-muted)" }}>
                  No attendance sessions found.
                </td>
              </tr>
            ) : (
              current.items.map((sess) => {
                // Counted by the server; a dash when it sent nothing.
                const total = sess.total_students;
                const presentCount = sess.present_count;
                const absent = total != null && presentCount != null ? Math.max(0, total - presentCount) : null;
                return (
                  <tr key={sess.session_id}>
                    <td style={{ color: "var(--erp-text-muted)", whiteSpace: "nowrap" }}>{formatDate(sess.start_time)}</td>
                    <td style={{ fontWeight: 600 }}>{sess.course_name}</td>
                    <td>{sess.class_code || "—"}</td>
                    <td>{sess.teacher_name || "—"}</td>
                    <td>{total ?? "—"}</td>
                    {sess.was_taken === false ? (
                      <td colSpan={2} style={{ color: "var(--erp-text-muted)" }}>Not taken</td>
                    ) : (
                      <>
                        <td style={{ color: "#15803d", fontWeight: 600 }}>{presentCount ?? "—"}</td>
                        <td style={{ color: "#b91c1c", fontWeight: 600 }}>{absent ?? "—"}</td>
                      </>
                    )}
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

      <Pagination page={current} onChange={setPage} label="Session pages" />
    </div>
  );
};
