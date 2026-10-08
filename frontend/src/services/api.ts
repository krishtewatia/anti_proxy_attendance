import type {
  AdminUserInfo,
  AttendanceCorrectionCreate,
  AttendanceCorrectionResponse,
  AttendanceSessionResponse,
  AuditEventResponse,
  SessionCreate,
  SessionFinalizationResponse,
  SessionLiveSnapshotResponse,
  SessionResponse,
  SessionRosterResponse,
  SessionRosterUpdate,
  StudentDirectoryItem,
  StudentProfile,
  StudentProfileBind,
  TokenResponse,
  UserCreate,
  UserLogin,
  UserResponse,
  VisionEventCreate,
  VisionEventResponse,
  AcademicClass,
  AcademicStructureResponse,
  StudentAttendanceDashboardResponse,
  StudentProfileResponse,
  StudentRegisterRequest,
  Subject,
  TeacherAssignClassesRequest,
  TeacherDashboardResponse,
  TeacherProfileResponse,
  TeacherRegisterRequest,
} from "../types";
import { clearStoredAuth, getStoredToken } from "./auth.ts";

export const getApiBaseUrl = (): string => {
  if (import.meta.env?.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL;
  }
  if (typeof window !== "undefined" && window.location.hostname) {
    const proto = window.location.protocol || "http:";
    return `${proto}//${window.location.hostname}:8000`;
  }
  return "http://localhost:8000";
};

const API_BASE_URL = getApiBaseUrl();

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getStoredToken();
  const headers = new Headers(options.headers);

  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    // Step 2C.3.5: Handle stale or invalid stored authentication (401)
    if (response.status === 401) {
      clearStoredAuth();
      if (typeof window !== "undefined" && window.location.pathname !== "/") {
        window.history.pushState({}, "", "/");
        window.dispatchEvent(new PopStateEvent("popstate"));
      }
    }

     let detail = `Request failed with status ${response.status}`;

    try {
      const errorBody = await response.json();

      if (typeof errorBody?.detail === "string") {
        detail = errorBody.detail;
      }
    } catch {
      // Keep the default error message.
    }

    throw new Error(detail);
  }

  return response.json() as Promise<T>;
}

