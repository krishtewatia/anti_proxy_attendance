import React from "react";
import type { UserResponse } from "../../types";
import { APP_NAME } from "../../config/app.ts";

const row: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  padding: "0.5rem 0",
  borderBottom: "1px solid var(--erp-border)",
};
const label: React.CSSProperties = { color: "var(--erp-text-muted)" };

export const ProfileTab: React.FC<{ user: UserResponse; onChangePassword?: () => void }> = ({
  user,
  onChangePassword,
}) => (
  <div style={{ maxWidth: "600px", margin: "0 auto" }}>
    <div className="erp-page-header" style={{ textAlign: "center" }}>
      <h1 className="erp-page-title">Administrator Profile</h1>
      <p className="erp-page-subtitle">{APP_NAME}</p>
    </div>

    <div className="erp-card" style={{ padding: "2rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "1.25rem", marginBottom: "1.5rem" }}>
        <div
          style={{
            width: "64px",
            height: "64px",
            borderRadius: "50%",
            background: "var(--erp-primary-light)",
            border: "2px solid var(--erp-primary-border)",
            color: "var(--erp-primary)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: "1.5rem",
            fontWeight: 700,
          }}
        >
          A
        </div>
        <div>
          <h2 style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--erp-navy)", margin: 0 }}>
            System Administrator
          </h2>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", fontSize: "0.875rem" }}>
        <div style={row}>
          <span style={label}>Role:</span>
          <span className="erp-role-pill role-admin">Administrator</span>
        </div>
        <div style={row}>
          <span style={label}>Official Email:</span>
          <strong>{user.email}</strong>
        </div>
        <div style={{ ...row, borderBottom: "none" }}>
          <span style={label}>System Status:</span>
          <span className="status-badge present">Online</span>
        </div>
      </div>

      {onChangePassword && (
        <button
          type="button"
          className="erp-btn erp-btn-secondary"
          style={{ marginTop: "1.5rem" }}
          onClick={onChangePassword}
        >
          Change Password
        </button>
      )}
    </div>
  </div>
);
