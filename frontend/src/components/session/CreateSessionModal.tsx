import React, { useEffect, useState } from "react";
import { api } from "../../services";
import type { SessionCreate, SessionResponse, StudentDirectoryItem } from "../../types";
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

const formatLocalDateTimeInput = (date: Date): string => {
  const pad = (n: number) => n.toString().padStart(2, "0");
  const year = date.getFullYear();
  const month = pad(date.getMonth() + 1);
  const day = pad(date.getDate());
  const hours = pad(date.getHours());
  const mins = pad(date.getMinutes());
  return `${year}-${month}-${day}T${hours}:${mins}`;
};

export const CreateSessionModal: React.FC<CreateSessionModalProps> = ({
  isOpen,
  onClose,
  onSessionCreated,
}) => {
  const [courseName, setCourseName] = useState("");
  const [classroomId, setClassroomId] = useState("ROOM_101");
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [requiredPresence, setRequiredPresence] = useState<number>(75);

  // Student directory & search
  const [studentDirectory, setStudentDirectory] = useState<StudentDirectoryItem[]>([]);
  const [directoryLoading, setDirectoryLoading] = useState(false);
  const [studentSearch, setStudentSearch] = useState("");
  const [selectedStudents, setSelectedStudents] = useState<Set<string>>(new Set());

  // Video Source Configuration
  const [videoSource, setVideoSource] = useState<"WEBCAM" | "SIMULATOR">("WEBCAM");

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<ValidationErrors>({});

  // Reset & load defaults when modal opens
  useEffect(() => {
    if (isOpen) {
      setApiError(null);
      setValidationErrors({});
      const now = new Date();
      const in90m = new Date(now.getTime() + 90 * 60 * 1000);
      setStartTime(formatLocalDateTimeInput(now));
      setEndTime(formatLocalDateTimeInput(in90m));
      setClassroomId("ROOM_101");

      // Fetch student candidates from database
      setDirectoryLoading(true);
      api
        .getStudentsDirectory()
        .then((items) => {
          setStudentDirectory(items);
          // By default, pre-select all available students so roster is ready
          const allIds = new Set(items.map((s) => s.identity));
          setSelectedStudents(allIds);
        })
        .catch(() => {
          // Fallback demo students
          const fallback = [
            {
              identity: "student_alice",
              name: "Alice Smith",
              email: "alice@demo.edu",
              student_id: "STU_ALICE",
              has_biometric: true,
            },
            {
              identity: "student_bob",
              name: "Bob Jones",
              email: "bob@demo.edu",
              student_id: "STU_BOB",
              has_biometric: true,
            },
            {
              identity: "student_charlie",
              name: "Charlie Davis",
              email: "charlie@demo.edu",
              student_id: "STU_CHARLIE",
              has_biometric: true,
            },
            {
              identity: "person_01",
              name: "Demo Candidate 1",
              email: "person_01@campus.edu",
              student_id: "person_01",
              has_biometric: true,
            },
          ];
          setStudentDirectory(fallback);
          setSelectedStudents(new Set(fallback.map((s) => s.identity)));
        })
        .finally(() => {
          setDirectoryLoading(false);
        });
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

  const toggleStudent = (ident: string) => {
    setSelectedStudents((prev) => {
      const next = new Set(prev);
      if (next.has(ident)) {
        next.delete(ident);
      } else {
        next.add(ident);
      }
      return next;
    });
  };

  const selectAllFiltered = () => {
    const next = new Set(selectedStudents);
    filteredStudents.forEach((s) => next.add(s.identity));
    setSelectedStudents(next);
  };

  const deselectAllFiltered = () => {
    const next = new Set(selectedStudents);
    filteredStudents.forEach((s) => next.delete(s.identity));
    setSelectedStudents(next);
  };

  // ⚡ Instant Start Action
  const handleInstantStart = async () => {
    setIsSubmitting(true);
    setApiError(null);
    try {
      const now = new Date();
      const in2h = new Date(now.getTime() + 120 * 60 * 1000);
      const instantPayload: SessionCreate = {
        course_name: courseName.trim() || `Classroom Session (${now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })})`,
        classroom_id: (classroomId || "ROOM_101").trim(),
        start_time: now.toISOString(),
        end_time: in2h.toISOString(),
        required_presence_percentage: 75.0,
      };

      const createdSession = await api.createSession(instantPayload);

      // Automatically register selected roster students into session
      const identitiesToEnroll = Array.from(selectedStudents);
      if (identitiesToEnroll.length > 0) {
        await api.updateSessionRoster(createdSession.session_id, identitiesToEnroll);
      }

      onSessionCreated(createdSession);
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setApiError(msg || "Failed to instantly start session.");
    } finally {
      setIsSubmitting(false);
    }
  };

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

      // Automatically register selected students into session roster
      const identitiesToEnroll = Array.from(selectedStudents);
      if (identitiesToEnroll.length > 0) {
        await api.updateSessionRoster(createdSession.session_id, identitiesToEnroll);
      }

      // Reset form fields on success
      setCourseName("");
      setClassroomId("ROOM_101");
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

  const filteredStudents = studentDirectory.filter((s) => {
    const q = studentSearch.toLowerCase().trim();
    if (!q) return true;
    return (
      s.name.toLowerCase().includes(q) ||
      s.identity.toLowerCase().includes(q) ||
      s.email.toLowerCase().includes(q) ||
      (s.student_id && s.student_id.toLowerCase().includes(q))
    );
  });

  return (
    <div
      className="modal-backdrop"
      onClick={handleBackdropClick}
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-session-title"
    >
      <div className="modal-card modal-card-wide">
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
            <div>
              <h2 id="create-session-title" className="modal-title">
                Create Attendance Session
              </h2>
              <p className="modal-subtitle">
                Configure optical camera, select enrolled students, or launch instantly.
              </p>
            </div>
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

        {/* ⚡ Instant Start Quick Action Banner */}
        <div className="instant-start-banner">
          <div className="instant-banner-text">
            <span className="instant-badge">⚡ INSTANT LAUNCH</span>
            <strong>Start Session Immediately (No Manual Timestamps Needed)</strong>
            <span>Launches session now in Room 101 with selected students; end anytime with 1 click.</span>
          </div>
          <button
            type="button"
            className="btn-instant-start"
            onClick={handleInstantStart}
            disabled={isSubmitting}
          >
            {isSubmitting ? "Starting..." : "⚡ Start Now"}
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

            {/* Course Name & Classroom */}
            <div className="form-row-2col">
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
                  placeholder="e.g. Data Science & AI"
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
                  placeholder="e.g. ROOM_101"
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
            </div>

            {/* Video Source Selection */}
            <div className="modal-field">
              <label className="modal-label">
                <span>Configure Video Source Before Start</span>
                <span className="presence-helper">Continuous camera node for facial recognition</span>
              </label>
              <div className="video-source-selector">
                <label className={`video-source-option ${videoSource === "WEBCAM" ? "selected" : ""}`}>
                  <input
                    type="radio"
                    name="videoSource"
                    value="WEBCAM"
                    checked={videoSource === "WEBCAM"}
                    onChange={() => setVideoSource("WEBCAM")}
                  />
                  <div className="option-content">
                    <span className="option-title">💻 Laptop Webcam</span>
                    <span className="option-sub">Direct in-browser camera</span>
                  </div>
                </label>

                <label className={`video-source-option ${videoSource === "SIMULATOR" ? "selected" : ""}`}>
                  <input
                    type="radio"
                    name="videoSource"
                    value="SIMULATOR"
                    checked={videoSource === "SIMULATOR"}
                    onChange={() => setVideoSource("SIMULATOR")}
                  />
                  <div className="option-content">
                    <span className="option-title">🎬 Optical Simulator</span>
                    <span className="option-sub">1-click test transit events</span>
                  </div>
                </label>
              </div>
            </div>

            {/* Student Search & Suggestions (Roster Selection) */}
            <div className="modal-field">
              <div className="student-selection-header">
                <label className="modal-label" style={{ marginBottom: 0 }}>
                  <span>Select Students From Database ({selectedStudents.size} selected)</span>
                </label>
                <div className="selection-quick-actions">
                  <button type="button" className="btn-text-action" onClick={selectAllFiltered}>
                    Select All
                  </button>
                  <span className="divider">•</span>
                  <button type="button" className="btn-text-action" onClick={deselectAllFiltered}>
                    Clear
                  </button>
                </div>
              </div>

              {/* Student Search Bar */}
              <div className="student-search-box">
                <svg className="search-icon" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
                </svg>
                <input
                  type="text"
                  className="student-search-input"
                  placeholder="Search students by name, email, or identity..."
                  value={studentSearch}
                  onChange={(e) => setStudentSearch(e.target.value)}
                />
                {studentSearch && (
                  <button
                    type="button"
                    className="clear-search-btn"
                    onClick={() => setStudentSearch("")}
                  >
                    ✕
                  </button>
                )}
              </div>

              {/* Student Candidate List */}
              <div className="student-chips-container">
                {directoryLoading ? (
                  <div className="chips-loading">Loading students from database...</div>
                ) : filteredStudents.length === 0 ? (
                  <div className="chips-empty">No students found matching "{studentSearch}"</div>
                ) : (
                  filteredStudents.map((s) => {
                    const isSelected = selectedStudents.has(s.identity);
                    return (
                      <div
                        key={s.identity}
                        className={`student-chip-card ${isSelected ? "selected" : ""}`}
                        onClick={() => toggleStudent(s.identity)}
                        role="checkbox"
                        aria-checked={isSelected}
                        tabIndex={0}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => {}} /* handled by parent div */
                          aria-hidden="true"
                        />
                        <div className="chip-info">
                          <span className="chip-name">{s.name}</span>
                          <span className="chip-id">{s.identity}</span>
                        </div>
                        {s.has_biometric && (
                          <span className="chip-bio-badge" title="Biometric profile enrolled">
                            🟢 Bio
                          </span>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
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
                  <span>Creating & Enrolling...</span>
                </>
              ) : (
                <span>Schedule & Enroll ({selectedStudents.size})</span>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
