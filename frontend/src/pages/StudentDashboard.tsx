import React, { useCallback, useEffect, useState } from "react";
import { api } from "../services";
import type {
  StudentAttendanceDashboardResponse,
  UserResponse,
} from "../types";
import "./student-dashboard.css";

interface StudentDashboardProps {
  user: UserResponse;
  onLogout: () => void;
  onNavigate?: (path: string) => void;
  activeNavId?: string;
  onSelectNav?: (navId: string) => void;
}

export const StudentDashboard: React.FC<StudentDashboardProps> = ({
  user,
  activeNavId = "dashboard",
  onSelectNav,
}) => {
  const [data, setData] = useState<StudentAttendanceDashboardResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const fetchDashboard = useCallback(async () => {
    setLoading(true);
    setErrorMessage(null);

    try {
      const resp = await api.getStudentDashboard();
      setData(resp);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(msg || "Unable to load student attendance data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  if (loading) {
    return (
      <div className="erp-loading-state">
        <div className="spinner" style={{ width: "32px", height: "32px", border: "3px solid #e2e8f0", borderTopColor: "#1d4ed8", borderRadius: "50%" }} />
        <p style={{ marginTop: "1rem", color: "var(--erp-text-muted)", fontSize: "0.875rem" }}>
          Loading your academic records...
        </p>
      </div>
    );
  }

  const profile = data?.profile;
  const overallPresent = data?.overall_present ?? 0;
  const overallTotal = data?.overall_total ?? 0;
  const overallPct = data?.overall_percentage ?? 0;
  const subjects = data?.subjects ?? [];
  const history = data?.history ?? [];

  // Determine time of day greeting
  const getGreeting = () => {
    const hour = new Date().getHours();
    if (hour < 12) return "Good morning";
    if (hour < 17) return "Good afternoon";
    return "Good evening";
  };

  const studentFirstName = profile?.name ? profile.name.split(" ")[0] : user.email.split("@")[0];

  // 1. DASHBOARD VIEW (Section 3)
  const renderDashboardView = () => (
    <div className="erp-student-dashboard">
      {/* Greeting Header */}
      <div className="erp-page-header">
        <h1 className="erp-page-title">
          {getGreeting()}, {studentFirstName}
        </h1>
        <p className="erp-page-subtitle">
          {profile?.branch || "Data Science"} • Section {profile?.section || "B"} • Roll No: {profile?.roll_number || "—"}
        </p>
      </div>

      {/* Attendance Summary Banner (Overall Attendance + Present Classes) */}
      <div className="erp-student-overview-card">
        <div className="erp-overview-stat">
          <span className="erp-stat-label">Overall Attendance</span>
          <span className={`erp-stat-number ${overallPct >= 75 ? "text-present" : "text-shortage"}`}>
            {overallPct}%
          </span>
          <div className="erp-progress-track">
            <div
              className={`erp-progress-bar ${overallPct >= 75 ? "bar-present" : "bar-shortage"}`}
              style={{ width: `${Math.min(overallPct, 100)}%` }}
            />
          </div>
          <span className="erp-stat-subtext">
            {overallPct >= 75 ? "Meets university 75% minimum criteria" : "Attendance shortage alert (< 75%)"}
          </span>
        </div>

        <div className="erp-overview-stat">
          <span className="erp-stat-label">Present Classes</span>
          <span className="erp-stat-number erp-stat-present-count">
            {overallPresent} <span className="erp-stat-total">/ {overallTotal}</span>
          </span>
          <div style={{ height: "6px" }} />
          <span className="erp-stat-subtext">Verified classroom lectures</span>
        </div>
      </div>

      {/* My Subjects Clean Table (Section 3) */}
      <div className="erp-section" style={{ marginTop: "1.75rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.85rem" }}>
          <h2 className="erp-section-title" style={{ margin: 0 }}>My Subjects</h2>
          <button
            type="button"
            className="erp-link-btn"
            onClick={() => onSelectNav && onSelectNav("attendance")}
          >
            View Full Breakdown →
          </button>
        </div>

        {subjects.length === 0 ? (
          <div className="erp-empty-box">No finalized subject attendance sessions recorded yet.</div>
        ) : (
          <div className="erp-table-container">
            <table className="erp-table">
              <thead>
                <tr>
                  <th>Subject</th>
                  <th>Attendance %</th>
                  <th style={{ width: "35%" }}>Progress</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {subjects.map((sub, idx) => {
                  const isSafe = sub.percentage >= 75;
                  return (
                    <tr key={idx}>
                      <td style={{ fontWeight: 600 }}>{sub.subject}</td>
                      <td style={{ fontWeight: 700, color: isSafe ? "#15803d" : "#b91c1c" }}>
                        {sub.percentage}%
                      </td>
                      <td>
                        <div className="erp-mini-track">
                          <div
                            className={`erp-mini-bar ${isSafe ? "bar-present" : "bar-shortage"}`}
                            style={{ width: `${Math.min(sub.percentage, 100)}%` }}
                          />
                        </div>
                      </td>
                      <td>
                        <span className={`status-badge ${isSafe ? "present" : "absent"}`}>
                          {isSafe ? "Satisfied" : "Shortage"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );

  // 2. MY ATTENDANCE VIEW (Detailed Subject Breakdown)
  const renderAttendanceView = () => (
    <div className="erp-student-attendance-view">
      <div className="erp-page-header">
        <h1 className="erp-page-title">My Attendance Breakdown</h1>
        <p className="erp-page-subtitle">Academic Year 2025–26 • Subject-wise presence & shortage criteria</p>
      </div>

      <div className="erp-table-container">
        <table className="erp-table">
          <thead>
            <tr>
              <th>Subject</th>
              <th>Classes Held</th>
              <th>Classes Attended</th>
              <th>Absent</th>
              <th>Attendance Rate</th>
              <th>Requirement</th>
            </tr>
          </thead>
          <tbody>
            {subjects.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ textAlign: "center", padding: "2rem", color: "var(--erp-text-muted)" }}>
                  No subject attendance sessions recorded yet.
                </td>
              </tr>
            ) : (
              subjects.map((sub, idx) => {
                const isSafe = sub.percentage >= 75;
                const absentCount = Math.max(0, sub.total - sub.present);
                return (
                  <tr key={idx}>
                    <td style={{ fontWeight: 600 }}>{sub.subject}</td>
                    <td>{sub.total}</td>
                    <td style={{ color: "#15803d", fontWeight: 600 }}>{sub.present}</td>
                    <td style={{ color: "#b91c1c", fontWeight: 600 }}>{absentCount}</td>
                    <td style={{ fontWeight: 700, color: isSafe ? "#15803d" : "#b91c1c" }}>
                      {sub.percentage}%
                    </td>
                    <td>
                      <span className={`status-badge ${isSafe ? "present" : "absent"}`}>
                        {isSafe ? "Satisfied (≥75%)" : "Shortage (<75%)"}
                      </span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );

  // 3. ATTENDANCE HISTORY VIEW
  const renderHistoryView = () => (
    <div className="erp-student-history-view">
      <div className="erp-page-header">
        <h1 className="erp-page-title">Attendance History</h1>
        <p className="erp-page-subtitle">Chronological record of class attendance sessions</p>
      </div>

      {history.length === 0 ? (
        <div className="erp-empty-box">No past attendance session records available.</div>
      ) : (
        <div className="erp-table-container">
          <table className="erp-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Subject / Course</th>
                <th>Class</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {history.map((item, idx) => {
                const isPresent = item.status === "PRESENT";
                return (
                  <tr key={idx}>
                    <td style={{ color: "var(--erp-text-muted)" }}>{item.date_str}</td>
                    <td style={{ fontWeight: 600 }}>{item.course_name || item.subject}</td>
                    <td>{item.class_code}</td>
                    <td>
                      <span className={`status-badge ${isPresent ? "present" : "absent"}`}>
                        {isPresent ? "✓ PRESENT" : "— ABSENT"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );

  // 4. STUDENT PROFILE VIEW (Section 4 Exact Layout)
  const renderProfileView = () => (
    <div className="erp-student-profile-view" style={{ maxWidth: "640px", margin: "0 auto" }}>
      <div className="erp-page-header" style={{ textAlign: "center" }}>
        <h1 className="erp-page-title">Student Profile</h1>
        <p className="erp-page-subtitle">Academic Credentials & Student Identity</p>
      </div>

      <div className="erp-card" style={{ padding: "2.25rem" }}>
        {/* Prominent Profile Photo */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginBottom: "1.75rem" }}>
          {profile?.photo_url ? (
            <img
              src={profile.photo_url}
              alt={profile.name}
              style={{
                width: "96px",
                height: "96px",
                borderRadius: "50%",
                objectFit: "cover",
                border: "3px solid var(--erp-primary)",
                boxShadow: "0 2px 8px rgba(0, 0, 0, 0.1)",
              }}
            />
          ) : (
            <div
              style={{
                width: "96px",
                height: "96px",
                borderRadius: "50%",
                background: "var(--erp-primary-light)",
                border: "2px solid var(--erp-primary-border)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: "2.5rem",
                color: "var(--erp-primary)",
                fontWeight: 700,
              }}
            >
              {profile?.name ? profile.name.charAt(0) : "S"}
            </div>
          )}

          <h2 style={{ fontSize: "1.35rem", fontWeight: 700, color: "var(--erp-navy)", marginTop: "0.85rem", marginBottom: "0.15rem" }}>
            {profile?.name || user.email}
          </h2>
          <div style={{ fontSize: "0.875rem", color: "var(--erp-text-muted)" }}>
            Student ID: <span style={{ fontFamily: "var(--font-mono)", fontWeight: 600, color: "var(--erp-text-main)" }}>{profile?.student_id || "DS202601"}</span>
          </div>
        </div>

        {/* Organized Information into Logical Sections (Section 4) */}
        <div style={{ display: "flex", flexDirection: "column", gap: "0.85rem", fontSize: "0.875rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "0.6rem 0", borderBottom: "1px solid var(--erp-border)" }}>
            <span style={{ color: "var(--erp-text-muted)" }}>ERP / Roll Number:</span>
            <strong style={{ fontFamily: "var(--font-mono)" }}>{profile?.roll_number || "—"}</strong>
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", padding: "0.6rem 0", borderBottom: "1px solid var(--erp-border)" }}>
            <span style={{ color: "var(--erp-text-muted)" }}>Branch:</span>
            <strong>{profile?.branch || "Data Science"}</strong>
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", padding: "0.6rem 0", borderBottom: "1px solid var(--erp-border)" }}>
            <span style={{ color: "var(--erp-text-muted)" }}>Section:</span>
            <strong>Section {profile?.section || "B"}</strong>
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", padding: "0.6rem 0", borderBottom: "1px solid var(--erp-border)" }}>
            <span style={{ color: "var(--erp-text-muted)" }}>Email Address:</span>
            <strong>{profile?.email || user.email}</strong>
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", padding: "0.6rem 0" }}>
            <span style={{ color: "var(--erp-text-muted)" }}>Face Biometric Status:</span>
            <span className="status-badge present">
              {profile?.has_biometric ? "Enrolled ✓" : "Registered"}
            </span>
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <div className="erp-student-container">
      {errorMessage && (
        <div className="alert-banner error" style={{ marginBottom: "1.5rem" }}>
          <span>{errorMessage}</span>
          <button
            onClick={() => setErrorMessage(null)}
            style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", fontWeight: 700 }}
          >
            ✕
          </button>
        </div>
      )}

      {/* Render view based on active sidebar tab */}
      {activeNavId === "dashboard" && renderDashboardView()}
      {activeNavId === "attendance" && renderAttendanceView()}
      {activeNavId === "history" && renderHistoryView()}
      {activeNavId === "profile" && renderProfileView()}
    </div>
  );
};
