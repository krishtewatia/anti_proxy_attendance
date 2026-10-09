import React, { useCallback, useEffect, useState } from "react";
import { api } from "../../services";
import type { AttendanceSummaryItem } from "../../types";
import { AttendanceCorrectionModal } from "../attendance";

export interface SessionAttendanceProps {
  sessionId: string;
  // Who is looking. A teacher can flip a record with one click; an
  // administrator corrects through the form, which requires a reason.
  viewerRole?: "TEACHER" | "ADMIN";
}

const smallButton: React.CSSProperties = { padding: "0.25rem 0.6rem", fontSize: "0.75rem" };

// The attendance register of one session: who was present, who was absent,
// and the way to correct a record.
export const SessionAttendance: React.FC<SessionAttendanceProps> = ({ sessionId, viewerRole = "TEACHER" }) => {
  const [records, setRecords] = useState<AttendanceSummaryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [selected, setSelected] = useState<AttendanceSummaryItem | null>(null);
  // False when the session was never taken: nobody in it is absent.
  const [wasTaken, setWasTaken] = useState(true);

  const load = useCallback(async () => {
    try {
      const data = await api.getAttendance(sessionId);
      setRecords(data.records);
      setWasTaken(data.was_taken !== false);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load attendance records.");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = async (record: AttendanceSummaryItem) => {
    const next = record.status === "PRESENT" ? "ABSENT" : "PRESENT";
    setBusyId(record.attendance_id);
    try {
      await api.updateAttendanceStatus(sessionId, record.attendance_id, next);
      await load();
    } catch (err: unknown) {
      setError(`Failed to update ${record.student_name || record.identity}: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusyId(null);
    }
  };

  const present = records.filter((r) => r.status === "PRESENT").length;

  return (
    <section className="erp-section" style={{ marginBottom: "2rem" }} aria-label="Attendance register">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
        <h2 className="erp-section-title" style={{ marginBottom: 0 }}>Attendance Register</h2>
        <button type="button" className="erp-btn erp-btn-secondary" style={smallButton} onClick={() => void load()}>
          ↻ Refresh
        </button>
      </div>

      {error && (
        <div className="alert-banner error" role="alert" style={{ margin: "1rem 0" }}>
          <span>{error}</span>
        </div>
      )}

      <div className="erp-metrics-grid" style={{ marginTop: "1rem" }}>
        <div className="erp-metric-card">
          <span className="erp-metric-label">Students</span>
          <span className="erp-metric-value">{records.length}</span>
          <span className="erp-metric-subtext">On this session's roster</span>
        </div>
        <div className="erp-metric-card">
          <span className="erp-metric-label">Present</span>
          <span className="erp-metric-value" style={{ color: "var(--erp-present-text)" }}>{wasTaken ? present : "—"}</span>
          <span className="erp-metric-subtext">{wasTaken ? "Marked by the camera or corrected" : "Attendance was not taken"}</span>
        </div>
        <div className="erp-metric-card">
          <span className="erp-metric-label">Absent</span>
          <span className="erp-metric-value" style={{ color: "var(--erp-absent-text)" }}>{wasTaken ? records.length - present : "—"}</span>
          <span className="erp-metric-subtext">{wasTaken ? "Not marked present" : "Not counted as absences"}</span>
        </div>
      </div>

      {!wasTaken && records.length > 0 && (
        <p style={{ fontSize: "0.8125rem", color: "var(--erp-text-muted)", margin: "0 0 0.75rem" }}>
          Attendance was not taken in this session, so it does not count towards anyone's attendance.
          Correcting a record makes it count.
        </p>
      )}

      {viewerRole === "ADMIN" && records.length > 0 && (
        <p style={{ fontSize: "0.8125rem", color: "var(--erp-text-muted)", margin: "0 0 0.75rem" }}>
          As an administrator you can correct a record; a reason is required and the correction is
          recorded in the audit trail as yours.
        </p>
      )}

      {records.length === 0 ? (
        <div className="erp-empty-box">
          {loading ? "Loading attendance..." : "No students are on this session's roster."}
        </div>
      ) : (
        <div className="erp-table-container">
          <table className="erp-table">
            <thead>
              <tr>
                <th>Student</th>
                <th>Roll No</th>
                <th>Student ID</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {records.map((record) => {
                const isPresent = record.status === "PRESENT";
                return (
                  <tr key={record.attendance_id}>
                    <td style={{ fontWeight: 600 }}>{record.student_name || record.identity}</td>
                    <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.8125rem" }}>{record.roll_number || "—"}</td>
                    <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.8125rem", color: "var(--erp-primary)" }}>
                      {record.student_id || "—"}
                    </td>
                    <td>
                      <span className={`status-badge ${!wasTaken ? "completed" : isPresent ? "present" : "absent"}`}>
                        {!wasTaken ? "Not taken" : isPresent ? "Present" : "Absent"}
                      </span>
                      {record.manually_corrected && (
                        <span style={{ marginLeft: "0.5rem", fontSize: "0.75rem", color: "var(--erp-warning-text)" }}>
                          Corrected
                        </span>
                      )}
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                        {viewerRole === "TEACHER" && (
                          <button
                            type="button"
                            className="erp-btn erp-btn-secondary"
                            style={smallButton}
                            disabled={busyId === record.attendance_id}
                            onClick={() => void toggle(record)}
                          >
                            {busyId === record.attendance_id ? "..." : isPresent ? "Mark Absent" : "Mark Present"}
                          </button>
                        )}
                        <button
                          type="button"
                          className="erp-btn erp-btn-secondary"
                          style={smallButton}
                          onClick={() => setSelected(record)}
                        >
                          {viewerRole === "ADMIN" ? "Correct / History" : "Correct with reason"}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <AttendanceCorrectionModal
          isOpen={true}
          sessionId={sessionId}
          attendance={selected}
          onClose={() => setSelected(null)}
          onSuccess={() => {
            setSelected(null);
            void load();
          }}
        />
      )}
    </section>
  );
};
