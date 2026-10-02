import React, { useCallback, useEffect, useState } from "react";
import {
  formatCorrectionTimestamp,
  formatPresenceDuration,
} from "../session/attendance-helpers.ts";
import { api } from "../../services";
import type {
  AttendanceCorrectionResponse,
  AttendanceStatus,
  AttendanceSummaryItem,
} from "../../types";
import {
  type AttendanceCorrectionValidationErrors,
  validateAttendanceCorrectionForm,
} from "./validation.ts";
import "./attendance-correction-modal.css";

export interface AttendanceCorrectionModalProps {
  isOpen: boolean;
  attendance: AttendanceSummaryItem;
  sessionId: string;
  onClose: () => void;
  onSuccess: (correction: AttendanceCorrectionResponse) => void;
}

export const AttendanceCorrectionModal: React.FC<
  AttendanceCorrectionModalProps
> = ({ isOpen, attendance, sessionId, onClose, onSuccess }) => {
  const currentStatus: AttendanceStatus =
    attendance.status?.toUpperCase() === "PRESENT" ? "PRESENT" : "ABSENT";

  const [newStatus, setNewStatus] = useState<AttendanceStatus>(currentStatus);
  const [newPresenceSeconds, setNewPresenceSeconds] = useState<number>(
    attendance.presence_duration_seconds ?? 0,
  );
  const [reason, setReason] = useState<string>("");
  const [saving, setSaving] = useState<boolean>(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] =
    useState<AttendanceCorrectionValidationErrors>({});

  // History state
  const [history, setHistory] = useState<AttendanceCorrectionResponse[]>([]);
  const [historyLoading, setHistoryLoading] = useState<boolean>(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const loadHistory = useCallback(async () => {
    if (!sessionId || !attendance?.attendance_id) return;
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const data = await api.getAttendanceCorrections(
        sessionId,
        attendance.attendance_id,
      );
      setHistory(data);
    } catch (err: unknown) {
      const raw = err instanceof Error ? err.message : String(err);
      let friendly = "Failed to load correction history. Please retry.";
      if (raw.includes("403") || raw.toLowerCase().includes("forbidden") || raw.toLowerCase().includes("own")) {
        friendly = "Access denied: You do not own this session.";
      } else if (raw.includes("404")) {
        friendly = "Attendance record or session not found.";
      }
      setHistoryError(friendly);
    } finally {
      setHistoryLoading(false);
    }
  }, [sessionId, attendance?.attendance_id]);

  // Reset form and fetch history when opening modal
  useEffect(() => {
    if (isOpen) {
      setNewStatus(
        attendance.status?.toUpperCase() === "PRESENT" ? "PRESENT" : "ABSENT",
      );
      setNewPresenceSeconds(attendance.presence_duration_seconds ?? 0);
      setReason("");
      setApiError(null);
      setFieldErrors({});
      setSaving(false);
      loadHistory();
    }
  }, [
    isOpen,
    attendance.status,
    attendance.presence_duration_seconds,
    loadHistory,
  ]);

  // Handle ESC key to dismiss modal
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !saving) {
        onClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, saving, onClose]);

  if (!isOpen) return null;

  const handleBackdropClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget && !saving) {
      onClose();
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (saving) return;

    const validation = validateAttendanceCorrectionForm({
      newStatus,
      newPresenceSeconds,
      reason,
    });

    if (!validation.isValid || !validation.sanitizedPayload) {
      setFieldErrors(validation.errors);
      return;
    }

    setFieldErrors({});
    setSaving(true);
    setApiError(null);

    try {
      const response = await api.correctAttendance(
        sessionId,
        attendance.attendance_id,
        validation.sanitizedPayload,
      );

      // Refresh history immediately so the audit trail shows the latest record
      await loadHistory();
      onSuccess(response);
      onClose();
    } catch (err: unknown) {
      const rawMsg = err instanceof Error ? err.message : String(err);

      // Map raw API exceptions to human-friendly messages
      let friendlyMsg = "Failed to submit attendance correction. Please try again.";
      if (rawMsg.includes("401") || rawMsg.toLowerCase().includes("unauthorized")) {
        friendlyMsg = "Your session has expired. Please log in again.";
      } else if (
        rawMsg.includes("403") ||
        rawMsg.toLowerCase().includes("forbidden") ||
        rawMsg.toLowerCase().includes("own")
      ) {
        friendlyMsg = "Access denied: You do not have permission to modify this session.";
      } else if (rawMsg.includes("404") || rawMsg.toLowerCase().includes("not found")) {
        friendlyMsg = "Attendance record or session no longer exists.";
      } else if (rawMsg.includes("422")) {
        friendlyMsg = "Invalid submission parameters. Please verify input fields.";
      } else if (rawMsg.includes("500") || rawMsg.toLowerCase().includes("server")) {
        friendlyMsg = "Server error occurred while saving audit correction. Please try again later.";
      } else if (rawMsg) {
        friendlyMsg = rawMsg;
      }

      setApiError(friendlyMsg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="modal-backdrop"
      onClick={handleBackdropClick}
      role="dialog"
      aria-modal="true"
      aria-labelledby="correction-modal-title"
    >
      <div className="correction-modal-card">
        {/* Header */}
        <div className="correction-modal-header">
          <div className="correction-modal-title-group">
            <div className="correction-modal-icon" aria-hidden="true">
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
            </div>
            <div>
              <h2 id="correction-modal-title" className="correction-modal-title">
                Review Attendance
              </h2>
              <span className="correction-modal-subtitle">
                Audit Trail & Manual Correction
              </span>
            </div>
          </div>

          <button
            type="button"
            className="correction-modal-close-btn"
            onClick={onClose}
            disabled={saving}
            aria-label="Close modal"
          >
            ✕
          </button>
        </div>

        {/* Modal Split Content: Left = Current State & Form, Right = Correction History */}
        <div className="correction-modal-grid">
          {/* Left Column: Form & Current State */}
          <div className="correction-grid-left">
            {/* Readonly Current Metadata Box */}
            <div className="correction-current-box">
              <div className="current-box-header">
                <span className="current-attendance-heading">Current Attendance</span>
                {attendance.manually_corrected ? (
                  <span className="current-corrected-badge">
                    ✓ Manually corrected
                  </span>
                ) : (
                  <span className="current-cv-badge">
                    Vision System Result
                  </span>
                )}
              </div>

              <div className="current-box-metrics">
                <div className="current-status-display">
                  <span
                    className={`status-indicator ${
                      currentStatus === "PRESENT" ? "is-present" : "is-absent"
                    }`}
                  >
                    {currentStatus === "PRESENT" ? "✓" : "✕"} {currentStatus}
                  </span>
                  <span className="current-sep">·</span>
                  <span className="current-percentage-text">
                    {attendance.presence_percentage.toFixed(2)}%
                  </span>
                  <span className="current-duration-text">
                    ({formatPresenceDuration(attendance.presence_duration_seconds)})
                  </span>
                </div>
              </div>

              <div className="current-student-identity">
                <span className="identity-label">Student:</span>
                <code className="current-identity-code">
                  {attendance.identity}
                </code>
              </div>
            </div>

            {/* Form Body */}
            <form onSubmit={handleSubmit} className="correction-modal-form" noValidate>
              <h3 className="section-form-title">Apply Correction</h3>

              {/* New Status Toggle */}
              <div className="correction-field-group">
                <label className="correction-field-label">
                  <span>
                    New Status <span className="correction-field-required">*</span>
                  </span>
                </label>
                <div className="correction-status-options" role="radiogroup">
                  <label
                    className={`status-toggle-label ${
                      newStatus === "PRESENT" ? "active status-present" : ""
                    }`}
                  >
                    <input
                      type="radio"
                      name="status"
                      value="PRESENT"
                      checked={newStatus === "PRESENT"}
                      onChange={() => {
                        setNewStatus("PRESENT");
                        if (fieldErrors.status) {
                          setFieldErrors((prev) => ({ ...prev, status: undefined }));
                        }
                      }}
                      className="status-toggle-radio"
                      disabled={saving}
                    />
                    <span>✓ PRESENT</span>
                  </label>

                  <label
                    className={`status-toggle-label ${
                      newStatus === "ABSENT" ? "active status-absent" : ""
                    }`}
                  >
                    <input
                      type="radio"
                      name="status"
                      value="ABSENT"
                      checked={newStatus === "ABSENT"}
                      onChange={() => {
                        setNewStatus("ABSENT");
                        if (fieldErrors.status) {
                          setFieldErrors((prev) => ({ ...prev, status: undefined }));
                        }
                      }}
                      className="status-toggle-radio"
                      disabled={saving}
                    />
                    <span>✕ ABSENT</span>
                  </label>
                </div>
                {fieldErrors.status && (
                  <span className="field-error-text" role="alert">
                    {fieldErrors.status}
                  </span>
                )}
              </div>

              {/* Presence Duration (seconds) */}
              <div className="correction-field-group">
                <div className="correction-field-label">
                  <span>
                    Presence Duration (seconds){" "}
                    <span className="correction-field-required">*</span>
                  </span>
                  <span className="field-helper-preview">
                    ≈ {formatPresenceDuration(newPresenceSeconds || 0)}
                  </span>
                </div>
                <input
                  type="number"
                  min="0"
                  step="1"
                  className={`correction-input ${
                    fieldErrors.presence ? "has-error" : ""
                  }`}
                  value={isNaN(newPresenceSeconds) ? "" : newPresenceSeconds}
                  onChange={(e) => {
                    const val = parseFloat(e.target.value);
                    setNewPresenceSeconds(isNaN(val) ? 0 : val);
                    if (fieldErrors.presence) {
                      setFieldErrors((prev) => ({ ...prev, presence: undefined }));
                    }
                  }}
                  disabled={saving}
                  placeholder="e.g. 3000"
                />
                {fieldErrors.presence && (
                  <span className="field-error-text" role="alert">
                    {fieldErrors.presence}
                  </span>
                )}
              </div>

              {/* Reason */}
              <div className="correction-field-group">
                <div className="correction-field-label">
                  <span>
                    Reason <span className="correction-field-required">*</span>
                  </span>
                  <span className="correction-field-subhint">
                    {reason.trim().length}/1000
                  </span>
                </div>
                <textarea
                  className={`correction-textarea ${
                    fieldErrors.reason ? "has-error" : ""
                  }`}
                  placeholder="Explain why this attendance is being manually corrected..."
                  value={reason}
                  onChange={(e) => {
                    setReason(e.target.value);
                    if (fieldErrors.reason) {
                      setFieldErrors((prev) => ({ ...prev, reason: undefined }));
                    }
                    if (apiError) setApiError(null);
                  }}
                  disabled={saving}
                  rows={3}
                  maxLength={1000}
                />
                {fieldErrors.reason && (
                  <span className="field-error-text" role="alert">
                    {fieldErrors.reason}
                  </span>
                )}
              </div>

              {/* API Error Alert */}
              {apiError && (
                <div className="correction-error-alert" role="alert">
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
                  <span>{apiError}</span>
                </div>
              )}

              {/* Form Action Buttons */}
              <div className="correction-form-actions">
                <button
                  type="button"
                  className="btn-cancel-correction"
                  onClick={onClose}
                  disabled={saving}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn-save-correction"
                  disabled={saving}
                >
                  {saving ? (
                    <>
                      <div className="btn-spinner" aria-hidden="true" />
                      <span>Saving Correction...</span>
                    </>
                  ) : (
                    <span>Save Correction</span>
                  )}
                </button>
              </div>
            </form>
          </div>

          {/* Right Column: Correction History */}
          <div className="correction-grid-right">
            <div className="history-header">
              <div className="history-title-group">
                <h3 className="history-title">Correction History</h3>
                {history.length > 0 && (
                  <span className="history-count-badge">{history.length}</span>
                )}
              </div>
              <button
                type="button"
                className={`btn-history-refresh ${historyLoading ? "is-spinning" : ""}`}
                onClick={loadHistory}
                disabled={historyLoading}
                title="Refresh history"
                aria-label="Refresh correction history"
              >
                <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99"
                  />
                </svg>
              </button>
            </div>

            {/* History Content Area */}
            <div className="history-container">
              {historyLoading && history.length === 0 ? (
                <div className="history-loading-box">
                  <div className="history-spinner" aria-hidden="true" />
                  <span>Loading audit trail...</span>
                </div>
              ) : historyError ? (
                <div className="history-error-box" role="alert">
                  <span className="history-error-text">{historyError}</span>
                  <button
                    type="button"
                    className="btn-history-retry"
                    onClick={loadHistory}
                  >
                    Retry
                  </button>
                </div>
              ) : history.length === 0 ? (
                <div className="history-empty-box">
                  <div className="history-empty-icon" aria-hidden="true">
                    <svg
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"
                      />
                    </svg>
                  </div>
                  <h4 className="history-empty-title">No manual corrections</h4>
                  <p className="history-empty-desc">
                    This attendance record has not been manually modified.
                  </p>
                </div>
              ) : (
                <div className="history-list">
                  {history.map((item) => (
                    <div key={item.correction_id} className="history-item-card">
                      <div className="history-item-header">
                        <span className="history-item-time">
                          {formatCorrectionTimestamp(item.corrected_at)}
                        </span>
                        <span className="history-item-author">
                          By: <strong className="history-teacher-name">{item.corrected_by}</strong>
                        </span>
                      </div>

                      <div className="history-item-transitions">
                        <div className="transition-row status-transition-row">
                          <span
                            className={`status-pill ${
                              item.previous_status === "PRESENT" ? "pill-present" : "pill-absent"
                            }`}
                          >
                            {item.previous_status}
                          </span>
                          <span className="transition-arrow">→</span>
                          <span
                            className={`status-pill ${
                              item.new_status === "PRESENT" ? "pill-present" : "pill-absent"
                            }`}
                          >
                            {item.new_status}
                          </span>
                        </div>

                        <div className="transition-row duration-transition-row">
                          <span className="duration-tag">
                            {formatPresenceDuration(item.previous_presence_seconds)}
                          </span>
                          <span className="transition-arrow">→</span>
                          <span className="duration-tag">
                            {formatPresenceDuration(item.new_presence_seconds)}
                          </span>
                        </div>
                      </div>

                      <div className="history-item-reason">
                        <span className="reason-label">Reason:</span>
                        <p className="reason-content">{item.reason}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
