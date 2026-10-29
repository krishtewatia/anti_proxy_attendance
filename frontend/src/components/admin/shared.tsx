import React, { useState } from "react";
import { api } from "../../services";

interface AdminModalProps {
  title: string;
  onClose: () => void;
  onSubmit?: (e: React.FormEvent) => void;
  submitLabel?: string;
  busy?: boolean;
  children: React.ReactNode;
}

export const AdminModal: React.FC<AdminModalProps> = ({
  title,
  onClose,
  onSubmit,
  submitLabel,
  busy = false,
  children,
}) => (
  <div className="erp-modal-overlay">
    <div className="erp-modal-card">
      <div className="erp-modal-header">
        <h3 className="erp-modal-title">{title}</h3>
        <button type="button" className="erp-modal-close-btn" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit?.(e);
        }}
      >
        <div className="erp-modal-body">{children}</div>
        <div className="erp-modal-footer">
          <button type="button" className="erp-btn erp-btn-secondary" onClick={onClose}>
            {onSubmit ? "Cancel" : "Close"}
          </button>
          {onSubmit && (
            <button type="submit" className="erp-btn erp-btn-primary" disabled={busy}>
              {busy ? "Saving..." : submitLabel}
            </button>
          )}
        </div>
      </form>
    </div>
  </div>
);

// Reset a password: the administrator types the new one and gives it to the
// person, who signs in with it (no forced change). It is sent once and kept
// nowhere in the page.
export const MIN_RESET_PASSWORD = 8;

export const SetPasswordModal: React.FC<{
  accountLabel: string;
  userId: string;
  onClose: () => void;
}> = ({ accountLabel, userId, onClose }) => {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const submit = async () => {
    if (password.length < MIN_RESET_PASSWORD) {
      setError(`The password must be at least ${MIN_RESET_PASSWORD} characters.`);
      return;
    }
    if (password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.resetUserPassword(userId, password);
      setPassword("");
      setConfirm("");
      setDone(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <AdminModal title="Password reset" onClose={onClose}>
        <p style={{ fontSize: "0.875rem", margin: 0 }}>
          The password for <strong>{accountLabel}</strong> is set. Give it to them; they sign in with it.
          Every device the account was signed in on has been signed out.
        </p>
      </AdminModal>
    );
  }

  return (
    <AdminModal title="Reset password" onClose={onClose} onSubmit={() => void submit()} submitLabel="Set password" busy={busy}>
      <p style={{ fontSize: "0.875rem", marginTop: 0 }}>
        Type a new password for <strong>{accountLabel}</strong> and give it to them. They sign in with it;
        they are signed out everywhere else.
      </p>
      {error && (
        <div className="alert-banner error" role="alert" style={{ marginBottom: "0.75rem" }}>
          <span>{error}</span>
        </div>
      )}
      <div className="form-group" style={{ marginBottom: "0.75rem" }}>
        <label className="form-label" htmlFor="reset-password-new">New password</label>
        <input id="reset-password-new" type="password" className="auth-input" autoComplete="new-password" minLength={MIN_RESET_PASSWORD} value={password} onChange={(e) => setPassword(e.target.value)} />
      </div>
      <div className="form-group">
        <label className="form-label" htmlFor="reset-password-confirm">Type it again</label>
        <input id="reset-password-confirm" type="password" className="auth-input" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      </div>
      <p style={{ fontSize: "0.8rem", color: "var(--erp-text-muted)", marginBottom: 0 }}>At least {MIN_RESET_PASSWORD} characters.</p>
    </AdminModal>
  );
};

// Check boxes for choosing classes from the ones that exist.
export const ClassPicker: React.FC<{
  available: string[];
  selected: string[];
  onChange: (next: string[]) => void;
}> = ({ available, selected, onChange }) => {
  // A class the teacher already has stays visible even if it is no longer offered.
  const options = [...available, ...selected.filter((code) => !available.includes(code))];
  if (options.length === 0) {
    return <div style={{ fontSize: "0.8125rem", color: "var(--erp-text-muted)" }}>No classes exist yet.</div>;
  }
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem 1rem" }}>
      {options.map((code) => (
        <label key={code} style={{ display: "flex", alignItems: "center", gap: "0.35rem", fontSize: "0.875rem" }}>
          <input
            type="checkbox"
            checked={selected.includes(code)}
            onChange={(e) =>
              onChange(e.target.checked ? [...selected, code] : selected.filter((c) => c !== code))
            }
          />
          {code}
        </label>
      ))}
    </div>
  );
};
