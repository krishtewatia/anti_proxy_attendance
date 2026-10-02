import type {
  AttendanceCorrectionCreate,
  AttendanceCorrectionResponse,
  AttendanceSessionResponse,
  AuditEventResponse,
  SessionCreate,
  SessionFinalizationResponse,
  SessionResponse,
  SessionRosterResponse,
  SessionRosterUpdate,
  StudentProfile,
  StudentProfileBind,
  TokenResponse,
  UserCreate,
  UserLogin,
  UserResponse,
  VisionEventCreate,
  VisionEventResponse,
} from "../types";
import { clearStoredAuth, getStoredToken } from "./auth.ts";

const API_BASE_URL =
  import.meta.env?.VITE_API_BASE_URL ?? "http://localhost:8000";

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

  ingestVisionEvent(
    event: VisionEventCreate,
  ): Promise<VisionEventResponse> {
    return request<VisionEventResponse>("/api/v1/events", {
      method: "POST",
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
