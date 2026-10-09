import React, { useEffect, useState } from "react";
import { api } from "../../services";
import { formatTurnout, type ReportsSummary } from "../../utils/reports.ts";
import { errorText } from "./adminShared.ts";

const tile: React.CSSProperties = {
  background: "var(--erp-surface-subtle)",
  padding: "1rem",
  borderRadius: "8px",
  border: "1px solid var(--erp-border)",
};
const tileLabel: React.CSSProperties = { fontSize: "0.75rem", fontWeight: 600, color: "var(--erp-text-muted)" };
const tileValue: React.CSSProperties = { fontSize: "1.75rem", fontWeight: 800, marginTop: "0.25rem" };
const tileNote: React.CSSProperties = { fontSize: "0.75rem", color: "var(--erp-text-muted)" };

// Every figure here is counted by the server from finalized sessions in which
// attendance was taken. Sessions closed without being taken are only listed.
export const ReportsTab: React.FC = () => {
  const [summary, setSummary] = useState<ReportsSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getAdminReportsSummary()
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errorText(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <div className="erp-page-header">
        <h1 className="erp-page-title">Attendance Reports</h1>
        <p className="erp-page-subtitle">Counted from finalized sessions in which attendance was taken</p>
      </div>

      {error && (
        <div className="alert-banner error" role="alert" style={{ marginBottom: "1.5rem" }}>
          <span>Could not load the report: {error}</span>
        </div>
      )}
      {!summary && !error && <div className="erp-empty-box">Loading report...</div>}

      {summary && summary.finalized_sessions === 0 && (
        <div className="erp-empty-box">
          No session with attendance has been finalized yet, so there is nothing to report. Figures
          appear here once a teacher takes attendance and finalizes the session.
          {(summary.sessions_not_taken ?? 0) > 0 &&
            ` ${summary.sessions_not_taken} session(s) were closed without attendance being taken; they are not counted.`}
        </div>
      )}

      {summary && summary.finalized_sessions > 0 && (
        <div className="erp-card" style={{ padding: "1.75rem", marginBottom: "1.5rem" }}>
          <h3 style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: "1.25rem", color: "var(--erp-navy)" }}>
            Attendance Summary
          </h3>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "1rem" }}>
            <div style={tile}>
              <div style={tileLabel}>Average Turnout</div>
              <div style={{ ...tileValue, color: "#15803d" }}>{formatTurnout(summary.average_turnout_percentage)}</div>
              <div style={tileNote}>
                {summary.attendance_records} attendance records in {summary.finalized_sessions} finalized sessions
                {(summary.sessions_not_taken ?? 0) > 0 && ` (${summary.sessions_not_taken} not taken, not counted)`}
              </div>
            </div>
            <div style={tile}>
              <div style={tileLabel}>Classes With Sessions</div>
              <div style={{ ...tileValue, color: "var(--erp-primary)" }}>{summary.classes_with_sessions}</div>
              <div style={tileNote}>Classes that have a finalized session</div>
            </div>
            <div style={tile}>
              <div style={tileLabel}>Students Below {summary.threshold_percentage}%</div>
              <div style={{ ...tileValue, color: "#b45309" }}>{summary.students_below_threshold}</div>
              <div style={tileNote}>Of {summary.students_counted} students with recorded attendance</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
