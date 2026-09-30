import React from "react";
import type { UserResponse } from "../types";

interface Props {
  user: UserResponse;
  onLogout: () => void;
}

export const StudentDashboardPlaceholder: React.FC<Props> = ({ user, onLogout }) => {
  return (
    <div className="dashboard-placeholder-container">
      <div className="dashboard-card">
        <span className="dashboard-role-badge badge-student">Student Portal</span>
        <h1 className="dashboard-title">Student Dashboard</h1>
        <p className="dashboard-subtitle">
          Personal presence timeline and session attendance logs
        </p>

        <div className="dashboard-user-info">
          <div className="info-row">
            <span className="info-label">Student ID:</span>
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
            <span className="info-label">Status:</span>
            <span className="info-value" style={{ color: "#06b6d4" }}>Authenticated</span>
          </div>
        </div>

        <button type="button" className="btn-signout" onClick={onLogout}>
          Sign Out
        </button>
      </div>
    </div>
  );
};
