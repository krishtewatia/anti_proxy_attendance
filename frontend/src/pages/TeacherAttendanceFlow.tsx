import React, { useEffect, useRef, useState } from "react";
import { api, getApiBaseUrl } from "../services";
import type {
  AttendanceSummaryItem,
  TeacherDashboardResponse,
  TeacherSessionSummaryItem,
  UserResponse,
} from "../types";
import { getFaceOverlayStyle, hasSpoof } from "../utils/faceOverlay";
import "./teacher-attendance-flow.css";
import { paginate, sessionStatusBadgeClass, sessionStatusLabel } from "../utils/sessions.ts";
import { formatDate, formatSessionTurnout } from "../utils/dates.ts";
import { Pagination } from "../components/common/Pagination";

const SESSIONS_PAGE_SIZE = 15;

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
  // The past session being viewed was never taken: nobody in it is absent.
  const [viewedNotTaken, setViewedNotTaken] = useState(false);

  // Teacher dashboard state
  const [dashboardData, setDashboardData] = useState<TeacherDashboardResponse | null>(null);
  const [sessionsPageNumber, setSessionsPageNumber] = useState(1);
  // What an administrator assigned to this teacher. Empty until loaded, and
  // empty if nothing is assigned: never a made-up class or subject.
  const [assignedClasses, setAssignedClasses] = useState<string[]>([]);
  const [assignedSubjects, setAssignedSubjects] = useState<string[]>([]);

  const [selectedClass, setSelectedClass] = useState<string>("");
  const [selectedSubject, setSelectedSubject] = useState<string>("");

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [records, setRecords] = useState<AttendanceSummaryItem[]>([]);
  const [callout, setCallout] = useState<RecognitionCallout>({
    name: "Ready",
    status: "IDLE",
  });
  const [spoofDetected, setSpoofDetected] = useState(false);
  const [cameraOnline, setCameraOnline] = useState<boolean>(false);
  const [cameraStatus, setCameraStatus] = useState<
    "FREE" | "REQUESTING_CAMERA" | "CAMERA_READY" | "ATTENDANCE_ACTIVE" | "STOPPING_CAMERA" | "PERMISSION_DENIED" | "UNAVAILABLE"
  >("FREE");
  const [cameraErrorMessage, setCameraErrorMessage] = useState<string | null>(null);
  const [availableCameras, setAvailableCameras] = useState<MediaDeviceInfo[]>([]);
  const [selectedCameraId, setSelectedCameraId] = useState<string>("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const overlayCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const isProcessingRef = useRef<boolean>(false);
  const prevMarkedCountRef = useRef<number>(0);

  // Enumerate available video inputs (Laptop built-in, USB webcams)
  const enumerateCameras = async () => {
    try {
      if (typeof navigator !== "undefined" && navigator.mediaDevices?.enumerateDevices) {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const videoInputs = devices.filter((d) => d.kind === "videoinput");
        setAvailableCameras(videoInputs);
        if (videoInputs.length > 0 && !selectedCameraId) {
          setSelectedCameraId(videoInputs[0].deviceId);
        }
      }
    } catch {
      // Fallback
    }
  };

  useEffect(() => {
    enumerateCameras();
    const handleDeviceChange = () => {
      enumerateCameras();
    };
    navigator.mediaDevices?.addEventListener("devicechange", handleDeviceChange);
    return () => {
      navigator.mediaDevices?.removeEventListener("devicechange", handleDeviceChange);
      if (mediaStreamRef.current) {
        mediaStreamRef.current.getTracks().forEach((t) => t.stop());
      }
    };
  }, []);

  // Start physical webcam stream via browser navigator.mediaDevices.getUserMedia()
  const startCameraStream = async (): Promise<boolean> => {
    setCameraStatus("REQUESTING_CAMERA");
    setCameraErrorMessage(null);

    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((t) => t.stop());
      mediaStreamRef.current = null;
    }

    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error("Browser does not support getUserMedia camera access.");
      }

      const constraints: MediaStreamConstraints = {
        video: selectedCameraId
          ? { deviceId: { exact: selectedCameraId }, width: { ideal: 640 }, height: { ideal: 480 } }
          : { width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false,
      };

      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      mediaStreamRef.current = stream;
      setCameraOnline(true);
      setCameraStatus("CAMERA_READY");

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.play().catch(() => {});
      }

      // Re-populate friendly camera device labels now that permission is active
      enumerateCameras();
      return true;
    } catch (err: unknown) {
      setCameraOnline(false);
      const errorName = err instanceof Error ? err.name : "";
      if (errorName === "NotAllowedError" || errorName === "PermissionDeniedError") {
        setCameraErrorMessage("Please allow camera access in your browser settings.");
        setCameraStatus("PERMISSION_DENIED");
      } else {
        setCameraErrorMessage("Please check that your webcam is connected.");
        setCameraStatus("UNAVAILABLE");
      }
      return false;
    }
  };

  // Clear recognition overlay canvas
  const clearOverlay = () => {
    const canvas = overlayCanvasRef.current;
    if (canvas) {
      const ctx = canvas.getContext("2d");
      if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
  };

  // Stop physical webcam stream and release hardware completely
  const stopCameraStream = () => {
    setCameraStatus("STOPPING_CAMERA");
    clearOverlay();
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setCameraOnline(false);
    setCameraStatus("FREE");
  };

  // Fetch teacher dashboard data
  const fetchTeacherData = async () => {
    try {
      const data = await api.getTeacherDashboard();
      setDashboardData(data);
      const classes = data.teacher.assigned_classes || [];
      const subjects = data.teacher.assigned_subjects || [];
      setAssignedClasses(classes);
      setAssignedSubjects(subjects);
      setSelectedClass((current) => (classes.includes(current) ? current : classes[0] ?? ""));
      setSelectedSubject((current) => (subjects.includes(current) ? current : subjects[0] ?? ""));
    } catch (err: unknown) {
      setErrorMessage(
        `Could not load your classes: ${err instanceof Error ? err.message : String(err)}`,
      );
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
        course_name: selectedSubject ? `${selectedSubject} — ${selectedClass}` : selectedClass,
        class_code: selectedClass,
        subject: selectedSubject || undefined,
        start_time: now.toISOString(),
        end_time: in2h.toISOString(),
        required_presence_percentage: 100.0,
      });

      setSessionId(session.session_id);

      // 2. Start Session
      await api.startSession(session.session_id);

      // 4. Fetch roster
      const attData = await api.getSessionAttendance(session.session_id);
      setRecords(attData.records);

      setCallout({ name: "Scanning", status: "IDLE" });
      setViewedNotTaken(false);
      setStep(2);
      if (onSelectNav) onSelectNav("attendance");

      // 5. Start browser webcam stream directly
      await startCameraStream();
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
      setViewedNotTaken(false);
      setStep(2);
      if (onSelectNav) onSelectNav("attendance");

      await startCameraStream();
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
      setViewedNotTaken(attData.was_taken === false);
      setStep(3);
      if (onSelectNav) onSelectNav("attendance");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(msg || "Failed to load past session details.");
    } finally {
      setLoading(false);
    }
  };

  // Attach MediaStream to <video> element once step 2 renders
  useEffect(() => {
    if (step === 2 && videoRef.current && mediaStreamRef.current) {
      if (videoRef.current.srcObject !== mediaStreamRef.current) {
        videoRef.current.srcObject = mediaStreamRef.current;
      }
      videoRef.current.play().catch(() => {});
    }
  }, [step, cameraOnline]);

  // Draw face bounding boxes and recognition labels over live video
  const drawRecognitionOverlay = (
    faces: Array<{
      bbox?: number[];
      box?: number[];
      name?: string | null;
      identity?: string | null;
      student_id?: string | null;
      similarity?: number;
      confidence_percent?: number;
      status?: string;
    }>,
    sourceW = 640,
    sourceH = 480
  ) => {
    const canvas = overlayCanvasRef.current;
    const video = videoRef.current;
    if (!canvas || !video) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const displayW = video.clientWidth || video.videoWidth || 640;
    const displayH = video.clientHeight || video.videoHeight || 480;

    if (canvas.width !== displayW || canvas.height !== displayH) {
      canvas.width = displayW;
      canvas.height = displayH;
    }

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (!faces || faces.length === 0) return;

    const scaleX = displayW / (sourceW || 640);
    const scaleY = displayH / (sourceH || 480);

    faces.forEach((face) => {
      const rawBox = face.bbox || face.box;
      if (!rawBox || rawBox.length < 4) return;

      const [x1, y1, x2, y2] = rawBox;
      const x = Math.max(0, x1 * scaleX);
      const y = Math.max(0, y1 * scaleY);
      const w = Math.min(displayW - x, (x2 - x1) * scaleX);
      const h = Math.min(displayH - y, (y2 - y1) * scaleY);

      // Recognized (green), unknown (amber) or blocked by the liveness check (red)
      const { label: labelText, strokeColor, bgColor } = getFaceOverlayStyle(face);

      // Draw bounding box rectangle
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = 2.5;
      ctx.strokeRect(x, y, w, h);

      // Label text
      ctx.font = "bold 13px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
      const textMetrics = ctx.measureText(labelText);
      const badgeW = textMetrics.width + 16;
      const badgeH = 24;
      const badgeX = x;
      const badgeY = Math.max(0, y - badgeH - 4);

      // Badge background
      ctx.fillStyle = bgColor;
      if (typeof ctx.roundRect === "function") {
        ctx.beginPath();
        ctx.roundRect(badgeX, badgeY, badgeW, badgeH, 4);
        ctx.fill();
      } else {
        ctx.fillRect(badgeX, badgeY, badgeW, badgeH);
      }

      // Badge text
      ctx.fillStyle = "#ffffff";
      ctx.textBaseline = "middle";
      ctx.fillText(labelText, badgeX + 8, badgeY + badgeH / 2);
    });
  };

  // ========================================================================
  // STEP 2: LIVE FRAME INFERENCE (BROWSER -> AI) & ROSTER POLLING
  // ========================================================================
  useEffect(() => {
    if (step !== 2 || !sessionId) return;

    // Periodic frame sampling from browser video element to Vision Service
    const frameInterval = setInterval(() => {
      if (isProcessingRef.current) return;
      const video = videoRef.current;
      if (!video || video.readyState < 2 || video.paused || video.ended) return;

      if (!canvasRef.current) {
        canvasRef.current = document.createElement("canvas");
      }
      const canvas = canvasRef.current;
      const targetW = video.videoWidth || 640;
      const targetH = video.videoHeight || 480;
      if (canvas.width !== targetW || canvas.height !== targetH) {
        canvas.width = targetW;
        canvas.height = targetH;
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.drawImage(video, 0, 0, targetW, targetH);

      isProcessingRef.current = true;
      canvas.toBlob(
        async (blob) => {
          if (!blob) {
            isProcessingRef.current = false;
            return;
          }
          try {
            const formData = new FormData();
            formData.append("frame", blob, "frame.jpg");
            if (sessionId) formData.append("session_id", sessionId);

            // Frames go to the backend with the teacher's token. The backend checks
            // the session, calls the vision service itself and marks attendance;
            // the browser never talks to the vision service or asserts an identity.
            let res: Response | null = null;
            try {
              const frameToken =
                api.getToken() || localStorage.getItem("anti_proxy_access_token") || "";
              const frameUrl = `${getApiBaseUrl()}/api/v1/attendance/${encodeURIComponent(sessionId || "")}/process-frame`;
              res = await fetch(frameUrl, {
                method: "POST",
                headers: { Authorization: `Bearer ${frameToken}` },
                body: formData,
              });
            } catch {
              res = null;
            }

            if (res && res.ok) {
              const data = await res.json();
              setSpoofDetected(hasSpoof(data.faces));
              if (data.faces && Array.isArray(data.faces) && data.faces.length > 0) {
                drawRecognitionOverlay(data.faces, data.frame_width || targetW, data.frame_height || targetH);
                const recognizedStudents = data.faces.filter(
                  (f: any) => f.status === "recognized" && f.name && f.name !== "UNKNOWN"
                );
                if (recognizedStudents.length > 0) {
                  const top = recognizedStudents[0];
                  setCallout({
                    name: top.name,
                    status: "PRESENT",
                  });
                  const recognizedIdents = new Set(recognizedStudents.map((f: any) => f.identity));
                  const recognizedIds = new Set(recognizedStudents.map((f: any) => f.student_id));
                  setRecords((prev) =>
                    prev.map((r) =>
                      recognizedIdents.has(r.identity) || recognizedIds.has(r.student_id)
                        ? { ...r, status: "PRESENT" }
                        : r
                    )
                  );
                }
              } else if (data.box) {
                drawRecognitionOverlay(
                  [
                    {
                      box: data.box,
                      name: data.recognized ? data.student_name : "UNKNOWN",
                      similarity: data.similarity,
                      status: data.recognized ? "recognized" : "unknown",
                    },
                  ],
                  data.frame_width || targetW,
                  data.frame_height || targetH
                );
                if (data.recognized && data.student_name) {
                  setCallout({
                    name: data.student_name,
                    status: "PRESENT",
                  });
                  setRecords((prev) =>
                    prev.map((r) =>
                      r.identity === data.identity || r.student_id === data.student_id
                        ? { ...r, status: "PRESENT" }
                        : r
                    )
                  );
                }
              } else {
                clearOverlay();
              }
            } else {
              clearOverlay();
            }
          } catch {
            // Ignore network jitter
          } finally {
            isProcessingRef.current = false;
          }
        },
        "image/jpeg",
        0.8
      );
    }, 250);

    // Periodic roster sync from backend
    const rosterInterval = setInterval(async () => {
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
    }, 1500);

    return () => {
      clearInterval(frameInterval);
      clearInterval(rosterInterval);
      clearOverlay();
    };
  }, [step, sessionId]);

  // ========================================================================
  // STEP 2 -> STEP 3: END ATTENDANCE
  // ========================================================================
  const handleEndAttendance = async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      // 1. Release physical camera tracks immediately
      stopCameraStream();

      // 2. Finalize backend session
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

  // Navigate to Dashboard after attendance completion
  const handleGoToDashboard = () => {
    stopCameraStream();
    clearOverlay();
    setStep(1);
    setSessionId(null);
    setRecords([]);
    setErrorMessage(null);
    if (onSelectNav) {
      onSelectNav("dashboard");
    }
    fetchTeacherData();
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
      // A corrected record means attendance has now been taken.
      setViewedNotTaken(false);
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
    stopCameraStream();
    setStep(1);
    setSessionId(null);
    setRecords([]);
    setCallout({ name: "Ready", status: "IDLE" });
    setSpoofDetected(false);
    fetchTeacherData();
  };

  const hasActiveSession = Boolean(dashboardData?.active_session);
  const activeSess = dashboardData?.active_session;
  const previousSessions = dashboardData?.previous_sessions ?? [];
  // The full list is shown a page at a time, like the administrator's.
  const sessionsPage = paginate(previousSessions, sessionsPageNumber, SESSIONS_PAGE_SIZE);
  const teacherName = dashboardData?.teacher.name || user.email;
  const teacherDepartment = dashboardData?.teacher.department || "";
  const teacherId = dashboardData?.teacher.teacher_id || "";
  const noClasses = assignedClasses.length === 0;
  const noClassesMessage =
    "No classes are assigned to you yet. Ask an administrator to assign your classes.";

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
        {noClasses && <div className="erp-empty-box">{noClassesMessage}</div>}
        <div className="erp-classes-grid">
          {assignedClasses.map((cls) => (
            <div key={cls} className="erp-class-card">
              <div className="erp-class-code">{cls}</div>
              {teacherDepartment && <div className="erp-class-dept">{teacherDepartment}</div>}
              <div className="erp-class-subjects">
                {assignedSubjects.length > 0 ? assignedSubjects.join(" • ") : "No subjects assigned"}
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
                  <th>Date</th>
                  <th>Class</th>
                  <th>Subject</th>
                  <th>Present</th>
                  <th>Turnout</th>
                  <th>Status</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {previousSessions.slice(0, 5).map((ps) => (
                  <tr key={ps.session_id}>
                    <td style={{ color: "var(--erp-text-muted)", whiteSpace: "nowrap" }}>{formatDate(ps.start_time || ps.created_at)}</td>
                    <td style={{ fontWeight: 600 }}>{ps.class_code || "—"}</td>
                    <td>{ps.subject || ps.course_name}</td>
                    <td>{ps.was_taken === false ? "—" : `${ps.present_count} / ${ps.total_students}`}</td>
                    <td
                      style={
                        ps.was_taken === false
                          ? { color: "var(--erp-text-muted)" }
                          : { fontWeight: 600, color: ps.attendance_percentage >= 75 ? "#15803d" : "#b91c1c" }
                      }
                    >
                      {formatSessionTurnout(ps)}
                    </td>
                    <td>
                      <span className={`status-badge ${sessionStatusBadgeClass(ps.status)}`}>
                        {sessionStatusLabel(ps.status)}
                      </span>
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

          {noClasses && (
            <div className="erp-alert-box warning" style={{ marginBottom: "1.25rem" }}>
              {noClassesMessage}
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
                disabled={hasActiveSession || loading || assignedSubjects.length === 0}
              >
                {assignedSubjects.length === 0 && <option value="">No subjects assigned</option>}
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
                disabled={hasActiveSession || loading || noClasses}
              >
                {noClasses && <option value="">No classes assigned</option>}
                {assignedClasses.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="erp-camera-select">Camera</label>
              {availableCameras.length > 0 ? (
                <select
                  id="erp-camera-select"
                  className="erp-select-input"
                  value={selectedCameraId}
                  onChange={(e) => setSelectedCameraId(e.target.value)}
                  disabled={hasActiveSession || loading}
                >
                  {availableCameras.map((cam, idx) => (
                    <option key={cam.deviceId || idx} value={cam.deviceId}>
                      {cam.label || (idx === 0 ? "Integrated Camera" : `USB Webcam ${idx}`)}
                    </option>
                  ))}
                </select>
              ) : (
                <div className="erp-select-input" style={{ color: "var(--text-muted)", cursor: "default" }}>
                  Default PC / USB Webcam
                </div>
              )}
              <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: "0.35rem" }}>
                Camera is not active. (Connects on Take Attendance)
              </div>
            </div>

            <div style={{ marginTop: "1.5rem" }}>
              <button
                type="button"
                className="erp-btn erp-btn-primary"
                onClick={handleStartAttendance}
                disabled={hasActiveSession || loading || !selectedClass}
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
              <span style={{ fontWeight: 600 }}>
                {cameraOnline
                  ? "Live Camera"
                  : cameraStatus === "REQUESTING_CAMERA"
                  ? "Requesting camera..."
                  : "Camera Unavailable"}
              </span>
            </div>
          </div>

          {/* Side-by-side Section 7 Layout */}
          <div className="erp-live-grid">
            {/* Left: LIVE CAMERA */}
            <div className="erp-camera-pane">
              <div className="erp-camera-viewport" style={{ position: "relative" }}>
                <video
                  ref={videoRef}
                  autoPlay
                  playsInline
                  muted
                  className="erp-camera-stream"
                  style={{ display: cameraOnline ? "block" : "none" }}
                />
                <canvas
                  ref={overlayCanvasRef}
                  className="recognition-overlay"
                  style={{ display: cameraOnline ? "block" : "none" }}
                />

                {!cameraOnline && (
                  <div
                    style={{
                      position: "absolute",
                      inset: 0,
                      backgroundColor: "rgba(15, 23, 42, 0.94)",
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
                      {cameraStatus === "REQUESTING_CAMERA"
                        ? "Requesting camera..."
                        : cameraStatus === "PERMISSION_DENIED"
                        ? "Camera unavailable"
                        : "Camera unavailable."}
                    </div>
                    <div style={{ fontSize: "0.875rem", color: "#94a3b8", maxWidth: "280px", lineHeight: 1.4, whiteSpace: "pre-line" }}>
                      {cameraStatus === "REQUESTING_CAMERA"
                        ? "Connecting to physical webcam device..."
                        : cameraErrorMessage || (cameraStatus === "PERMISSION_DENIED" ? "Please allow camera access in your browser settings." : "Please check that your webcam is connected.")}
                    </div>
                  </div>
                )}

                {/* A face in view was blocked by the liveness check; nobody is marked for it */}
                {spoofDetected && (
                  <div className="erp-spoof-callout" role="alert">
                    Spoof detected: a photo or screen was shown to the camera. No attendance was marked for it.
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
                Live Camera Feed
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
              <div className="erp-complete-check">{viewedNotTaken ? "—" : "✓"}</div>
              <h1 className="erp-complete-title">{viewedNotTaken ? "Attendance Not Taken" : "Attendance Complete"}</h1>
              <div className="erp-complete-meta">
                <strong>{selectedSubject}</strong> • {selectedClass}
              </div>
              <div className="erp-complete-stats">
                {viewedNotTaken
                  ? "This session does not count towards anyone's attendance."
                  : `${presentCount} / ${totalStudents} Present (${totalStudents > 0 ? Math.round((presentCount / totalStudents) * 100) : 0}%)`}
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
                          <span className={`status-badge ${viewedNotTaken ? "completed" : isPresent ? "present" : "absent"}`}>
                            {viewedNotTaken ? "Not taken" : student.status}
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
            <div className="erp-complete-actions" style={{ display: "flex", gap: "1rem" }}>
              <button
                type="button"
                className="erp-btn erp-btn-secondary"
                onClick={handleDownloadCsv}
                style={{ flex: 1, padding: "0.75rem" }}
              >
                📥 Download Attendance CSV
              </button>
              <button
                type="button"
                className="erp-btn erp-btn-primary"
                onClick={handleGoToDashboard}
                style={{ flex: 1, padding: "0.75rem" }}
              >
                Go to Dashboard
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
        <p className="erp-page-subtitle">Classes an administrator has assigned to you</p>
      </div>

      {noClasses && <div className="erp-empty-box">{noClassesMessage}</div>}
      <div className="erp-classes-grid">
        {assignedClasses.map((cls) => (
          <div key={cls} className="erp-class-card">
            <div className="erp-class-code">{cls}</div>
            {teacherDepartment && <div className="erp-class-dept">{teacherDepartment}</div>}
            <div className="erp-class-subjects">
              Subjects: {assignedSubjects.length > 0 ? assignedSubjects.join(", ") : "none assigned"}
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
                <th>Date</th>
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
              {sessionsPage.items.map((ps) => {
                const absent = Math.max(0, ps.total_students - ps.present_count);
                return (
                  <tr key={ps.session_id}>
                    <td style={{ color: "var(--erp-text-muted)", whiteSpace: "nowrap" }}>{formatDate(ps.start_time || ps.created_at)}</td>
                    <td style={{ fontWeight: 600 }}>{ps.subject || ps.course_name}</td>
                    <td>{ps.class_code || "—"}</td>
                    <td>{ps.total_students}</td>
                    {ps.was_taken === false ? (
                      <td colSpan={2} style={{ color: "var(--erp-text-muted)" }}>Not taken</td>
                    ) : (
                      <>
                        <td style={{ color: "#15803d", fontWeight: 600 }}>{ps.present_count}</td>
                        <td style={{ color: "#b91c1c", fontWeight: 600 }}>{absent}</td>
                      </>
                    )}
                    <td>
                      <span className={`status-badge ${sessionStatusBadgeClass(ps.status)}`}>
                        {sessionStatusLabel(ps.status)}
                      </span>
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
      <Pagination page={sessionsPage} onChange={setSessionsPageNumber} label="Session pages" />
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
            {teacherName.charAt(0).toUpperCase()}
          </div>
          <div>
            <h2 style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--erp-text-main)", margin: 0 }}>
              {teacherName}
            </h2>
            {teacherDepartment && (
              <div style={{ color: "var(--erp-text-muted)", fontSize: "0.875rem" }}>{teacherDepartment}</div>
            )}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", fontSize: "0.875rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "0.5rem 0", borderBottom: "1px solid var(--erp-border)" }}>
            <span style={{ color: "var(--erp-text-muted)" }}>Faculty ID:</span>
            <strong style={{ fontFamily: "var(--font-mono)" }}>{teacherId || "—"}</strong>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "0.5rem 0", borderBottom: "1px solid var(--erp-border)" }}>
            <span style={{ color: "var(--erp-text-muted)" }}>Department:</span>
            <strong>{teacherDepartment || "—"}</strong>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "0.5rem 0", borderBottom: "1px solid var(--erp-border)" }}>
            <span style={{ color: "var(--erp-text-muted)" }}>Assigned Classes:</span>
            <strong>{noClasses ? "None assigned" : assignedClasses.join(", ")}</strong>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "0.5rem 0" }}>
            <span style={{ color: "var(--erp-text-muted)" }}>Email:</span>
            <strong>{user.email}</strong>
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
