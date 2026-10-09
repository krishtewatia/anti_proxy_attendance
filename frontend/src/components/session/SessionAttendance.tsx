import React, { useCallback, useEffect, useState } from "react";
import { AttendanceCorrectionModal } from "../attendance/AttendanceCorrectionModal.tsx";
import { api } from "../../services";
import type {
  AttendanceSummaryItem,
  SessionLiveSnapshotResponse,
  StudentLiveItem,
} from "../../types";
import {
  formatPresenceDuration,
  formatPresencePercentage,
} from "./attendance-helpers.ts";
import "./session-attendance.css";

export interface SessionAttendanceProps {
  sessionId: string;
  requiredPercentage?: number;
  onFinalize?: () => void;
  // An administrator reads a session; corrections are made by its teacher.
  readOnly?: boolean;
}

export const SessionAttendance: React.FC<SessionAttendanceProps> = ({
  sessionId,
  requiredPercentage = 70.0,
  onFinalize: _onFinalize,
  readOnly = false,
}) => {
  const [records, setRecords] = useState<AttendanceSummaryItem[]>([]);
  const [liveSnapshot, setLiveSnapshot] = useState<SessionLiveSnapshotResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [selectedAttendance, setSelectedAttendance] =
    useState<AttendanceSummaryItem | null>(null);
  const [markingAction, setMarkingAction] = useState<string | null>(null);

  const fetchAttendance = useCallback(
    async (isManualRefresh = false) => {
      if (isManualRefresh) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }
      setError(null);

      try {
        const response = await api.getAttendance(sessionId);
        const list = Array.isArray(response?.records) ? response.records : [];
        setRecords(list);
        setLastUpdated(new Date());

        // Also fetch live snapshot for real-time presence data
        try {
          const snap = await api.getSessionLiveSnapshot(sessionId);
          setLiveSnapshot(snap);
        } catch {
          // ignore if snapshot fails
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        // If 404 is returned because attendance hasn't been finalized yet
        if (msg.includes("404") || msg.toLowerCase().includes("not found")) {
          setRecords([]);
          try {
            const snap = await api.getSessionLiveSnapshot(sessionId);
            setLiveSnapshot(snap);
          } catch {
            // ignore
          }
          setLastUpdated(new Date());
        } else {
          setError(msg || "Failed to load attendance records.");
        }
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [sessionId],
  );

  // 1-Click Quick Override for Finalized Session
  const handleFinalizedQuickMark = async (record: AttendanceSummaryItem, newStatus: "PRESENT" | "ABSENT") => {
    if (!record.attendance_id) return;
    setMarkingAction(`${record.identity}_${newStatus}`);
    try {
      await api.correctAttendance(sessionId, record.attendance_id, {
        new_status: newStatus,
        new_presence_seconds: record.presence_duration_seconds,
        reason: `Teacher marked student ${newStatus.toLowerCase()} directly from attendance ledger`,
      });
      await fetchAttendance(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(`Failed to correct attendance: ${msg}`);
    } finally {
      setMarkingAction(null);
    }
  };

  useEffect(() => {
    fetchAttendance(false);
    // Auto-poll live snapshot every 2.5s for real-time presence updates
    const interval = setInterval(() => {
      fetchAttendance(true);
    }, 2500);
    return () => clearInterval(interval);
  }, [fetchAttendance]);

  // Derived statistics (Finalized or Live)
  const isFinalized = records.length > 0;
  const liveStudents: StudentLiveItem[] = liveSnapshot?.students || [];

  const totalStudents = isFinalized ? records.length : liveStudents.length;
  const presentCount = isFinalized
    ? records.filter((r) => r.status?.toUpperCase() === "PRESENT").length
    : liveStudents.filter((s) => s.state === "INSIDE").length;
  const absentCount = isFinalized
    ? records.filter((r) => r.status?.toUpperCase() === "ABSENT").length
    : liveStudents.filter((s) => s.state === "NOT_SEEN").length;
  const transitCount = !isFinalized
    ? liveStudents.filter((s) => s.state === "OUTSIDE").length
    : 0;

  const effectiveThreshold =
    records[0]?.required_presence_percentage ?? requiredPercentage;

  // Format updated timestamp
  const formatUpdateTime = (date: Date | null) => {
    if (!date) return "";
    return date.toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
      hour12: true,
    });
  };

  // State 1: Initial Loading Skeleton
  if (loading && !refreshing && !liveSnapshot) {
    return (
      <section
        className="session-attendance-card"
        aria-label="Attendance Verification"
        aria-busy="true"
      >
        <div className="attendance-header">
          <div className="attendance-skeleton-header" />
        </div>
        <div className="attendance-skeleton-grid">
          <div className="attendance-skeleton-kpi" />
          <div className="attendance-skeleton-kpi" />
          <div className="attendance-skeleton-kpi" />
          <div className="attendance-skeleton-kpi" />
        </div>
        <div className="attendance-skeleton-table" />
      </section>
    );
  }

  return (
    <section
      className="session-attendance-card"
      aria-label="Attendance Verification"
    >
      {/* Header & Controls */}
      <div className="attendance-header">
        <div className="attendance-header-top">
          <div className="attendance-title-group">
            <div className="attendance-header-icon" aria-hidden="true">
              <svg
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M9 12.75L11.25 15 15 9.75M21 12c0 1.268-.63 2.39-1.593 3.068a3.745 3.745 0 01-1.043 3.296 3.745 3.745 0 01-3.296 1.043A3.745 3.745 0 0112 21c-1.268 0-2.39-.63-3.068-1.593a3.746 3.746 0 01-3.296-1.043 3.745 3.745 0 01-1.043-3.296A3.745 3.745 0 013 12c0-1.268.63-2.39 1.593-3.068a3.745 3.745 0 011.043-3.296 3.746 3.746 0 013.296-1.043A3.746 3.746 0 0112 3c1.268 0 2.39.63 3.068 1.593a3.746 3.746 0 013.296 1.043 3.746 3.746 0 011.043 3.296A3.745 3.745 0 0121 12z"
                />
              </svg>
            </div>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <h2 className="attendance-title">Attendance & Verification Ledger</h2>
                <span className={`status-pill ${isFinalized ? "finalized" : "live"}`}>
                  {isFinalized ? "✓ FINALIZED" : "🟢 LIVE MONITORING"}
                </span>
              </div>
              <p className="attendance-subtitle">
                {isFinalized
                  ? "Session finalized. All presence intervals computed with full audit logging."
                  : "Continuous presence tracking. Recognitions from the camera mark attendance in real-time."}
              </p>
            </div>
          </div>

          <div className="attendance-header-actions">
            {lastUpdated && (
              <span className="attendance-last-updated" title="Last checked">
                Live Sync: {formatUpdateTime(lastUpdated)}
              </span>
            )}
            <button
              type="button"
              className={`btn-attendance-refresh ${refreshing ? "is-spinning" : ""}`}
              onClick={() => fetchAttendance(true)}
              disabled={refreshing}
              title="Refresh attendance records"
              aria-label="Refresh attendance"
            >
              <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99"
                />
              </svg>
              <span>{refreshing ? "Syncing..." : "Sync"}</span>
            </button>
          </div>
        </div>
      </div>

      {/* Error Alert */}
      {error && (
        <div className="attendance-alert error" role="alert">
          <div className="attendance-alert-content">
            <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
            </svg>
            <span>{error}</span>
          </div>
          <button type="button" className="btn-alert-retry" onClick={() => fetchAttendance(false)}>
            Retry
          </button>
        </div>
      )}

      {/* Summary KPI Cards */}
      <div className="attendance-kpi-grid">
        <div className="attendance-kpi-card">
          <span className="kpi-label">Rostered Students</span>
          <div className="kpi-value-row">
            <span className="kpi-value">{totalStudents}</span>
          </div>
        </div>

        <div className="attendance-kpi-card kpi-present">
          <span className="kpi-label">{isFinalized ? "Present" : "In Classroom (Present)"}</span>
          <div className="kpi-value-row">
            <span className="kpi-indicator-dot present" aria-hidden="true" />
            <span className="kpi-value">{presentCount}</span>
          </div>
        </div>

        <div className="attendance-kpi-card kpi-absent">
          <span className="kpi-label">{isFinalized ? "Absent" : "Not Seen / Outside"}</span>
          <div className="kpi-value-row">
            <span className="kpi-indicator-dot absent" aria-hidden="true" />
            <span className="kpi-value">{absentCount + transitCount}</span>
          </div>
        </div>

        <div className="attendance-kpi-card kpi-threshold">
          <span className="kpi-label">Required Threshold</span>
          <div className="kpi-value-row">
            <span className="kpi-value">{effectiveThreshold}%</span>
          </div>
        </div>
      </div>

      {/* Case A: Finalized Attendance Records */}
      {isFinalized && (
        <div className="attendance-table-wrapper">
          <table className="attendance-table">
            <thead>
              <tr>
                <th scope="col">Student</th>
                <th scope="col">Presence</th>
                <th scope="col">% Progress</th>
                <th scope="col">Final Status</th>
                <th scope="col">Manual Override</th>
              </tr>
            </thead>
            <tbody>
              {records.map((record) => {
                const isPresent = record.status?.toUpperCase() === "PRESENT";
                const pct = Math.max(0, Math.min(100, record.presence_percentage));

                return (
                  <tr key={record.attendance_id || record.identity}>
                    <td>
                      <div className="student-cell">
                        <code className="student-identity-code">{record.identity}</code>
                      </div>
                    </td>

                    <td>
                      <span className="presence-duration-text">
                        {formatPresenceDuration(record.presence_duration_seconds)}
                      </span>
                    </td>

                    <td>
                      <div className="presence-progress-cell">
                        <div className="presence-percentage-row">
                          <span className="presence-pct-value">
                            {formatPresencePercentage(record.presence_percentage)}
                          </span>
                        </div>
                        <div className="presence-progress-track">
                          <div
                            className={`presence-progress-bar ${pct >= effectiveThreshold ? "met-threshold" : "below-threshold"}`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    </td>

                    <td>
                      <div className="status-cell-wrapper">
                        <span className={`attendance-status-badge ${isPresent ? "status-present" : "status-absent"}`}>
                          <span className="attendance-status-icon">{isPresent ? "✓" : "✗"}</span>
                          <span>{record.status}</span>
                        </span>
                        {record.manually_corrected && (
                          <span className="badge-manually-corrected" title="Corrected by teacher">
                            ✎ Corrected
                          </span>
                        )}
                      </div>
                    </td>

                    <td>
                      <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                        {readOnly ? null : !isPresent ? (
                          <button
                            type="button"
                            className="btn-mark-present-quick"
                            onClick={() => handleFinalizedQuickMark(record, "PRESENT")}
                            disabled={markingAction === `${record.identity}_PRESENT`}
                          >
                            {markingAction === `${record.identity}_PRESENT` ? "..." : "+ Mark Present"}
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="btn-mark-absent-quick"
                            onClick={() => handleFinalizedQuickMark(record, "ABSENT")}
                            disabled={markingAction === `${record.identity}_ABSENT`}
                          >
                            {markingAction === `${record.identity}_ABSENT` ? "..." : "− Mark Absent"}
                          </button>
                        )}
                        <button
                          type="button"
                          className="btn-review-attendance"
                          onClick={() => setSelectedAttendance(record)}
                          hidden={readOnly}
                        >
                          Details
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

      {/* Case B: Real-Time Live Presence Ledger (Active Session) */}
      {!isFinalized && liveStudents.length > 0 && (
        <div className="attendance-table-wrapper">
          <table className="attendance-table">
            <thead>
              <tr>
                <th scope="col">Student</th>
                <th scope="col">Real-Time Presence</th>
                <th scope="col">% Progress</th>
                <th scope="col">Live State</th>
              </tr>
            </thead>
            <tbody>
              {liveStudents.map((student) => {
                const isInside = student.state === "INSIDE";
                const isOutside = student.state === "OUTSIDE";
                const pct = Math.max(0, Math.min(100, student.presence_percentage || 0));

                return (
                  <tr key={student.identity}>
                    <td>
                      <div className="student-cell">
                        <code className="student-identity-code">{student.identity}</code>
                        {student.is_rostered && (
                          <span className="badge-rostered" title="Enrolled in this session">
                            Roster
                          </span>
                        )}
                      </div>
                    </td>

                    <td>
                      <span className="presence-duration-text">
                        {formatPresenceDuration(student.presence_duration_seconds || 0)}
                      </span>
                    </td>

                    <td>
                      <div className="presence-progress-cell">
                        <div className="presence-percentage-row">
                          <span className="presence-pct-value">
                            {pct.toFixed(1)}%
                          </span>
                        </div>
                        <div className="presence-progress-track">
                          <div
                            className={`presence-progress-bar ${pct >= effectiveThreshold ? "met-threshold" : "below-threshold"}`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    </td>

                    <td>
                      <span
                        className={`attendance-status-badge ${
                          isInside
                            ? "status-present"
                            : isOutside
                            ? "status-transit"
                            : "status-absent"
                        }`}
                      >
                        <span className="attendance-status-icon">
                          {isInside ? "🟢" : isOutside ? "🟡" : "⚪"}
                        </span>
                        <span>
                          {isInside
                            ? "IN ROOM"
                            : isOutside
                            ? "EXITED"
                            : "NOT SEEN"}
                        </span>
                      </span>
                    </td>

                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Case C: No roster enrolled yet */}
      {!isFinalized && liveStudents.length === 0 && (
        <div className="attendance-empty-container">
          <h3 className="attendance-empty-title">Waiting for Student Detections</h3>
          <p className="attendance-empty-desc">
            Students appear in this ledger as the camera recognizes them.
          </p>
        </div>
      )}

      {/* Attendance Correction Modal */}
      {selectedAttendance && (
        <AttendanceCorrectionModal
          isOpen={true}
          sessionId={sessionId}
          attendance={selectedAttendance}
          onClose={() => setSelectedAttendance(null)}
          onSuccess={() => {
            setSelectedAttendance(null);
            fetchAttendance(true);
          }}
        />
      )}
    </section>
  );
};
