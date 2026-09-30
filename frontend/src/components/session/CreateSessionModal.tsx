import React, { useEffect, useState } from "react";
import { api } from "../../services";
import type { SessionCreate, SessionResponse } from "../../types";
import "./create-session.css";
import {
  type SessionFormData,
  type ValidationErrors,
  validateSessionForm,
} from "./validation.ts";

export { validateSessionForm, type SessionFormData, type ValidationErrors };

export interface CreateSessionModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSessionCreated: (session: SessionResponse) => void;
}

export const CreateSessionModal: React.FC<CreateSessionModalProps> = ({
  isOpen,
  onClose,
  onSessionCreated,
}) => {
  const [courseName, setCourseName] = useState("");
  const [classroomId, setClassroomId] = useState("");
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [requiredPresence, setRequiredPresence] = useState<number>(75);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<ValidationErrors>({});

  // Reset form or errors when modal opens
  useEffect(() => {
    if (isOpen) {
      setApiError(null);
      setValidationErrors({});
    }
  }, [isOpen]);

  // Handle ESC key to close modal
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !isSubmitting) {
        onClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, isSubmitting, onClose]);

  if (!isOpen) {
    return null;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setApiError(null);

    const { isValid, errors } = validateSessionForm({
      courseName,
      classroomId,
      startTime,
      endTime,
      requiredPresence,
    });

    setValidationErrors(errors);
    if (!isValid) {
      return;
    }

    setIsSubmitting(true);

    try {
      const payload: SessionCreate = {
        course_name: courseName.trim(),
        classroom_id: classroomId.trim(),
        start_time: new Date(startTime).toISOString(),
        end_time: new Date(endTime).toISOString(),
        required_presence_percentage: Number(requiredPresence),
      };

      const createdSession = await api.createSession(payload);

      // Reset form fields on success
      setCourseName("");
      setClassroomId("");
      setStartTime("");
      setEndTime("");
      setRequiredPresence(75);

      onSessionCreated(createdSession);
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setApiError(
        msg || "Unable to create session. Please check your inputs and try again."
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleBackdropClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget && !isSubmitting) {
      onClose();
    }
  };

  return (
    <div
      className="modal-backdrop"
      onClick={handleBackdropClick}
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-session-title"
    >
      <div className="modal-card">
        {/* Header */}
        <div className="modal-header">
          <div className="modal-title-wrapper">
            <div className="modal-header-icon" aria-hidden="true">
              <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M12 4.5v15m7.5-7.5h-15"
                />
              </svg>
            </div>
            <h2 id="create-session-title" className="modal-title">
              Create Attendance Session
            </h2>
          </div>
          <button
            type="button"
            className="modal-close-btn"
            onClick={onClose}
            disabled={isSubmitting}
            title="Close modal"
            aria-label="Close"
          >
            <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} noValidate>
          <div className="modal-body">
            {/* API Error Banner if request failed */}
            {apiError && (
              <div className="modal-alert error" role="alert">
                <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 7.5h.008v.008H12v-.008z"
                  />
                </svg>
                <span>{apiError}</span>
              </div>
            )}

            {/* Course Name */}
            <div className="modal-field">
              <label htmlFor="course-name-input" className="modal-label">
                <span>
                  Course Name <span className="required-indicator">*</span>
                </span>
              </label>
              <input
                id="course-name-input"
                type="text"
                className={`modal-input ${validationErrors.courseName ? "has-error" : ""}`}
                placeholder="e.g. Data Science"
                value={courseName}
                onChange={(e) => {
                  setCourseName(e.target.value);
                  if (validationErrors.courseName) {
                    setValidationErrors((prev) => ({ ...prev, courseName: undefined }));
                  }
                }}
                disabled={isSubmitting}
                autoFocus
              />
              {validationErrors.courseName && (
                <span className="field-error-text">{validationErrors.courseName}</span>
              )}
            </div>

            {/* Classroom */}
            <div className="modal-field">
              <label htmlFor="classroom-input" className="modal-label">
                <span>
                  Classroom <span className="required-indicator">*</span>
                </span>
              </label>
              <input
                id="classroom-input"
                type="text"
                className={`modal-input ${validationErrors.classroomId ? "has-error" : ""}`}
                placeholder="e.g. Room 204"
                value={classroomId}
                onChange={(e) => {
                  setClassroomId(e.target.value);
                  if (validationErrors.classroomId) {
                    setValidationErrors((prev) => ({ ...prev, classroomId: undefined }));
                  }
                }}
                disabled={isSubmitting}
              />
              {validationErrors.classroomId && (
                <span className="field-error-text">{validationErrors.classroomId}</span>
              )}
            </div>

            {/* Start Time & End Time */}
            <div className="form-row-2col">
              <div className="modal-field">
                <label htmlFor="start-time-input" className="modal-label">
                  <span>
                    Start Time <span className="required-indicator">*</span>
                  </span>
                </label>
                <input
                  id="start-time-input"
                  type="datetime-local"
                  className={`modal-input ${validationErrors.startTime ? "has-error" : ""}`}
                  value={startTime}
                  onChange={(e) => {
                    setStartTime(e.target.value);
                    if (validationErrors.startTime) {
                      setValidationErrors((prev) => ({ ...prev, startTime: undefined }));
                    }
                  }}
                  disabled={isSubmitting}
                />
                {validationErrors.startTime && (
                  <span className="field-error-text">{validationErrors.startTime}</span>
                )}
              </div>

              <div className="modal-field">
                <label htmlFor="end-time-input" className="modal-label">
                  <span>
                    End Time <span className="required-indicator">*</span>
                  </span>
                </label>
                <input
                  id="end-time-input"
                  type="datetime-local"
                  className={`modal-input ${validationErrors.endTime ? "has-error" : ""}`}
                  value={endTime}
                  onChange={(e) => {
                    setEndTime(e.target.value);
                    if (validationErrors.endTime) {
                      setValidationErrors((prev) => ({ ...prev, endTime: undefined }));
                    }
                  }}
                  disabled={isSubmitting}
                />
                {validationErrors.endTime && (
                  <span className="field-error-text">{validationErrors.endTime}</span>
                )}
              </div>
            </div>

            {/* Required Presence */}
            <div className="modal-field">
              <label htmlFor="presence-input" className="modal-label">
                <span>Required Presence</span>
                <span className="presence-helper">0 – 100% (default 75%)</span>
              </label>
              <div className="presence-input-wrapper">
                <input
                  id="presence-input"
                  type="number"
                  min="0"
                  max="100"
                  step="1"
                  className={`modal-input ${validationErrors.requiredPresence ? "has-error" : ""}`}
                  value={isNaN(requiredPresence) ? "" : requiredPresence}
                  onChange={(e) => {
                    const val = parseFloat(e.target.value);
                    setRequiredPresence(val);
                    if (validationErrors.requiredPresence) {
                      setValidationErrors((prev) => ({ ...prev, requiredPresence: undefined }));
                    }
                  }}
                  disabled={isSubmitting}
                />
                <span className="presence-suffix" aria-hidden="true">%</span>
              </div>
              {validationErrors.requiredPresence && (
                <span className="field-error-text">{validationErrors.requiredPresence}</span>
              )}
            </div>
          </div>

          {/* Footer Actions */}
          <div className="modal-footer">
            <button
              type="button"
              className="btn-modal-cancel"
              onClick={onClose}
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn-modal-submit"
              disabled={isSubmitting}
            >
              {isSubmitting ? (
                <>
                  <svg
                    className="spinner"
                    width="16"
                    height="16"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    viewBox="0 0 24 24"
                    aria-hidden="true"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99"
                    />
                  </svg>
                  <span>Creating...</span>
                </>
              ) : (
                <span>Create Session</span>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
