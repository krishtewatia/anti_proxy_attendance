import React from "react";
import { type AdminData } from "./adminShared.ts";

export const OverviewTab: React.FC<AdminData> = ({ students, teachers, academic, sessions }) => {
  const activeClassesCount = academic?.classes?.length || 8;
  const activeSessions = sessions.filter((s) => s.status === "ACTIVE");

  return (
    <div>
      <div className="erp-page-header">
        <h1 className="erp-page-title">Institutional Overview</h1>
        <p className="erp-page-subtitle">College Administration & Academic Health Metrics</p>
      </div>

      <div className="erp-metrics-grid">
        <div className="erp-metric-card">
          <span className="erp-metric-label">Total Students</span>
          <span className="erp-metric-value">{students.length}</span>
          <span className="erp-metric-subtext">Active enrolled students</span>
        </div>
        <div className="erp-metric-card">
          <span className="erp-metric-label">Total Teachers</span>
          <span className="erp-metric-value">{teachers.length}</span>
          <span className="erp-metric-subtext">Faculty & instructors</span>
        </div>
        <div className="erp-metric-card">
          <span className="erp-metric-label">Active Classes</span>
          <span className="erp-metric-value">{activeClassesCount}</span>
          <span className="erp-metric-subtext">Registered academic sections</span>
        </div>
        <div className="erp-metric-card">
          <span className="erp-metric-label">Today's Sessions</span>
          <span className="erp-metric-value">{sessions.length}</span>
          <span className="erp-metric-subtext">Attendance sessions logged</span>
        </div>
      </div>

      <div className="erp-section" style={{ marginBottom: "2rem" }}>
        <h2 className="erp-section-title">Currently Active Sessions</h2>
        {activeSessions.length === 0 ? (
          <div className="erp-empty-box">No classroom sessions currently active.</div>
        ) : (
          <div className="erp-table-container">
            <table className="erp-table">
              <thead>
                <tr>
                  <th>Subject / Course</th>
                  <th>Class</th>
                  <th>Room</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {activeSessions.map((s) => (
                  <tr key={s.session_id}>
                    <td style={{ fontWeight: 600 }}>{s.course_name}</td>
                    <td>{s.class_code || "DS-B"}</td>
                    <td>{s.classroom_id}</td>
                    <td>
                      <span className="status-badge active">In Progress</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="erp-section">
        <h2 className="erp-section-title">Recent Attendance Sessions</h2>
        {sessions.length === 0 ? (
          <div className="erp-empty-box">No recorded attendance sessions yet.</div>
        ) : (
          <div className="erp-table-container">
            <table className="erp-table">
              <thead>
                <tr>
                  <th>Course</th>
                  <th>Class</th>
                  <th>Room</th>
                  <th>Date</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {sessions.slice(0, 5).map((s) => (
                  <tr key={s.session_id}>
                    <td style={{ fontWeight: 600 }}>{s.course_name}</td>
                    <td>{s.class_code || "DS-B"}</td>
                    <td>{s.classroom_id}</td>
                    <td>{new Date(s.start_time).toLocaleDateString()}</td>
                    <td>
                      <span className={`status-badge ${s.status === "ACTIVE" ? "active" : "completed"}`}>
                        {s.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
