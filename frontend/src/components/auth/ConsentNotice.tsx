import React from "react";
import type { ConsentNotice as Notice } from "../../utils/registration.ts";

interface ConsentNoticeProps {
  notice: Notice;
  accepted: boolean;
  onChange: (accepted: boolean) => void;
  disabled?: boolean;
}

// The short notice a student reads and accepts before sending a photo of their face.
export const ConsentNotice: React.FC<ConsentNoticeProps> = ({ notice, accepted, onChange, disabled }) => (
  <div
    className="consent-notice"
    style={{
      border: "1px solid var(--erp-border)",
      borderRadius: "8px",
      padding: "0.75rem 0.85rem",
      background: "var(--erp-surface-hover)",
      fontSize: "0.8rem",
      color: "var(--erp-text-muted)",
    }}
  >
    <div style={{ fontWeight: 600, color: "var(--erp-text-main)", marginBottom: "0.35rem" }}>{notice.title}</div>
    <ul style={{ margin: "0 0 0.5rem 1rem", padding: 0, display: "grid", gap: "0.25rem" }}>
      {notice.points.map((point) => (
        <li key={point}>{point}</li>
      ))}
    </ul>
    <label style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start", cursor: "pointer", color: "var(--erp-text-main)" }}>
      <input
        type="checkbox"
        checked={accepted}
        onChange={(e) => onChange(e.target.checked)}
        disabled={disabled}
        style={{ marginTop: "0.15rem" }}
      />
      <span>I have read this and agree to my photos being used to mark my attendance.</span>
    </label>
  </div>
);
