import React, { useState } from "react";
import { auth } from "../../services";

interface RegisterFormProps {
  onSuccess: (registeredEmail: string) => void;
  onSwitchToLogin: () => void;
}

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export const RegisterForm: React.FC<RegisterFormProps> = ({
  onSuccess,
  onSwitchToLogin,
}) => {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [role, setRole] = useState<"TEACHER" | "STUDENT">("TEACHER");
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    const trimmedEmail = email.trim();

    // 1. Email format check
    if (!trimmedEmail) {
      setErrorMessage("Please enter an email address.");
      return;
    }
    if (!EMAIL_REGEX.test(trimmedEmail)) {
      setErrorMessage("Please enter a valid email address.");
      return;
    }

    // 2. Password length check
    if (password.length < 8) {
      setErrorMessage("Password must be at least 8 characters long.");
      return;
    }

    // 3. Confirm password match
    if (password !== confirmPassword) {
      setErrorMessage("Passwords do not match.");
      return;
    }

    // 4. Role check (strictly TEACHER or STUDENT)
    if (role !== "TEACHER" && role !== "STUDENT") {
      setErrorMessage("Please select a valid account type.");
      return;
    }

    setLoading(true);

    try {
      await auth.register({
        email: trimmedEmail,
        password,
        role,
      });

      onSuccess(trimmedEmail);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);

      if (
        message.includes("409") ||
        message.toLowerCase().includes("already exists")
      ) {
        setErrorMessage("An account with this email already exists.");
      } else if (
        message.includes("422") ||
        message.toLowerCase().includes("validation")
      ) {
        setErrorMessage("Please check the information entered.");
      } else {
        setErrorMessage("Unable to complete registration. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <form className="auth-form" onSubmit={handleSubmit} noValidate>
      {errorMessage && (
        <div className="alert-banner error" role="alert">
          <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 7.5h.008v.008H12v-.008z" />
          </svg>
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Account Type Selector (Teacher / Student only) */}
      <div className="form-group">
        <label className="role-group-label">Select Account Type</label>
        <div className="role-grid" role="radiogroup" aria-label="Account Type">
          <div
            className={`role-card ${role === "TEACHER" ? "selected" : ""}`}
            onClick={() => setRole("TEACHER")}
            role="radio"
            aria-checked={role === "TEACHER"}
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") setRole("TEACHER");
            }}
          >
            <svg className="role-card-icon" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M4.26 10.147a60.436 60.436 0 00-.491 6.347A48.627 48.627 0 0112 20.904a48.627 48.627 0 018.232-4.41 60.46 60.46 0 00-.491-6.347m-15.482 0a50.57 50.57 0 00-2.658-.813A59.905 59.905 0 0112 3.493a59.902 59.902 0 0110.399 5.84c-.896.248-1.783.52-2.658.814m-15.482 0A50.697 50.697 0 0112 13.489a50.702 50.702 0 017.74-3.342" />
            </svg>
            <span className="role-card-title">Teacher</span>
            <span className="role-card-desc">Sessions & Roster</span>
          </div>

          <div
            className={`role-card ${role === "STUDENT" ? "selected" : ""}`}
            onClick={() => setRole("STUDENT")}
            role="radio"
            aria-checked={role === "STUDENT"}
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") setRole("STUDENT");
            }}
          >
            <svg className="role-card-icon" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
            </svg>
            <span className="role-card-title">Student</span>
            <span className="role-card-desc">Attendance Records</span>
          </div>
        </div>
      </div>

      <div className="form-group">
        <label className="form-label" htmlFor="register-email">
          Email Address
        </label>
        <div className="input-container">
          <svg className="input-icon" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0v.243a2.25 2.25 0 01-1.07 1.916l-7.5 4.615a2.25 2.25 0 01-2.36 0L3.32 8.91a2.25 2.25 0 01-1.07-1.916V6.75" />
          </svg>
          <input
            id="register-email"
            type="email"
            className="auth-input"
            placeholder="you@institution.edu"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            required
            disabled={loading}
          />
        </div>
      </div>

      <div className="form-group">
        <label className="form-label" htmlFor="register-password">
          Password (min. 8 characters)
        </label>
        <div className="input-container">
          <svg className="input-icon" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
          </svg>
          <input
            id="register-password"
            type="password"
            className="auth-input"
            placeholder="At least 8 characters"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            required
            disabled={loading}
          />
        </div>
      </div>

      <div className="form-group">
        <label className="form-label" htmlFor="register-confirm-password">
          Confirm Password
        </label>
        <div className="input-container">
          <svg className="input-icon" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
          </svg>
          <input
            id="register-confirm-password"
            type="password"
            className="auth-input"
            placeholder="Re-enter password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            autoComplete="new-password"
            required
            disabled={loading}
          />
        </div>
      </div>

      <button type="submit" className="btn-submit" disabled={loading}>
        {loading ? (
          <>
            <svg className="spinner" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="10" strokeOpacity="0.25" />
              <path d="M4 12a8 8 0 018-8" />
            </svg>
            <span>Creating account...</span>
          </>
        ) : (
          <span>Create Account</span>
        )}
      </button>

      <div className="auth-footer">
        <span>Already have an account?</span>
        <button
          type="button"
          className="auth-footer-btn"
          onClick={onSwitchToLogin}
          disabled={loading}
        >
          Sign in
        </button>
      </div>
    </form>
  );
};
