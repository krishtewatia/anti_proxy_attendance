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
import { validationMessage } from "../utils/apiErrors.ts";
import { clearStoredAuth, getStoredToken, setMustChangePassword } from "./auth.ts";
import type { PendingApprovals, PendingCounts } from "../utils/approvals.ts";
import type { ReportsSummary } from "../utils/reports.ts";
import type { ConsentStatus, RegistrationRules } from "../utils/registration.ts";
import type { RegistryTeacher, StudentRegistry } from "../utils/registry.ts";
import type { SlotSession, TeacherTimetable } from "../utils/teaching.ts";
import { classPath, type ClassSessionItem, type LectureItem, type SubjectReport, type TeacherClassItem } from "../utils/classReports.ts";
import type { MyTeacherSetup, TeacherSetupOptions, WaitingTeacherRequest } from "../utils/teacherSetup.ts";
import type { ListSummary, ListUploadReport, MatchReport } from "../utils/sectionList.ts";
import type { MySetup, PhotoCheckResult, SetupOptions, SetupRequest, SetupRequestList, requestBody } from "../utils/enrolment.ts";
import type {
  CalendarEntry,
  ImportReport,
  OrgClass,
  OrgSlot,
  OrgStructure,
  OrgSubject,
  PilotSettings,
  Term,
  TimetableVersion,
} from "../utils/organisation.ts";
import type { AdminAccount, StudentEditFields, TeacherEditFields } from "../utils/accounts.ts";
import type {
  AdminClassRow,
  AdminSubjectRow,
  ClassChanges,
  PublicClass,
  SubjectEditFields,
} from "../utils/catalog.ts";

// Value of VITE_API_BASE_URL that means "the address this page was loaded
// from": the Docker image is built with it, so the browser reaches the API
// through the same reverse proxy that served the page.
export const SAME_ORIGIN = "same-origin";

