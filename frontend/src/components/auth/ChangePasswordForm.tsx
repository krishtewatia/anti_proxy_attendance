import React, { useState } from "react";
import { auth } from "../../services";
import { MIN_PASSWORD_LENGTH, validatePasswordChange } from "../../utils/accounts.ts";

interface ChangePasswordFormProps {
  // True when the account cannot do anything else until the password is changed.
  forced: boolean;
  onDone: () => void;
  onCancel?: () => void;
}

export const ChangePasswordForm: React.FC<ChangePasswordFormProps> = ({ forced, onDone, onCancel }) => {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const problem = validatePasswordChange(current, next, confirm);
    if (problem) {
      setErrorMessage(problem);
      return;
    }
    setErrorMessage(null);
    setSaving(true);
    try {
      await auth.changePassword(current, next);
      onDone();
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : "The password could not be changed.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="auth-form" onSubmit={handleSubmit} noValidate>
      {forced && (
        <div className="alert-banner success" role="status" style={{ marginBottom: "1rem" }}>
          <span>
            Your password was set by an administrator. Choose your own password to continue.
          </span>
        </div>
      )}
      {errorMessage && (
        <div className="alert-banner error" role="alert" style={{ marginBottom: "1rem" }}>
          <span>{errorMessage}</span>
        </div>
      )}

      <div className="form-group">
        <label className="form-label" htmlFor="change-current">
          {forced ? "Password you were given" : "Current password"}
        </label>
        <input
          id="change-current"
          type="password"
          className="auth-input"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          autoComplete="current-password"
          disabled={saving}
          required
        />
      </div>

      <div className="form-group">
        <label className="form-label" htmlFor="change-new">
          New password
        </label>
        <input
          id="change-new"
          type="password"
          className="auth-input"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          autoComplete="new-password"
          minLength={MIN_PASSWORD_LENGTH}
          disabled={saving}
          required
        />
        <small style={{ color: "var(--erp-text-muted)", fontSize: "0.75rem" }}>
          At least {MIN_PASSWORD_LENGTH} characters.
        </small>
      </div>

      <div className="form-group">
        <label className="form-label" htmlFor="change-confirm">
          New password again
        </label>
        <input
          id="change-confirm"
          type="password"
          className="auth-input"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          autoComplete="new-password"
          disabled={saving}
          required
        />
      </div>

      <p style={{ color: "var(--erp-text-muted)", fontSize: "0.8125rem", margin: "0 0 1rem" }}>
        Changing your password signs you out everywhere else.
      </p>

      <button type="submit" className="btn-submit" disabled={saving}>
        <span>{saving ? "Saving..." : "Change Password"}</span>
      </button>

      {onCancel && (
        <div className="auth-footer">
          <button type="button" className="auth-footer-btn" onClick={onCancel} disabled={saving}>
            {forced ? "Sign out" : "Cancel"}
          </button>
        </div>
      )}
    </form>
  );
};