export const api = {
  register(
    data: UserCreate,
  ): Promise<UserResponse> {
    return request<UserResponse>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  login(
    data: UserLogin,
  ): Promise<TokenResponse> {
    return request<TokenResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  createSession(
    data: SessionCreate,
  ): Promise<SessionResponse> {
    return request<SessionResponse>("/api/v1/sessions", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  getSessions(): Promise<SessionResponse[]> {
    return request<SessionResponse[]>("/api/v1/sessions");
  },

  getSession(sessionId: string): Promise<SessionResponse> {
    return request<SessionResponse>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}`
    );
  },

  getSessionLiveSnapshot(sessionId: string): Promise<SessionLiveSnapshotResponse> {
    return request<SessionLiveSnapshotResponse>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/live-snapshot`
    );
  },

  getSessionRoster(sessionId: string): Promise<SessionRosterResponse> {
    return request<SessionRosterResponse>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/roster`
    );
  },

  updateSessionRoster(
    sessionId: string,
    identitiesOrData: string[] | SessionRosterUpdate
  ): Promise<SessionRosterResponse> {
    const payload: SessionRosterUpdate = Array.isArray(identitiesOrData)
      ? { identities: identitiesOrData }
      : identitiesOrData;

    return request<SessionRosterResponse>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/roster`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
  },

  updateRoster(
    sessionId: string,
    data: SessionRosterUpdate | string[],
  ): Promise<SessionRosterResponse> {
    return this.updateSessionRoster(sessionId, data);
  },

  getRoster(
    sessionId: string,
  ): Promise<SessionRosterResponse> {
    return this.getSessionRoster(sessionId);
  },

  finalizeSession(
    sessionId: string,
  ): Promise<SessionFinalizationResponse> {
    return request<SessionFinalizationResponse>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/finalize`,
      {
        method: "POST",
      },
    );
  },

  getAttendance(
    sessionId: string,
  ): Promise<AttendanceSessionResponse> {
    return request<AttendanceSessionResponse>(
      `/api/v1/attendance/${encodeURIComponent(sessionId)}`,
    );
  },

  getAttendanceExportUrl(sessionId: string): string {
    return `${API_BASE_URL}/api/v1/attendance/${encodeURIComponent(sessionId)}/export`;
  },

  correctAttendance(
    sessionId: string,
    attendanceId: string,
    data: AttendanceCorrectionCreate,
  ): Promise<AttendanceCorrectionResponse> {
    return request<AttendanceCorrectionResponse>(
      `/api/v1/attendance/${encodeURIComponent(sessionId)}/records/${encodeURIComponent(attendanceId)}`,
      {
        method: "PATCH",
        body: JSON.stringify({
          new_status: data.new_status,
          new_presence_seconds: data.new_presence_seconds,
          reason: data.reason,
        }),
      },
    );
  },

  getAttendanceCorrections(
    sessionId: string,
    attendanceId: string,
  ): Promise<AttendanceCorrectionResponse[]> {
    return request<AttendanceCorrectionResponse[]>(
      `/api/v1/attendance/${encodeURIComponent(sessionId)}/records/${encodeURIComponent(attendanceId)}/corrections`,
    );
  },

  getStudentProfile(): Promise<StudentProfile> {
    return request<StudentProfile>("/api/v1/students/profile");
  },

  getMyStudentProfile(): Promise<StudentProfile> {
    return this.getStudentProfile();
  },

  bindStudentProfile(
    identityOrData: string | StudentProfileBind,
  ): Promise<StudentProfile> {
    const payload: StudentProfileBind =
      typeof identityOrData === "string"
        ? { identity: identityOrData }
        : identityOrData;

    return request<StudentProfile>("/api/v1/students/profile", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  bindStudentIdentity(
    identityOrData: string | StudentProfileBind,
  ): Promise<StudentProfile> {
    return this.bindStudentProfile(identityOrData);
  },

  getStudentsDirectory(): Promise<StudentDirectoryItem[]> {
    return request<StudentDirectoryItem[]>("/api/v1/students/directory");
  },

  simulateTransitEvent(
    identity: string,
    direction: "ENTRY" | "EXIT",
    cameraId: string = "CAM_ROOM_101_DOOR"
  ): Promise<VisionEventResponse> {
    const event: VisionEventCreate = {
      event_id: `evt_sim_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
      camera_id: cameraId,
      track_id: Math.floor(Math.random() * 9000) + 1000,
      identity,
      direction,
      timestamp: new Date().toISOString(),
      evidence: {
        peak_similarity: 0.95,
        mean_similarity: 0.92,
        supporting_frames: 18,
        total_frames: 20,
        consistency_pct: 90.0,
      },
    };
    return this.ingestVisionEvent(event);
  },

  ingestVisionEvent(
    event: VisionEventCreate,
    apiKey: string = "test_vision_api_key_for_smoke_test_12345",
  ): Promise<VisionEventResponse> {
    const headers: Record<string, string> = {};
    if (apiKey) {
      headers["X-API-Key"] = apiKey;
    }
    return request<VisionEventResponse>("/api/v1/events", {
      method: "POST",
      headers,
      body: JSON.stringify(event),
    });
  },

  getAuditEvents(params?: {
    resource_type?: string;
    resource_id?: string;
  }): Promise<AuditEventResponse[]> {
    const query = new URLSearchParams();
    if (params?.resource_type) {
      query.set("resource_type", params.resource_type);
    }
    if (params?.resource_id) {
      query.set("resource_id", params.resource_id);
    }
    const queryString = query.toString();
    const endpoint = queryString ? `/api/v1/audit?${queryString}` : "/api/v1/audit";
    return request<AuditEventResponse[]>(endpoint);
  },

  deleteSession(sessionId: string): Promise<{ deleted: boolean; session_id: string }> {
    return request<{ deleted: boolean; session_id: string }>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}`,
      { method: "DELETE" },
    );
  },

  adminGetUsers(role?: string): Promise<AdminUserInfo[]> {
    const query = role ? `?role=${encodeURIComponent(role)}` : "";
    return request<AdminUserInfo[]>(`/api/v1/admin/users${query}`);
  },

  adminGetSessions(): Promise<SessionResponse[]> {
    return request<SessionResponse[]>("/api/v1/admin/sessions");
  },

  adminCreateSession(
    session: SessionCreate,
    assignedTeacherId?: string,
  ): Promise<SessionResponse> {
    const query = assignedTeacherId
      ? `?assigned_teacher_id=${encodeURIComponent(assignedTeacherId)}`
      : "";
    return request<SessionResponse>(`/api/v1/admin/sessions${query}`, {
      method: "POST",
      body: JSON.stringify(session),
    });
  },

  adminDeleteSession(
    sessionId: string,
  ): Promise<{ deleted: boolean; session_id: string }> {
    return request<{ deleted: boolean; session_id: string }>(
      `/api/v1/admin/sessions/${encodeURIComponent(sessionId)}`,
      { method: "DELETE" },
    );
  },

  adminFinalizeSession(
    sessionId: string,
  ): Promise<{ session_id: string; status: string; records_finalized: number }> {
    return request<{ session_id: string; status: string; records_finalized: number }>(
      `/api/v1/admin/sessions/${encodeURIComponent(sessionId)}/finalize`,
      { method: "POST" },
    );
  },

  // --- Phase 2: Student Endpoints ---
  registerStudent(
    data: StudentRegisterRequest,
  ): Promise<StudentProfileResponse> {
    return request<StudentProfileResponse>("/api/v1/students/register", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  getFullStudentProfile(): Promise<StudentProfileResponse> {
    return request<StudentProfileResponse>("/api/v1/students/me");
  },

  getSessionAttendance(
    sessionId: string,
  ): Promise<AttendanceSessionResponse> {
    return this.getAttendance(sessionId);
  },

  getToken(): string | null {
    return getStoredToken();
  },

  getStudentDashboard(): Promise<StudentAttendanceDashboardResponse> {
    return request<StudentAttendanceDashboardResponse>("/api/v1/students/dashboard");
  },

  uploadStudentPhoto(photo_base64: string): Promise<{ status: string; message: string; has_biometric: boolean }> {
    return request<{ status: string; message: string; has_biometric: boolean }>("/api/v1/students/photo", {
      method: "POST",
      body: JSON.stringify({ photo_base64 }),
    });
  },

  // --- Phase 2: Teacher Endpoints ---
  registerTeacher(
    data: TeacherRegisterRequest,
  ): Promise<TeacherProfileResponse> {
    return request<TeacherProfileResponse>("/api/v1/teachers/register", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  getTeacherDashboard(): Promise<TeacherDashboardResponse> {
    return request<TeacherDashboardResponse>("/api/v1/teachers/dashboard");
  },

  getTeacherProfile(): Promise<TeacherProfileResponse> {
    return request<TeacherProfileResponse>("/api/v1/teachers/profile");
  },

  // --- Phase 2: Academic Endpoints ---
  getAcademicStructure(): Promise<AcademicStructureResponse> {
    return request<AcademicStructureResponse>("/api/v1/academic/structure");
  },

  getClasses(): Promise<AcademicClass[]> {
    return request<AcademicClass[]>("/api/v1/academic/classes");
  },

  getSubjects(): Promise<Subject[]> {
    return request<Subject[]>("/api/v1/academic/subjects");
  },

  getClassStudents(classCode: string): Promise<StudentDirectoryItem[]> {
    return request<StudentDirectoryItem[]>(`/api/v1/academic/classes/${encodeURIComponent(classCode)}/students`);
  },

  // --- Phase 2: Session Start / End & Manual Correction ---
  startSession(sessionId: string): Promise<SessionResponse> {
    return request<SessionResponse>(`/api/v1/sessions/${encodeURIComponent(sessionId)}/start`, {
      method: "POST",
    });
  },

  endSession(sessionId: string): Promise<SessionResponse> {
    return request<SessionResponse>(`/api/v1/sessions/${encodeURIComponent(sessionId)}/end`, {
      method: "POST",
    });
  },

  updateAttendanceStatus(
    sessionId: string,
    attendanceId: string,
    status: "PRESENT" | "ABSENT",
  ): Promise<{ attendance_id: string; session_id: string; status: string; message: string }> {
    return request<{ attendance_id: string; session_id: string; status: string; message: string }>(
      `/api/v1/attendance/${encodeURIComponent(sessionId)}/records/${encodeURIComponent(attendanceId)}`,
      {
        method: "PATCH",
        body: JSON.stringify({ status }),
      },
    );
  },

  // --- Phase 2: Admin Multi-Role Management ---
  getAdminStudents(): Promise<StudentProfileResponse[]> {
    return request<StudentProfileResponse[]>("/api/v1/admin/students");
  },

  createAdminStudent(data: StudentRegisterRequest): Promise<StudentProfileResponse> {
    return request<StudentProfileResponse>("/api/v1/admin/students", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  // Removes the account, profile, face template, photo, attendance records and roster entries.
  deleteAdminStudent(
    userId: string,
  ): Promise<{ status: string; user_id: string; student_id?: string; removed?: Record<string, number | boolean> }> {
    return request<{
      status: string;
      user_id: string;
      student_id?: string;
      removed?: Record<string, number | boolean>;
    }>(`/api/v1/admin/students/${encodeURIComponent(userId)}`, {
      method: "DELETE",
    });
  },

  getAdminTeachers(): Promise<TeacherProfileResponse[]> {
    return request<TeacherProfileResponse[]>("/api/v1/admin/teachers");
  },

  createAdminTeacher(data: TeacherRegisterRequest): Promise<TeacherProfileResponse> {
    return request<TeacherProfileResponse>("/api/v1/admin/teachers", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  deleteAdminTeacher(userId: string): Promise<{ status: string; user_id: string }> {
    return request<{ status: string; user_id: string }>(`/api/v1/admin/teachers/${encodeURIComponent(userId)}`, {
      method: "DELETE",
    });
  },

  assignTeacherClasses(
    teacherId: string,
    data: TeacherAssignClassesRequest,
  ): Promise<TeacherProfileResponse> {
    return request<TeacherProfileResponse>(`/api/v1/admin/teachers/${encodeURIComponent(teacherId)}/assign`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  addAdminClass(data: { class_code: string; branch: string; section: string; semester?: number }): Promise<AcademicClass> {
    return request<AcademicClass>("/api/v1/admin/academic/classes", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  addAdminSubject(data: { name: string; code?: string; branch?: string }): Promise<Subject> {
    return request<Subject>("/api/v1/admin/academic/subjects", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  getAdminSessions(filters?: {
    branch?: string;
    section?: string;
    subject?: string;
    teacher?: string;
    status?: string;
  }): Promise<SessionResponse[]> {
    const params = new URLSearchParams();
    if (filters?.branch) params.set("branch", filters.branch);
    if (filters?.section) params.set("section", filters.section);
    if (filters?.subject) params.set("subject", filters.subject);
    if (filters?.teacher) params.set("teacher", filters.teacher);
    if (filters?.status) params.set("status", filters.status);
    const qs = params.toString() ? `?${params.toString()}` : "";
    return request<SessionResponse[]>(`/api/v1/admin/sessions${qs}`);
  },

  checkHealth(): Promise<{
    status: string;
    service: string;
    version: string;
  }> {
    return request<{
      status: string;
      service: string;
      version: string;
    }>("/health");
  },
};
