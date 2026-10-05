import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../services";
import type {
  AttendanceSummaryItem,
  TeacherDashboardResponse,
  TeacherSessionSummaryItem,
  UserResponse,
} from "../types";
import "./teacher-attendance-flow.css";

interface TeacherAttendanceFlowProps {
  user: UserResponse;
  onLogout: () => void;
  onNavigate?: (path: string) => void;
  activeNavId?: string;
  onSelectNav?: (navId: string) => void;
}

type Step = 1 | 2 | 3;

interface RecognitionCallout {
  name: string;
  status: "PRESENT" | "ALREADY_PRESENT" | "UNKNOWN" | "IDLE";
}

export const TeacherAttendanceFlow: React.FC<TeacherAttendanceFlowProps> = ({
  user,
  activeNavId = "dashboard",
  onSelectNav,
}) => {
  const [step, setStep] = useState<Step>(1);

  // Teacher dashboard state
  const [dashboardData, setDashboardData] = useState<TeacherDashboardResponse | null>(null);
  const [assignedClasses, setAssignedClasses] = useState<string[]>(["DS-B", "DS-C"]);
  const [assignedSubjects, setAssignedSubjects] = useState<string[]>([
    "Machine Learning",
    "Computer Networks",
    "DBMS",
  ]);

  const [selectedClass, setSelectedClass] = useState<string>("DS-B");
  const [selectedSubject, setSelectedSubject] = useState<string>("Machine Learning");

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [records, setRecords] = useState<AttendanceSummaryItem[]>([]);
  const [callout, setCallout] = useState<RecognitionCallout>({
    name: "Ready",
    status: "IDLE",
  });
  const [cameraOnline, setCameraOnline] = useState<boolean>(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const prevMarkedCountRef = useRef<number>(0);

  const previewBaseUrl = useMemo(() => {
    if (typeof window !== "undefined") {
      const host = window.location.hostname || "localhost";
      return `http://${host}:8088`;
    }
    return "http://localhost:8088";
  }, []);

  const previewMjpgUrl = `${previewBaseUrl}/preview.mjpg`;

  // Fetch teacher dashboard data
  const fetchTeacherData = async () => {
    try {
      const data = await api.getTeacherDashboard();
      setDashboardData(data);
      if (data.teacher.assigned_classes && data.teacher.assigned_classes.length > 0) {
        setAssignedClasses(data.teacher.assigned_classes);
        setSelectedClass(data.teacher.assigned_classes[0]);
      }
      if (data.teacher.assigned_subjects && data.teacher.assigned_subjects.length > 0) {
        setAssignedSubjects(data.teacher.assigned_subjects);
        setSelectedSubject(data.teacher.assigned_subjects[0]);
      }
    } catch {
      // Fallback defaults
    }
  };

  useEffect(() => {
    fetchTeacherData();
  }, []);

  const totalStudents = records.length;
  const presentCount = records.filter((r) => r.status === "PRESENT").length;

  // ========================================================================
  // STEP 1 -> STEP 2: START ATTENDANCE
  // ========================================================================
  const handleStartAttendance = async () => {
    setLoading(true);
    setErrorMessage(null);
    try {
      const now = new Date();
      const in2h = new Date(now.getTime() + 120 * 60 * 1000);

      // 1. Create Session
      const session = await api.createSession({
        course_name: `${selectedSubject} — ${selectedClass}`,
        classroom_id: "ROOM_101",
        class_code: selectedClass,
        subject: selectedSubject,
        start_time: now.toISOString(),
        end_time: in2h.toISOString(),
        required_presence_percentage: 100.0,
      });

      setSessionId(session.session_id);

      // 2. Start Session
      await api.startSession(session.session_id);

      // 3. Reset Vision Counter and notify active session
      try {
        await fetch(`${previewBaseUrl}/reset`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: session.session_id }),
        });
      } catch {
        // Preview server might be starting up
      }

      // 4. Fetch roster
      const attData = await api.getSessionAttendance(session.session_id);
      setRecords(attData.records);

      setCallout({ name: "Scanning", status: "IDLE" });
      setStep(2);
      if (onSelectNav) onSelectNav("attendance");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(msg || "Failed to start attendance session.");
    } finally {
      setLoading(false);
    }
  };

  // Continue an already active session
  const handleResumeActiveSession = async (activeSess: TeacherSessionSummaryItem) => {
    setLoading(true);
    setErrorMessage(null);
    try {
      setSessionId(activeSess.session_id);
      if (activeSess.class_code) setSelectedClass(activeSess.class_code);
      if (activeSess.subject) setSelectedSubject(activeSess.subject);

      const attData = await api.getSessionAttendance(activeSess.session_id);
      setRecords(attData.records);
      setCallout({ name: "Session Resumed", status: "IDLE" });
      setStep(2);
      if (onSelectNav) onSelectNav("attendance");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(msg || "Failed to resume active session.");
    } finally {
      setLoading(false);
    }
  };

  // View past session
  const handleViewPastSession = async (pastSess: TeacherSessionSummaryItem) => {
    setLoading(true);
    try {
      setSessionId(pastSess.session_id);
      if (pastSess.class_code) setSelectedClass(pastSess.class_code);
      if (pastSess.subject) setSelectedSubject(pastSess.subject);

      const attData = await api.getSessionAttendance(pastSess.session_id);
      setRecords(attData.records);
      setStep(3);
      if (onSelectNav) onSelectNav("attendance");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(msg || "Failed to load past session details.");
    } finally {
      setLoading(false);
    }
  };

  // ========================================================================
  // STEP 2: LIVE POLLING FOR RECOGNIZED FACES
  // ========================================================================
  useEffect(() => {
    if (step !== 2 || !sessionId) return;

    const interval = setInterval(async () => {
      try {
        const statusRes = await fetch(`${previewBaseUrl}/status`);
        if (statusRes.ok) {
          const st = await statusRes.json();
          setCameraOnline(Boolean(st.camera_connected));

          if (st.last_recognized) {
            setCallout({
              name: st.last_recognized,
              status: "PRESENT",
            });
          }
        }
      } catch {
        setCameraOnline(false);
      }

      try {
        const attData = await api.getSessionAttendance(sessionId);
        setRecords(attData.records);

        const currentMarked = (attData.records as AttendanceSummaryItem[]).filter(
          (r: AttendanceSummaryItem) => r.status === "PRESENT"
        ).length;
        if (currentMarked > prevMarkedCountRef.current) {
          prevMarkedCountRef.current = currentMarked;
        }
      } catch {
        // Ignore network jitter
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [step, sessionId, previewBaseUrl]);

  // ========================================================================
  // STEP 2 -> STEP 3: END ATTENDANCE
  // ========================================================================
  const handleEndAttendance = async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      await api.endSession(sessionId);
      const attData = await api.getSessionAttendance(sessionId);
      setRecords(attData.records);
      setStep(3);
      fetchTeacherData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(msg || "Failed to finalize attendance.");
    } finally {
      setLoading(false);
    }
  };

  // ========================================================================
  // STEP 3: MANUAL CORRECTION (PRESENT <-> ABSENT)
  // ========================================================================
  const handleToggleStudentStatus = async (item: AttendanceSummaryItem) => {
    if (!sessionId) return;
    const newStatus = item.status === "PRESENT" ? "ABSENT" : "PRESENT";

    setRecords((prev) =>
      prev.map((r) =>
        r.attendance_id === item.attendance_id ? { ...r, status: newStatus } : r
      )
    );

    try {
      await api.updateAttendanceStatus(sessionId, item.attendance_id, newStatus);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(`Failed to update status for ${item.student_name}: ${msg}`);
      setRecords((prev) =>
        prev.map((r) =>
          r.attendance_id === item.attendance_id ? { ...r, status: item.status } : r
        )
      );
    }
  };

  // CSV Export
  const handleDownloadCsv = () => {
    if (!sessionId) return;
    const host = typeof window !== "undefined" ? window.location.hostname || "localhost" : "localhost";
    const token = api.getToken() || localStorage.getItem("anti_proxy_access_token") || "";
    const url = `http://${host}:8000/api/v1/attendance/${sessionId}/export`;

    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((res) => res.blob())
      .then((blob) => {
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = `${selectedSubject}_${selectedClass}_attendance.csv`;
        link.click();
      })
      .catch(() => {
        alert("Failed to download CSV export.");
      });
  };

  const handleNewAttendance = () => {
    setStep(1);
    setSessionId(null);
    setRecords([]);
    fetchTeacherData();
  };

  const hasActiveSession = Boolean(dashboardData?.active_session);
  const activeSess = dashboardData?.active_session;
  const previousSessions = dashboardData?.previous_sessions ?? [];
  const teacherName = dashboardData?.teacher.name || "Dr. Sharma";

  // Tab 1: Teacher Dashboard
  const renderDashboardView = () => (
    <div className="erp-teacher-dashboard">
      <div className="erp-page-header">
        <h1 className="erp-page-title">Welcome, {teacherName}</h1>
        <p className="erp-page-subtitle">Faculty Attendance & Class Management Portal</p>
      </div>

      {/* Active Session Overview */}
      <div className="erp-section" style={{ marginBottom: "1.75rem" }}>
        <h2 className="erp-section-title">Today's Attendance</h2>
        {hasActiveSession && activeSess ? (
          <div className="erp-active-session-card">
            <div className="erp-active-session-info">
              <span className="status-badge active">Active Session in Progress</span>
              <h3 className="erp-session-course">{activeSess.course_name}</h3>
              <p className="erp-session-stats">
                {activeSess.present_count} / {activeSess.total_students} Students Present
              </p>
            </div>
            <button
              type="button"
              className="erp-btn erp-btn-primary"
              onClick={() => handleResumeActiveSession(activeSess)}
            >
              Continue Active Session →
            </button>
          </div>
        ) : (
          <div className="erp-empty-active-card">
            <div>
              <div className="erp-active-label">Active Session: None</div>
              <div className="erp-active-desc">No ongoing attendance session currently in progress.</div>
            </div>
            <button
              type="button"
              className="erp-btn erp-btn-primary"
              onClick={() => {
                setStep(1);
                if (onSelectNav) onSelectNav("attendance");
              }}
            >
              Start New Attendance
            </button>
          </div>
        )}
      </div>

      {/* Assigned Classes */}
      <div className="erp-section" style={{ marginBottom: "1.75rem" }}>
        <h2 className="erp-section-title">Assigned Classes</h2>
        <div className="erp-classes-grid">
          {assignedClasses.map((cls) => (
            <div key={cls} className="erp-class-card">
              <div className="erp-class-code">{cls}</div>
              <div className="erp-class-dept">Department of Data Science</div>
              <div className="erp-class-subjects">
                {assignedSubjects.join(" • ")}
              </div>
              <button
                type="button"
                className="erp-btn erp-btn-secondary"
                style={{ marginTop: "1rem", width: "100%" }}
                onClick={() => {
                  setSelectedClass(cls);
                  setStep(1);
                  if (onSelectNav) onSelectNav("attendance");
                }}
              >
                Take Attendance
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Recent Attendance Sessions */}
      <div className="erp-section">
        <h2 className="erp-section-title">Recent Attendance Sessions</h2>
        {previousSessions.length === 0 ? (
          <div className="erp-empty-box">No previous attendance sessions recorded yet.</div>
        ) : (
          <div className="erp-table-container">
            <table className="erp-table">
              <thead>
                <tr>
                  <th>Class</th>
                  <th>Subject</th>
                  <th>Present</th>
                  <th>Turnout %</th>
                  <th>Status</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {previousSessions.slice(0, 5).map((ps) => (
                  <tr key={ps.session_id}>
                    <td style={{ fontWeight: 600 }}>{ps.class_code || "DS-B"}</td>
                    <td>{ps.subject || ps.course_name}</td>
                    <td>{ps.present_count} / {ps.total_students}</td>
                    <td style={{ fontWeight: 600, color: ps.attendance_percentage >= 75 ? "#15803d" : "#b91c1c" }}>
                      {ps.attendance_percentage}%
                    </td>
                    <td>
                      <span className="status-badge completed">Completed</span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="erp-btn erp-btn-secondary"
                        style={{ padding: "0.25rem 0.6rem", fontSize: "0.75rem" }}
                        onClick={() => handleViewPastSession(ps)}
                      >
                        View Records
                      </button>
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

  // Tab 2: Attendance Workflow (Screens 1, 2, 3)
  const renderAttendanceWorkflow = () => (
    <div className="erp-attendance-flow">
      {/* SCREEN 1: START ATTENDANCE */}
      {step === 1 && (
        <div className="erp-start-attendance-card">
          <div className="erp-card-header">
            <h1 className="erp-page-title">Start Attendance</h1>
            <p className="erp-page-subtitle">Select class and subject to begin taking attendance.</p>
          </div>

          {hasActiveSession && (
            <div className="erp-alert-box warning" style={{ marginBottom: "1.25rem" }}>
              An active attendance session is already running for {activeSess?.course_name}. Please finish or continue that session.
            </div>
          )}

          <div className="erp-form-stack">
            <div className="form-group">
              <label className="form-label" htmlFor="erp-subject-select">Subject</label>
              <select
                id="erp-subject-select"
                className="erp-select-input"
                value={selectedSubject}
                onChange={(e) => setSelectedSubject(e.target.value)}
                disabled={hasActiveSession || loading}
              >
                {assignedSubjects.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="erp-class-select">Class</label>
              <select
                id="erp-class-select"
                className="erp-select-input"
                value={selectedClass}
                onChange={(e) => setSelectedClass(e.target.value)}
                disabled={hasActiveSession || loading}
              >
                {assignedClasses.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>

            <div style={{ marginTop: "1.5rem" }}>
              <button
                type="button"
                className="erp-btn erp-btn-primary"
                onClick={handleStartAttendance}
                disabled={hasActiveSession || loading}
                style={{ width: "100%", padding: "0.85rem", fontSize: "1rem" }}
              >
                {loading ? "Starting Attendance Session..." : "START ATTENDANCE"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* SCREEN 2: LIVE ATTENDANCE (Matches Section 7 Layout) */}
      {step === 2 && (
        <div className="erp-live-attendance-page">
          <div className="erp-live-header">
            <div>
              <h1 className="erp-live-course">{selectedSubject}</h1>
              <div className="erp-live-class-code">{selectedClass}</div>
            </div>
            <div className="erp-live-stats-badge">
              <span className={`erp-camera-status-dot ${cameraOnline ? "online" : "offline"}`} />
              <span style={{ fontWeight: 600 }}>{cameraOnline ? "Live Camera" : "Connecting Camera..."}</span>
            </div>
          </div>

          {/* Side-by-side Section 7 Layout */}
          <div className="erp-live-grid">
            {/* Left: LIVE CAMERA */}
            <div className="erp-camera-pane">
              <div className="erp-camera-viewport" style={{ position: "relative" }}>
                <img
                  src={previewMjpgUrl}
                  alt="Live Attendance Camera Viewport"
                  className="erp-camera-stream"
                  onError={() => setCameraOnline(false)}
                  onLoad={() => setCameraOnline(true)}
                />

                {!cameraOnline && (
                  <div
                    style={{
                      position: "absolute",
                      inset: 0,
                      backgroundColor: "rgba(15, 23, 42, 0.92)",
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "center",
                      justifyContent: "center",
                      padding: "1.5rem",
                      textAlign: "center",
                      color: "#f8fafc",
                      zIndex: 10,
                    }}
                  >
                    <div style={{ fontSize: "1.1rem", fontWeight: 600, marginBottom: "0.5rem" }}>
                      Camera unavailable
                    </div>
                    <div style={{ fontSize: "0.875rem", color: "#94a3b8", maxWidth: "280px", lineHeight: 1.4 }}>
                      Please make sure the webcam is connected and try again.
                    </div>
                  </div>
                )}

                {/* Subtle recognition feedback */}
                {callout.status === "PRESENT" && (
                  <div className="erp-subtle-present-callout">
                    ✓ {callout.name} marked present
                  </div>
                )}
              </div>
              <div className="erp-camera-footer">
                Live Classroom Camera Feed
              </div>
            </div>

            {/* Right: Students Present */}
            <div className="erp-students-present-pane">
              <div className="erp-roster-header">
                <div>
                  <h3 className="erp-roster-title">Students Present</h3>
                  <div className="erp-roster-count">{presentCount} / {totalStudents}</div>
                </div>
              </div>

              <div className="erp-students-list">
                {records.map((student) => {
                  const isPresent = student.status === "PRESENT";
                  return (
                    <div
                      key={student.identity}
                      className={`erp-student-row ${isPresent ? "row-present" : "row-absent"}`}
                    >
                      <div className="erp-student-details">
                        <span className="erp-student-name">{student.student_name}</span>
                        <span className="erp-student-roll">{student.student_id}</span>
                      </div>
                      <span className={`status-badge ${isPresent ? "present" : "absent"}`}>
                        {isPresent ? "✓ PRESENT" : "— ABSENT"}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Centered End Attendance Button */}
          <div className="erp-live-action-bar">
            <button
              type="button"
              className="erp-btn erp-btn-danger"
              onClick={handleEndAttendance}
              disabled={loading}
              style={{ minWidth: "220px", padding: "0.85rem 1.5rem", fontSize: "1rem" }}
            >
              {loading ? "Finalizing Attendance..." : "END ATTENDANCE"}
            </button>
          </div>
        </div>
      )}

      {/* SCREEN 3: ATTENDANCE COMPLETE (Matches Section 9 Layout) */}
      {step === 3 && (
        <div className="erp-complete-page">
          <div className="erp-complete-card">
            <div className="erp-complete-header">
              <div className="erp-complete-check">✓</div>
              <h1 className="erp-complete-title">Attendance Complete</h1>
              <div className="erp-complete-meta">
                <strong>{selectedSubject}</strong> • {selectedClass}
              </div>
              <div className="erp-complete-stats">
                {presentCount} / {totalStudents} Present ({totalStudents > 0 ? Math.round((presentCount / totalStudents) * 100) : 0}%)
              </div>
            </div>

            {/* Clean Attendance Table */}
            <div className="erp-table-container" style={{ margin: "1.5rem 0" }}>
              <table className="erp-table">
                <thead>
                  <tr>
                    <th>Student ID</th>
                    <th>Student Name</th>
                    <th>Status</th>
                    <th>Correction</th>
                  </tr>
                </thead>
                <tbody>
                  {records.map((student) => {
                    const isPresent = student.status === "PRESENT";
                    return (
                      <tr key={student.identity}>
                        <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.8125rem" }}>
                          {student.student_id}
                        </td>
                        <td style={{ fontWeight: 600 }}>{student.student_name}</td>
                        <td>
                          <span className={`status-badge ${isPresent ? "present" : "absent"}`}>
                            {student.status}
                          </span>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="erp-btn erp-btn-secondary"
                            style={{ padding: "0.25rem 0.6rem", fontSize: "0.75rem" }}
                            onClick={() => handleToggleStudentStatus(student)}
                          >
                            Mark {isPresent ? "Absent" : "Present"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Actions */}
            <div className="erp-complete-actions">
              <button
                type="button"
                className="erp-btn erp-btn-primary"
                onClick={handleDownloadCsv}
                style={{ flex: 1, padding: "0.75rem" }}
              >
                📥 Download CSV
              </button>
              <button
                type="button"
                className="erp-btn erp-btn-secondary"
                onClick={handleNewAttendance}
                style={{ flex: 1, padding: "0.75rem" }}
              >
                New Attendance
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  // Tab 3: My Classes
  const renderClassesView = () => (
    <div className="erp-classes-view">
      <div className="erp-page-header">
        <h1 className="erp-page-title">My Assigned Classes</h1>
        <p className="erp-page-subtitle">Academic Year 2025–26 • Term II Teaching Allocations</p>
      </div>

      <div className="erp-classes-grid">
        {assignedClasses.map((cls) => (
          <div key={cls} className="erp-class-card">
            <div className="erp-class-code">{cls}</div>
            <div className="erp-class-dept">Department of Data Science</div>
            <div className="erp-class-subjects">
              Subjects: {assignedSubjects.join(", ")}
            </div>
            <div style={{ marginTop: "1rem", fontSize: "0.8125rem", color: "var(--erp-text-muted)" }}>
              Section DS-B • 4 Students Registered
            </div>
            <button
              type="button"
              className="erp-btn erp-btn-primary"
              style={{ marginTop: "1rem", width: "100%" }}
              onClick={() => {
                setSelectedClass(cls);
                setStep(1);
                if (onSelectNav) onSelectNav("attendance");
              }}
            >
              Take Attendance
            </button>
          </div>
        ))}
      </div>
    </div>
  );

  // Tab 4: Previous Sessions
  const renderSessionsView = () => (
    <div className="erp-sessions-view">
      <div className="erp-page-header">
        <h1 className="erp-page-title">Previous Attendance Sessions</h1>
        <p className="erp-page-subtitle">Historical records and completed attendance sheets.</p>
      </div>

      {previousSessions.length === 0 ? (
        <div className="erp-empty-box">No finalized attendance sessions recorded yet.</div>
      ) : (
        <div className="erp-table-container">
          <table className="erp-table">
            <thead>
              <tr>
                <th>Subject</th>
                <th>Class</th>
                <th>Students</th>
                <th>Present</th>
                <th>Absent</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {previousSessions.map((ps) => {
                const absent = Math.max(0, ps.total_students - ps.present_count);
                return (
                  <tr key={ps.session_id}>
                    <td style={{ fontWeight: 600 }}>{ps.subject || ps.course_name}</td>
                    <td>{ps.class_code || "DS-B"}</td>
                    <td>{ps.total_students}</td>
                    <td style={{ color: "#15803d", fontWeight: 600 }}>{ps.present_count}</td>
                    <td style={{ color: "#b91c1c", fontWeight: 600 }}>{absent}</td>
                    <td>
                      <span className="status-badge completed">Completed</span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="erp-btn erp-btn-secondary"
                        style={{ padding: "0.25rem 0.6rem", fontSize: "0.75rem" }}
                        onClick={() => handleViewPastSession(ps)}
                      >
                        View Details
                      </button>
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

  // Tab 5: Profile
  const renderProfileView = () => (
    <div className="erp-profile-view" style={{ maxWidth: "600px", margin: "0 auto" }}>
      <div className="erp-page-header" style={{ textAlign: "center" }}>
        <h1 className="erp-page-title">Faculty Profile</h1>
        <p className="erp-page-subtitle">Academic Credentials & Assigned Department</p>
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
            {teacherName.charAt(0)}
          </div>
          <div>
            <h2 style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--erp-text-main)", margin: 0 }}>
              {teacherName}
            </h2>
            <div style={{ color: "var(--erp-text-muted)", fontSize: "0.875rem" }}>
              Department of Data Science
            </div>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", fontSize: "0.875rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "0.5rem 0", borderBottom: "1px solid var(--erp-border)" }}>
            <span style={{ color: "var(--erp-text-muted)" }}>Faculty ID:</span>
            <strong style={{ fontFamily: "var(--font-mono)" }}>T001</strong>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "0.5rem 0", borderBottom: "1px solid var(--erp-border)" }}>
            <span style={{ color: "var(--erp-text-muted)" }}>Department:</span>
            <strong>Data Science</strong>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "0.5rem 0", borderBottom: "1px solid var(--erp-border)" }}>
            <span style={{ color: "var(--erp-text-muted)" }}>Assigned Classes:</span>
            <strong>{assignedClasses.join(", ")}</strong>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "0.5rem 0", borderBottom: "1px solid var(--erp-border)" }}>
            <span style={{ color: "var(--erp-text-muted)" }}>Institutional Email:</span>
            <strong>{user.email}</strong>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "0.5rem 0" }}>
            <span style={{ color: "var(--erp-text-muted)" }}>Academic Status:</span>
            <span className="status-badge present">Active Faculty</span>
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <div className="erp-teacher-container">
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
      {activeNavId === "attendance" && renderAttendanceWorkflow()}
      {activeNavId === "classes" && renderClassesView()}
      {activeNavId === "sessions" && renderSessionsView()}
      {activeNavId === "profile" && renderProfileView()}
    </div>
  );
};
