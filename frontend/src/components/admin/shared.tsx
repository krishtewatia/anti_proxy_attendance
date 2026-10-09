import React, { useState } from "react";

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

// A temporary password is returned by the server once. It is shown here until
// the administrator closes the box, and is kept nowhere else.
export const TemporaryPasswordNotice: React.FC<{
  accountLabel: string;
  temporaryPassword: string;
  onClose: () => void;
}> = ({ accountLabel, temporaryPassword, onClose }) => {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(temporaryPassword);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <AdminModal title="Temporary Password" onClose={onClose}>
      <p style={{ fontSize: "0.875rem", marginBottom: "1rem" }}>
        The password for <strong>{accountLabel}</strong> was reset. Give them this temporary
        password; they will have to choose their own at the next sign-in.
      </p>
      <div
        style={{
          display: "flex",
          gap: "0.5rem",
          alignItems: "center",
          padding: "0.75rem",
          border: "1px solid var(--erp-border)",
          borderRadius: "6px",
          background: "var(--erp-surface-subtle)",
        }}
      >
        <code style={{ flex: 1, fontSize: "1rem", wordBreak: "break-all" }}>{temporaryPassword}</code>
        <button type="button" className="erp-btn erp-btn-secondary" onClick={copy}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <p style={{ fontSize: "0.8125rem", color: "#b45309", marginTop: "1rem" }}>
        This is shown only once. It cannot be displayed again after you close this box. Every
        device the account was signed in on has been signed out.
      </p>
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
