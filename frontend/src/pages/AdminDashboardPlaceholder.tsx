import React from "react";
import type { UserResponse } from "../types";

interface Props {
  user: UserResponse;
  onLogout: () => void;
}

export const AdminDashboardPlaceholder: React.FC<Props> = ({ user, onLogout }) => {
  return (
    <div className="dashboard-placeholder-container">
      <div className="dashboard-card">
        <span className="dashboard-role-badge badge-admin">Admin Portal</span>
        <h1 className="dashboard-title">Admin Dashboard</h1>
        <p className="dashboard-subtitle">
          System administration, audit logs, and platform telemetry
        </p>

        <div className="dashboard-user-info">
          <div className="info-row">
            <span className="info-label">Administrator ID:</span>
            <span className="info-value">{user.user_id}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Email:</span>
            <span className="info-value">{user.email}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Role:</span>
            <span className="info-value">{user.role}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Privileges:</span>
            <span className="info-value" style={{ color: "#f59e0b" }}>System Root</span>
          </div>
        </div>

        <button type="button" className="btn-signout" onClick={onLogout}>
          Sign Out
        </button>
      </div>
    </div>
  );
};