export const getApiBaseUrl = (): string => {
  if (import.meta.env?.VITE_API_BASE_URL === SAME_ORIGIN) {
    return "";
  }
  if (import.meta.env?.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL;
  }
  // Node (the test suites): an explicit address, never a guess.
  const nodeEnv = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env;
  if (nodeEnv?.VITE_API_BASE_URL) {
    return nodeEnv.VITE_API_BASE_URL === SAME_ORIGIN ? "" : nodeEnv.VITE_API_BASE_URL;
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

      const invalid = validationMessage(errorBody?.detail);
      if (typeof errorBody?.detail === "string") {
        detail = errorBody.detail;
      } else if (invalid) {
        // A rejected form (422): say which field and why.
        detail = invalid;
      } else if (typeof errorBody?.detail?.message === "string") {
        // Structured errors, e.g. { code: "account_pending", message: "..." }
        detail = errorBody.detail.message;
        if (errorBody.detail.code === "password_change_required") {
          // The app shows the change-password screen until this is cleared.
          setMustChangePassword(true);
          if (typeof window !== "undefined") {
            window.dispatchEvent(new PopStateEvent("popstate"));
          }
        }
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

  changePassword(currentPassword: string, newPassword: string): Promise<TokenResponse> {
    return request<TokenResponse>("/api/v1/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
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
  // Public: the college email domain (null while any address is accepted) and the photo notice.
  getRegistrationRules(): Promise<RegistrationRules> {
    return request<RegistrationRules>("/api/v1/auth/registration-rules");
  },

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

  // --- Student self-setup (section, groups, photos) ---
  getSetupOptions(): Promise<SetupOptions> {
    return request<SetupOptions>("/api/v1/enrolment/options");
  },

  getMySetup(): Promise<MySetup> {
    return request<MySetup>("/api/v1/enrolment/me");
  },

  checkSetupPhoto(photo_base64: string): Promise<PhotoCheckResult> {
    return request<PhotoCheckResult>("/api/v1/enrolment/photos/check", {
      method: "POST",
      body: JSON.stringify({ photo_base64 }),
    });
  },

  submitSetup(body: ReturnType<typeof requestBody>): Promise<SetupRequest> {
    return request<SetupRequest>("/api/v1/enrolment/requests", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  withdrawSetup(): Promise<{ status: string; request_id: string }> {
    return request<{ status: string; request_id: string }>("/api/v1/enrolment/requests/current", { method: "DELETE" });
  },

  // --- Admin: setup requests ---
  getSetupRequests(params: Record<string, string> = {}): Promise<SetupRequestList> {
    const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString();
    return request<SetupRequestList>(`/api/v1/admin/enrolment/requests${query ? `?${query}` : ""}`);
  },

  decideSetupRequests(action: "approve" | "reject", request_ids: string[], reason?: string): Promise<{ done: string[] }> {
    return request<{ done: string[] }>("/api/v1/admin/enrolment/requests/bulk", {
      method: "POST",
      body: JSON.stringify({ action, request_ids, ...(reason ? { reason } : {}) }),
    });
  },

  // --- Reports and downloads ---
  getMySubjects(): Promise<SubjectReport> {
    return request<SubjectReport>("/api/v1/students/attendance/subjects");
  },

  getMySubjectLectures(subjectKey: string): Promise<{ subject_key: string; lectures: LectureItem[] }> {
    return request<{ subject_key: string; lectures: LectureItem[] }>(`/api/v1/students/attendance/subjects/${encodeURIComponent(subjectKey)}`);
  },

  getMyTeachingClasses(): Promise<TeacherClassItem[]> {
    return request<TeacherClassItem[]>("/api/v1/teachers/classes");
  },

  getClassSessions(classId: string): Promise<ClassSessionItem[]> {
    return request<ClassSessionItem[]>(classPath(classId, "sessions"));
  },

  // Downloads a file with the signed-in user's token (never a reusable link).
  async downloadFile(path: string, filename: string): Promise<void> {
    const token = getStoredToken();
    const response = await fetch(`${API_BASE_URL}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!response.ok) {
      let detail = `Download failed (${response.status})`;
      try {
        const body = await response.json();
        if (typeof body?.detail === "string") detail = body.detail;
      } catch {
        // keep the default message
      }
      throw new Error(detail);
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  },

  // --- Teachers choose their own classes ---
  getTeacherSetupOptions(): Promise<TeacherSetupOptions> {
    return request<TeacherSetupOptions>("/api/v1/teachers/setup/options");
  },

  getTeacherSetupOptionsAsAdmin(): Promise<TeacherSetupOptions> {
    return request<TeacherSetupOptions>("/api/v1/admin/teacher-requests/options");
  },

  getMyTeacherSetup(): Promise<MyTeacherSetup> {
    return request<MyTeacherSetup>("/api/v1/teachers/setup/me");
  },

  submitTeacherSetup(classIds: string[]): Promise<unknown> {
    return request<unknown>("/api/v1/teachers/setup/requests", { method: "POST", body: JSON.stringify({ class_ids: classIds }) });
  },

  withdrawTeacherSetup(): Promise<unknown> {
    return request<unknown>("/api/v1/teachers/setup/requests/current", { method: "DELETE" });
  },

  getTeacherRequests(): Promise<{ requests: WaitingTeacherRequest[] }> {
    return request<{ requests: WaitingTeacherRequest[] }>("/api/v1/admin/teacher-requests");
  },

  approveTeacherRequest(requestId: string, classIds?: string[]): Promise<unknown> {
    return request<unknown>(`/api/v1/admin/teacher-requests/${encodeURIComponent(requestId)}/approve`, {
      method: "POST",
      body: JSON.stringify(classIds ? { class_ids: classIds } : {}),
    });
  },

  rejectTeacherRequest(requestId: string, reason: string): Promise<unknown> {
    return request<unknown>(`/api/v1/admin/teacher-requests/${encodeURIComponent(requestId)}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
  },

  // --- ENTRY / EXIT rounds ---
  changeRound(sessionId: string, round: "ENTRY" | "EXIT", action: "open" | "close"): Promise<unknown> {
    return request<unknown>(`/api/v1/sessions/${encodeURIComponent(sessionId)}/rounds/${round}/${action}`, { method: "POST" });
  },

  markRound(sessionId: string, round: "ENTRY" | "EXIT", identity: string, status: "PRESENT" | "ABSENT", reason = ""): Promise<unknown> {
    return request<unknown>(`/api/v1/sessions/${encodeURIComponent(sessionId)}/rounds/${round}/marks`, {
      method: "POST",
      body: JSON.stringify({ identity, status, reason }),
    });
  },

  // --- Teachers on the timetable ---
  setTeacherClasses(userId: string, classIds: string[]): Promise<{ teacher_id: string; class_ids: string[] }> {
    return request<{ teacher_id: string; class_ids: string[] }>(`/api/v1/admin/org/teachers/${encodeURIComponent(userId)}/classes`, {
      method: "PUT",
      body: JSON.stringify({ class_ids: classIds }),
    });
  },

  getTeacherTimetable(date?: string): Promise<TeacherTimetable> {
    return request<TeacherTimetable>(`/api/v1/teachers/timetable${date ? `?date=${encodeURIComponent(date)}` : ""}`);
  },

  startFromSlot(slotId: string, date?: string): Promise<SlotSession> {
    return request<SlotSession>("/api/v1/teachers/sessions/from-slot", {
      method: "POST",
      body: JSON.stringify({ slot_id: slotId, ...(date ? { date } : {}) }),
    });
  },

  // --- Admin: registries, Year > Branch > Section ---
  getStudentRegistry(params: Record<string, string> = {}): Promise<StudentRegistry> {
    const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString();
    return request<StudentRegistry>(`/api/v1/admin/registry/students${query ? `?${query}` : ""}`);
  },

  getTeacherRegistry(): Promise<{ teachers: RegistryTeacher[] }> {
    return request<{ teachers: RegistryTeacher[] }>("/api/v1/admin/registry/teachers");
  },

  // --- Admin: the official section list ---
  uploadSectionList(cohortId: string, csvText: string, sourceName: string, dryRun: boolean): Promise<ListUploadReport> {
    const query = new URLSearchParams({ dry_run: String(dryRun), source_name: sourceName });
    return request<ListUploadReport>(`/api/v1/admin/enrolment/section-lists/${encodeURIComponent(cohortId)}?${query.toString()}`, {
      method: "POST",
      headers: { "Content-Type": "text/csv" },
      body: csvText,
    });
  },

  getSectionList(cohortId: string): Promise<ListSummary> {
    return request<ListSummary>(`/api/v1/admin/enrolment/section-lists/${encodeURIComponent(cohortId)}`);
  },

  deleteSectionList(cohortId: string): Promise<{ deleted: boolean }> {
    return request<{ deleted: boolean }>(`/api/v1/admin/enrolment/section-lists/${encodeURIComponent(cohortId)}`, { method: "DELETE" });
  },

  getSectionListReport(cohortId: string): Promise<MatchReport> {
    return request<MatchReport>(`/api/v1/admin/enrolment/section-lists/${encodeURIComponent(cohortId)}/report`);
  },

  approveMatching(cohortId: string, requestIds: string[]): Promise<{ done: string[] }> {
    return request<{ done: string[] }>(`/api/v1/admin/enrolment/section-lists/${encodeURIComponent(cohortId)}/approve-matching`, {
      method: "POST",
      body: JSON.stringify({ request_ids: requestIds }),
    });
  },

  // The notice a student accepts before sending a photo of their face.
  getMyConsent(): Promise<ConsentStatus> {
    return request<ConsentStatus>("/api/v1/students/consent");
  },

  acceptConsent(version: string): Promise<ConsentStatus> {
    return request<ConsentStatus>("/api/v1/students/consent", {
      method: "POST",
      body: JSON.stringify({ version }),
    });
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
  // --- Registration approval (admin) ---

  getPendingApprovals(): Promise<PendingApprovals> {
    return request<PendingApprovals>("/api/v1/admin/approvals");
  },

  getPendingApprovalCounts(): Promise<PendingCounts> {
    return request<PendingCounts>("/api/v1/admin/approvals/count");
  },

  approveRegistration(
    userId: string,
    decision: { assigned_classes?: string[]; assigned_subjects?: string[]; branch?: string; section?: string },
  ): Promise<{ status: string; user_id: string }> {
    return request<{ status: string; user_id: string }>(
      `/api/v1/admin/approvals/${encodeURIComponent(userId)}/approve`,
      { method: "POST", body: JSON.stringify(decision) },
    );
  },

  rejectRegistration(userId: string): Promise<{ status: string; user_id: string }> {
    return request<{ status: string; user_id: string }>(
      `/api/v1/admin/approvals/${encodeURIComponent(userId)}/reject`,
      { method: "POST" },
    );
  },

  approvePhotoChange(identity: string): Promise<{ status: string; identity: string }> {
    return request<{ status: string; identity: string }>(
      `/api/v1/admin/approvals/photos/${encodeURIComponent(identity)}/approve`,
      { method: "POST" },
    );
  },

  rejectPhotoChange(identity: string): Promise<{ status: string; identity: string }> {
    return request<{ status: string; identity: string }>(
      `/api/v1/admin/approvals/photos/${encodeURIComponent(identity)}/reject`,
      { method: "POST" },
    );
  },

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

  // --- Account management (admin) ---

  updateAdminStudent(
    userId: string,
    changes: Partial<StudentEditFields>,
  ): Promise<{ status: string; user_id: string; changed: string[] }> {
    return request<{ status: string; user_id: string; changed: string[] }>(
      `/api/v1/admin/students/${encodeURIComponent(userId)}`,
      { method: "PATCH", body: JSON.stringify(changes) },
    );
  },

  updateAdminTeacher(
    userId: string,
    changes: Partial<TeacherEditFields>,
  ): Promise<{ status: string; user_id: string; changed: string[] }> {
    return request<{ status: string; user_id: string; changed: string[] }>(
      `/api/v1/admin/teachers/${encodeURIComponent(userId)}`,
      { method: "PATCH", body: JSON.stringify(changes) },
    );
  },

  // The temporary password comes back once, in this response only.
  resetUserPassword(userId: string): Promise<{ user_id: string; temporary_password: string }> {
    return request<{ user_id: string; temporary_password: string }>(
      `/api/v1/admin/users/${encodeURIComponent(userId)}/reset-password`,
      { method: "POST" },
    );
  },

  getAdmins(): Promise<AdminAccount[]> {
    return request<AdminAccount[]>("/api/v1/admin/admins");
  },

  createAdmin(data: { name: string; email: string; password: string }): Promise<AdminAccount> {
    return request<AdminAccount>("/api/v1/admin/admins", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  deleteAdmin(userId: string): Promise<{ status: string; user_id: string }> {
    return request<{ status: string; user_id: string }>(
      `/api/v1/admin/admins/${encodeURIComponent(userId)}`,
      { method: "DELETE" },
    );
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

  // Keeps the sessions and attendance the teacher recorded.
  deleteAdminTeacher(userId: string): Promise<{ status: string; user_id: string; sessions_kept?: number }> {
    return request<{ status: string; user_id: string; sessions_kept?: number }>(`/api/v1/admin/teachers/${encodeURIComponent(userId)}`, {
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

  // --- Academic setup (pilot organisation model) ---

  seedPilotStructure(): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>("/api/v1/admin/org/seed-pilot", { method: "POST" });
  },

  getOrgStructure(): Promise<OrgStructure> {
    return request<OrgStructure>("/api/v1/admin/org/structure");
  },

  setTermDates(termId: string, startDate: string | null, endDate: string | null): Promise<Term> {
    return request<Term>(`/api/v1/admin/org/terms/${encodeURIComponent(termId)}`, {
      method: "PATCH",
      body: JSON.stringify({ start_date: startDate || null, end_date: endDate || null }),
    });
  },

  getOrgSubjects(): Promise<OrgSubject[]> {
    return request<OrgSubject[]>("/api/v1/admin/org/subjects");
  },

  updateOrgSubject(
    key: string,
    changes: Partial<Pick<OrgSubject, "code" | "name" | "code_status" | "code_note">>,
  ): Promise<OrgSubject> {
    return request<OrgSubject>(`/api/v1/admin/org/subjects/${encodeURIComponent(key)}`, {
      method: "PATCH",
      body: JSON.stringify(changes),
    });
  },

  getOrgClasses(cohortId?: string): Promise<OrgClass[]> {
    const query = cohortId ? `?cohort_id=${encodeURIComponent(cohortId)}` : "";
    return request<OrgClass[]>(`/api/v1/admin/org/classes${query}`);
  },

  // The CSV goes as the request body. dryRun only checks it.
  importTimetable(cohortId: string, csvText: string, sourceName: string, dryRun: boolean): Promise<ImportReport> {
    const query = new URLSearchParams({ cohort_id: cohortId, dry_run: String(dryRun), source_name: sourceName });
    return request<ImportReport>(`/api/v1/admin/org/timetable/import?${query.toString()}`, {
      method: "POST",
      headers: { "Content-Type": "text/csv" },
      body: csvText,
    });
  },

  getTimetableVersions(cohortId: string): Promise<TimetableVersion[]> {
    return request<TimetableVersion[]>(`/api/v1/admin/org/timetable/versions?cohort_id=${encodeURIComponent(cohortId)}`);
  },

  getTimetableSlots(versionId: string, flaggedOnly = false): Promise<OrgSlot[]> {
    return request<OrgSlot[]>(
      `/api/v1/admin/org/timetable/versions/${encodeURIComponent(versionId)}/slots?flagged_only=${flaggedOnly}`,
    );
  },

  activateTimetableVersion(versionId: string, effectiveFrom: string): Promise<TimetableVersion> {
    return request<TimetableVersion>(`/api/v1/admin/org/timetable/versions/${encodeURIComponent(versionId)}/activate`, {
      method: "POST",
      body: JSON.stringify({ effective_from: effectiveFrom }),
    });
  },

  resolveTimetableFlag(slotId: string, kind: string, note: string): Promise<OrgSlot> {
    return request<OrgSlot>(
      `/api/v1/admin/org/timetable/slots/${encodeURIComponent(slotId)}/flags/${encodeURIComponent(kind)}/resolve`,
      { method: "POST", body: JSON.stringify({ note }) },
    );
  },

  getCalendar(cohortId: string): Promise<CalendarEntry[]> {
    return request<CalendarEntry[]>(`/api/v1/admin/org/calendar?cohort_id=${encodeURIComponent(cohortId)}`);
  },

  addCalendarEntry(entry: { cohort_id: string; date: string; reason: string; class_id?: string | null }): Promise<CalendarEntry> {
    return request<CalendarEntry>("/api/v1/admin/org/calendar", { method: "POST", body: JSON.stringify(entry) });
  },

  deleteCalendarEntry(exceptionId: string): Promise<{ deleted: string }> {
    return request<{ deleted: string }>(`/api/v1/admin/org/calendar/${encodeURIComponent(exceptionId)}`, {
      method: "DELETE",
    });
  },

  getPilotSettings(): Promise<PilotSettings> {
    return request<PilotSettings>("/api/v1/admin/org/settings");
  },

  updatePilotSettings(changes: Partial<PilotSettings>): Promise<PilotSettings> {
    return request<PilotSettings>("/api/v1/admin/org/settings", { method: "PUT", body: JSON.stringify(changes) });
  },

  // --- Classes and subjects ---

  // The active classes, for the registration form. Needs no sign-in.
  getPublicClasses(): Promise<PublicClass[]> {
    return request<PublicClass[]>("/api/v1/academic/public/classes");
  },

  getAdminClasses(): Promise<AdminClassRow[]> {
    return request<AdminClassRow[]>("/api/v1/admin/academic/classes");
  },

  updateAdminClass(classCode: string, changes: ClassChanges): Promise<{ class_code: string; changed: string[] }> {
    return request<{ class_code: string; changed: string[] }>(
      `/api/v1/admin/academic/classes/${encodeURIComponent(classCode)}`,
      { method: "PATCH", body: JSON.stringify(changes) },
    );
  },

  setAdminClassArchived(classCode: string, archived: boolean): Promise<{ class_code: string; status: string }> {
    return request<{ class_code: string; status: string }>(
      `/api/v1/admin/academic/classes/${encodeURIComponent(classCode)}/${archived ? "archive" : "unarchive"}`,
      { method: "POST" },
    );
  },

  deleteAdminClass(classCode: string): Promise<{ status: string; class_code: string }> {
    return request<{ status: string; class_code: string }>(
      `/api/v1/admin/academic/classes/${encodeURIComponent(classCode)}`,
      { method: "DELETE" },
    );
  },

  getAdminSubjects(): Promise<AdminSubjectRow[]> {
    return request<AdminSubjectRow[]>("/api/v1/admin/academic/subjects");
  },

  updateAdminSubject(
    subjectId: string,
    changes: Partial<SubjectEditFields>,
  ): Promise<{ subject_id: string; changed: string[] }> {
    return request<{ subject_id: string; changed: string[] }>(
      `/api/v1/admin/academic/subjects/${encodeURIComponent(subjectId)}`,
      { method: "PATCH", body: JSON.stringify(changes) },
    );
  },

  setAdminSubjectArchived(subjectId: string, archived: boolean): Promise<{ subject_id: string; status: string }> {
    return request<{ subject_id: string; status: string }>(
      `/api/v1/admin/academic/subjects/${encodeURIComponent(subjectId)}/${archived ? "archive" : "unarchive"}`,
      { method: "POST" },
    );
  },

  deleteAdminSubject(subjectId: string): Promise<{ status: string; subject_id: string }> {
    return request<{ status: string; subject_id: string }>(
      `/api/v1/admin/academic/subjects/${encodeURIComponent(subjectId)}`,
      { method: "DELETE" },
    );
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

  getAdminReportsSummary(): Promise<ReportsSummary> {
    return request<ReportsSummary>("/api/v1/admin/reports/summary");
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
