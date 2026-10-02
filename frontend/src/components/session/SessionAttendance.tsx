import React, { useCallback, useEffect, useState } from "react";
import { AttendanceCorrectionModal } from "../attendance/AttendanceCorrectionModal.tsx";
import { api } from "../../services";
import type { AttendanceSummaryItem } from "../../types";
import {
  formatPresenceDuration,
  formatPresencePercentage,
} from "./attendance-helpers.ts";
import "./session-attendance.css";

export interface SessionAttendanceProps {
  sessionId: string;
  requiredPercentage?: number;
}

export const SessionAttendance: React.FC<SessionAttendanceProps> = ({
  sessionId,
  requiredPercentage = 70.0,
}) => {
  const [records, setRecords] = useState<AttendanceSummaryItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [selectedAttendance, setSelectedAttendance] =
    useState<AttendanceSummaryItem | null>(null);

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
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        // If 404 is returned because attendance hasn't been generated yet
        if (msg.includes("404") || msg.toLowerCase().includes("not found")) {
          setRecords([]);
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

  useEffect(() => {
    fetchAttendance(false);
  }, [fetchAttendance]);

  // Derived statistics
  const totalStudents = records.length;
  const presentCount = records.filter(
    (r) => r.status?.toUpperCase() === "PRESENT",
  ).length;
  const absentCount = records.filter(
    (r) => r.status?.toUpperCase() === "ABSENT",
  ).length;

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
  if (loading && !refreshing) {
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
              <h2 className="attendance-title">Attendance & Verification</h2>
              <p className="attendance-subtitle">
                Automated CV presence calculation and final session attendance
                records.
              </p>
            </div>
          </div>

          <div className="attendance-header-actions">
            {lastUpdated && (
              <span className="attendance-last-updated" title="Last checked">
                Updated {formatUpdateTime(lastUpdated)}
              </span>
            )}
            <button
              type="button"
              className={`btn-attendance-refresh ${
                refreshing ? "is-spinning" : ""
              }`}
              onClick={() => fetchAttendance(true)}
              disabled={refreshing}
              title="Refresh attendance records"
              aria-label="Refresh attendance"
            >
              <svg
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
              <span>{refreshing ? "Refreshing..." : "Refresh"}</span>
            </button>
          </div>
        </div>
      </div>

      {/* State 2: Error State + Retry */}
      {error && (
        <div className="attendance-alert error" role="alert">
          <div className="attendance-alert-content">
            <svg
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"
              />
            </svg>
            <span>{error}</span>
          </div>
          <button
            type="button"
            className="btn-alert-retry"
            onClick={() => fetchAttendance(false)}
          >
            Retry
          </button>
        </div>
      )}

      {/* State 3: Empty State (No attendance generated yet) */}
      {!error && records.length === 0 && (
        <div className="attendance-empty-container">
          <div className="attendance-empty-icon" aria-hidden="true">
            <svg
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
          </div>
          <h3 className="attendance-empty-title">
            No Attendance Generated Yet
          </h3>
          <p className="attendance-empty-desc">
            Attendance records have not been calculated for this session. Records
            are computed by the backend Presence Engine when the session is
            finalized after CV event capture.
          </p>
          <div className="attendance-empty-tip">
            <span>ℹ Required presence threshold for this session:</span>
            <strong style={{ color: "#a5b4fc" }}>
              {effectiveThreshold}%
            </strong>
          </div>
          <button
            type="button"
            className="btn-empty-check"
            onClick={() => fetchAttendance(true)}
            disabled={refreshing}
          >
            <svg
              width="16"
              height="16"
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
            <span>{refreshing ? "Checking..." : "Check for Attendance"}</span>
          </button>
        </div>
      )}

      {/* State 4: Attendance Available */}
      {!error && records.length > 0 && (
        <>
          {/* Summary KPI Cards */}
          <div className="attendance-kpi-grid">
            {/* Total Students */}
            <div className="attendance-kpi-card">
              <span className="kpi-label">Total Evaluated</span>
              <div className="kpi-value-row">
                <span className="kpi-value">{totalStudents}</span>
              </div>
            </div>

            {/* Present Count */}
            <div className="attendance-kpi-card kpi-present">
              <span className="kpi-label">Present</span>
              <div className="kpi-value-row">
                <span className="kpi-indicator-dot present" aria-hidden="true" />
                <span className="kpi-value">{presentCount}</span>
              </div>
            </div>

            {/* Absent Count */}
            <div className="attendance-kpi-card kpi-absent">
              <span className="kpi-label">Absent</span>
              <div className="kpi-value-row">
                <span className="kpi-indicator-dot absent" aria-hidden="true" />
                <span className="kpi-value">{absentCount}</span>
              </div>
            </div>

            {/* Required Presence Threshold */}
            <div className="attendance-kpi-card kpi-threshold">
              <span className="kpi-label">Required Threshold</span>
              <div className="kpi-value-row">
                <span className="kpi-value">{effectiveThreshold}%</span>
              </div>
            </div>
          </div>

          {/* Attendance Table */}
          <div className="attendance-table-wrapper">
            <table className="attendance-table">
              <thead>
                <tr>
                  <th scope="col">Student</th>
                  <th scope="col">Presence</th>
                  <th scope="col">% (Progress)</th>
                  <th scope="col">Status</th>
                  <th scope="col">Review</th>
                </tr>
              </thead>
              <tbody>
                {records.map((record) => {
                  const isPresent =
                    record.status?.toUpperCase() === "PRESENT";
                  const pct = Math.max(0, Math.min(100, record.presence_percentage));
                  const threshold =
                    record.required_presence_percentage ?? effectiveThreshold;

                  return (
                    <tr key={record.attendance_id || record.identity}>
                      {/* Student */}
                      <td>
                        <div className="student-cell">
                          <code className="student-identity-code">
                            {record.identity}
                          </code>
                        </div>
                      </td>

                      {/* Presence Duration */}
                      <td>
                        <span className="presence-duration-text">
                          {formatPresenceDuration(
                            record.presence_duration_seconds,
                          )}
                        </span>
                      </td>

                      {/* Presence Percentage with Visual Progress Bar */}
                      <td>
                        <div className="presence-progress-cell">
                          <div className="presence-percentage-row">
                            <span className="presence-pct-value">
                              {formatPresencePercentage(
                                record.presence_percentage,
                              )}
                            </span>
                            <span className="presence-pct-threshold-hint">
                              req: {threshold}%
                            </span>
                          </div>
                          <div
                            className="presence-progress-track"
                            title={`${record.identity}: ${formatPresencePercentage(record.presence_percentage)} (Required: ${threshold}%)`}
                          >
                            <div
                              className={`presence-progress-fill ${
                                isPresent
                                  ? "status-present"
                                  : "status-absent"
                              }`}
                              style={{ width: `${pct}%` }}
                            />
                            {/* Visual Threshold Marker */}
                            {threshold > 0 && threshold <= 100 && (
                              <div
                                className="presence-threshold-marker"
                                style={{ left: `${threshold}%` }}
                                title={`Threshold: ${threshold}%`}
                              />
                            )}
                          </div>
                        </div>
                      </td>

                      {/* Status */}
                      <td>
                        <div className="status-cell-wrapper">
                          <span
                            className={`attendance-status-badge ${
                              isPresent ? "status-present" : "status-absent"
                            }`}
                          >
                            <span
                              className="attendance-status-icon"
                              aria-hidden="true"
                            >
                              {isPresent ? "✓" : "✕"}
                            </span>
                            <span>{record.status}</span>
                          </span>
                          {record.manually_corrected && (
                            <span
                              className="badge-manually-corrected"
                              title="Attendance was manually reviewed and corrected"
                            >
                              ✓ Manually corrected
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Review / Correct Action */}
                      <td>
                        <button
                          type="button"
                          className="btn-review-attendance"
                          onClick={() => setSelectedAttendance(record)}
                          title={`Review or correct attendance for ${record.identity}`}
                          aria-label={`Review or correct attendance for ${record.identity}`}
                        >
                          <svg
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            viewBox="0 0 24 24"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10"
                            />
                          </svg>
                          <span>Review / Correct</span>
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Attendance Correction Modal */}
      {selectedAttendance && (
        <AttendanceCorrectionModal
          isOpen={true}
          attendance={selectedAttendance}
          sessionId={sessionId}
          onClose={() => setSelectedAttendance(null)}
          onSuccess={async () => {
            await fetchAttendance(false);
            setSelectedAttendance(null);
          }}
        />
      )}
    </section>
  );
};
