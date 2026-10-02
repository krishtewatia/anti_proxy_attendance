import React, { useCallback, useEffect, useState } from "react";
import { api } from "../services";
import type { StudentProfile, UserResponse } from "../types";
import "./student-dashboard.css";

interface StudentDashboardProps {
  user: UserResponse;
  onLogout: () => void;
  onNavigate?: (path: string) => void;
}

export const StudentDashboard: React.FC<StudentDashboardProps> = ({
  user,
}) => {
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [binding, setBinding] = useState<boolean>(false);
  const [identityInput, setIdentityInput] = useState<string>("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isConflictError, setIsConflictError] = useState<boolean>(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const fetchProfile = useCallback(async () => {
    setLoading(true);
    setErrorMessage(null);
    setIsConflictError(false);

    try {
      const data = await api.getStudentProfile();
      setProfile(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      // 404 indicates the student account has not yet bound a CV identity (unbound state)
      if (msg.includes("404") || msg.toLowerCase().includes("not found")) {
        setProfile(null);
      } else {
        setErrorMessage(
          msg || "Unable to check student identity status. Please refresh."
        );
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProfile();
  }, [fetchProfile]);

  // Auto-dismiss success notification
  useEffect(() => {
    if (!successMessage) return;
    const timer = setTimeout(() => {
      setSuccessMessage(null);
    }, 6000);
    return () => clearTimeout(timer);
  }, [successMessage]);

  const handleIdentitySubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const trimmed = identityInput.trim();
    if (!trimmed) {
      setValidationError("Please enter a valid CV identity (e.g., person_01)");
      return;
    }

    setValidationError(null);
    setErrorMessage(null);
    setIsConflictError(false);
    setBinding(true);

    try {
      // Security: Sends only { identity }, user_id is derived on backend strictly from JWT
      const boundProfile = await api.bindStudentProfile(trimmed);
      setProfile(boundProfile);
      setSuccessMessage(`Identity successfully linked to ${boundProfile.identity}.`);
      setIdentityInput("");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      if (
        msg.includes("409") ||
        msg.toLowerCase().includes("already bound") ||
        msg.toLowerCase().includes("already has a student profile") ||
        msg.toLowerCase().includes("conflict")
      ) {
        setIsConflictError(true);
        setErrorMessage(
          msg ||
            "Conflict: This CV identity may already be assigned to another student, or your account is already bound."
        );
      } else {
        setErrorMessage(msg || "Failed to link identity. Please try again.");
      }
    } finally {
      setBinding(false);
    }
  };

  return (
    <div className="student-dashboard">
      {/* Header */}
      <div className="student-dashboard-header">
        <span className="student-portal-badge">Student Portal</span>
        <h1 className="student-title">Student Dashboard</h1>
        <p className="student-subtitle">
          Personal presence timeline and session attendance logs for{" "}
          <span className="student-email-highlight">{user.email}</span>
        </p>
      </div>

      {/* Success Notification */}
      {successMessage && (
        <div className="student-alert student-alert-success" role="alert">
          <svg
            className="student-alert-icon"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <div className="student-alert-content">
            <div className="student-alert-title">Identity Linked</div>
            <div>{successMessage}</div>
          </div>
          <button
            type="button"
            className="student-alert-close"
            onClick={() => setSuccessMessage(null)}
            title="Dismiss notification"
          >
            ✕
          </button>
        </div>
      )}

      {/* Error / Conflict Alert */}
      {errorMessage && (
        <div
          className={`student-alert ${
            isConflictError ? "student-alert-warning" : "student-alert-error"
          }`}
          role="alert"
        >
          <svg
            className="student-alert-icon"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            viewBox="0 0 24 24"
          >
            {isConflictError ? (
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
              />
            ) : (
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"
              />
            )}
          </svg>
          <div className="student-alert-content">
            <div className="student-alert-title">
              {isConflictError ? "Identity Conflict (409)" : "Error"}
            </div>
            <div>{errorMessage}</div>
            {isConflictError && (
              <div style={{ marginTop: "0.4rem", fontSize: "0.8125rem", opacity: 0.9 }}>
                The identity you entered may already be claimed by another student in the system.
                Please contact your course instructor to verify your assigned CV identity identifier.
              </div>
            )}
          </div>
          <button
            type="button"
            className="student-alert-close"
            onClick={() => {
              setErrorMessage(null);
              setIsConflictError(false);
            }}
            title="Dismiss error"
          >
            ✕
          </button>
        </div>
      )}

      {/* Main Grid */}
      <div className="student-grid">
        {/* Identity Verification Card */}
        <section className="student-card" aria-labelledby="identity-verification-heading">
          <div className="student-card-header">
            <div className="student-card-title-group">
              <div className="student-card-icon" aria-hidden="true">
                <svg
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M15 9h3.75M15 12h3.75M15 15h3.75M4.5 19.5h15a2.25 2.25 0 002.25-2.25V6.75A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25v10.5A2.25 2.25 0 004.5 19.5zm6-10.125a1.875 1.875 0 11-3.75 0 1.875 1.875 0 013.75 0zm1.294 6.336a6.721 6.721 0 01-3.169.789 6.721 6.721 0 01-3.168-.789 3.376 3.376 0 016.337 0z"
                  />
                </svg>
              </div>
              <h2 id="identity-verification-heading">Identity Verification</h2>
            </div>

            {/* Status Pill in Header */}
            {!loading && (
              <div
                className={`identity-status-pill ${
                  profile ? "status-linked" : "status-unlinked"
                }`}
              >
                <span className="status-dot" aria-hidden="true" />
                <span>
                  {profile
                    ? "✓ Identity linked"
                    : "Your account is not linked to a CV identity"}
                </span>
              </div>
            )}
          </div>

          {/* Loading State */}
          {loading && (
            <div className="identity-loading-container">
              <div className="identity-spinner" aria-hidden="true" />
              <span>Verifying student profile status...</span>
            </div>
          )}

          {/* Bound State */}
          {!loading && profile && (
            <div className="identity-bound-view">
              <div className="bound-highlight-box">
                <div className="bound-field-group">
                  <span className="bound-field-label">CV Identity</span>
                  <div className="bound-identity-badge">
                    <svg
                      width="20"
                      height="20"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z"
                      />
                    </svg>
                    <span>{profile.identity}</span>
                  </div>
                </div>

                <div className="bound-meta-row">
                  <div className="bound-meta-item">
                    <span className="bound-meta-label">Account User ID</span>
                    <span className="bound-meta-value">{profile.user_id}</span>
                  </div>
                  <div className="bound-meta-item">
                    <span className="bound-meta-label">Status</span>
                    <span
                      className="bound-meta-value"
                      style={{ color: "#34d399", fontWeight: 600 }}
                    >
                      Active & Enrolled
                    </span>
                  </div>
                </div>
              </div>

              <div className="bound-notice-box">
                <svg
                  className="bound-notice-icon"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                  />
                </svg>
                <span>This identity will be used for attendance.</span>
              </div>
            </div>
          )}

          {/* Unbound State / Setup Form */}
          {!loading && !profile && (
            <div className="identity-unbound-view">
              <p className="unbound-intro-text">
                Your account is currently not linked to a computer-vision identity.
                Enter the identity identifier assigned by your instructor to link your account
                for automated classroom attendance.
              </p>

              <form className="identity-setup-form" onSubmit={handleIdentitySubmit}>
                <div className="form-group">
                  <label htmlFor="cv-identity-input" className="form-label">
                    <span>CV Identity</span>
                    <span style={{ fontSize: "0.75rem", color: "var(--text-dim)" }}>
                      Required
                    </span>
                  </label>
                  <div className="form-input-wrapper">
                    <input
                      id="cv-identity-input"
                      type="text"
                      className={`form-input ${
                        validationError || isConflictError ? "has-error" : ""
                      }`}
                      placeholder="e.g. person_01"
                      value={identityInput}
                      onChange={(e) => {
                        setIdentityInput(e.target.value);
                        if (validationError) setValidationError(null);
                        if (errorMessage) {
                          setErrorMessage(null);
                          setIsConflictError(false);
                        }
                      }}
                      disabled={binding}
                      autoComplete="off"
                    />
                  </div>
                  {validationError && (
                    <div className="form-field-error">{validationError}</div>
                  )}
                </div>

                <button
                  type="submit"
                  className="btn-link-identity"
                  disabled={binding || !identityInput.trim()}
                >
                  {binding ? (
                    <>
                      <div className="btn-spinner" aria-hidden="true" />
                      <span>Linking Identity...</span>
                    </>
                  ) : (
                    <span>Link Identity</span>
                  )}
                </button>
              </form>

              <div className="identity-advisory">
                <svg
                  className="identity-advisory-icon"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
                  />
                </svg>
                <span>
                  ⚠ Make sure your teacher has assigned the correct identity to you.
                </span>
              </div>
            </div>
          )}
        </section>

        {/* Student Account Overview Card */}
        <section className="student-card account-info-card" aria-labelledby="student-account-heading">
          <div className="student-card-header">
            <div className="student-card-title-group">
              <div className="student-card-icon" style={{ background: "rgba(6, 182, 212, 0.15)", color: "#22d3ee", borderColor: "rgba(6, 182, 212, 0.3)" }}>
                <svg
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M17.982 18.725A7.488 7.488 0 0012 15.75a7.488 7.488 0 00-5.982 2.975m11.963 0a9 9 0 10-11.963 0m11.963 0A8.966 8.966 0 0112 21a8.966 8.966 0 01-5.982-2.275M15 9.75a3 3 0 11-6 0 3 3 0 016 0z"
                  />
                </svg>
              </div>
              <h2 id="student-account-heading">Student Account Details</h2>
            </div>
          </div>

          <div className="account-info-grid">
            <div className="account-info-item">
              <span className="account-info-label">User ID</span>
              <span className="account-info-value mono">{user.user_id}</span>
            </div>
            <div className="account-info-item">
              <span className="account-info-label">Email Address</span>
              <span className="account-info-value">{user.email}</span>
            </div>
            <div className="account-info-item">
              <span className="account-info-label">Role</span>
              <span className="account-info-value" style={{ color: "#38bdf8" }}>{user.role}</span>
            </div>
            <div className="account-info-item">
              <span className="account-info-label">Account Status</span>
              <span className="account-info-value" style={{ color: "#34d399" }}>
                {user.is_active ? "Active" : "Inactive"}
              </span>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
};
