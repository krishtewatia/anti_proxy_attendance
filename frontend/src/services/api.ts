import type {
  AttendanceSessionResponse,
  SessionCreate,
  SessionFinalizationResponse,
  SessionResponse,
  SessionRosterResponse,
  SessionRosterUpdate,
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

  updateRoster(
    sessionId: string,
    data: SessionRosterUpdate,
  ): Promise<SessionRosterResponse> {
    return request<SessionRosterResponse>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/roster`,
      {
        method: "POST",
        body: JSON.stringify(data),
      },
    );
  },

  getRoster(
    sessionId: string,
  ): Promise<SessionRosterResponse> {
    return request<SessionRosterResponse>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/roster`,
    );
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

  ingestVisionEvent(
    event: VisionEventCreate,
  ): Promise<VisionEventResponse> {
    return request<VisionEventResponse>("/api/v1/events", {
      method: "POST",
      body: JSON.stringify(event),
    });
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
