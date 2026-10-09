// Shared gate for the test suites that talk to a real backend.
//
// These suites register accounts, create sessions and mark attendance, so
// they must never run against whatever happens to be listening on
// localhost:8000 (that is how a development database fills up with test
// accounts). They run only when an administrator for a throwaway backend is
// named explicitly:
//
//   LIVE_TEST_ADMIN_EMAIL=...  LIVE_TEST_ADMIN_PASSWORD=...  LIVE_TEST_SERVICE_KEY=...  //     [VITE_API_BASE_URL=http://127.0.0.1:PORT]  npm test
//
// The easiest throwaway backend is `python scripts/smoke_e2e.py --keep`,
// which prints the address, the administrator and the service key it generated.
//
// Without those variables every live suite is skipped, as in CI.
//
// A new registration is PENDING until an administrator approves it, and a
// teacher may open a session only for an assigned class. When the gate is
// open, `api.register` is wrapped so each account the suites create is
// approved (teachers for LIVE_TEST_CLASS), and `api.createSession` names that
// class unless the suite chose one.

import { api, getApiBaseUrl } from "../src/services/index.ts";
import type { VisionEventCreate, VisionEventResponse } from "../src/types/index.ts";

// A class from the default catalog that the smoke test leaves empty, so a
// session's automatic roster starts with nobody on it.
export const LIVE_TEST_CLASS = "CS-C";

let prepared = false;

async function adminToken(email: string, password: string): Promise<string> {
  const response = await fetch(`${getApiBaseUrl()}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    throw new Error(`live test administrator could not log in (HTTP ${response.status})`);
  }
  return (await response.json()).access_token as string;
}

// Returns the backend's health answer, or throws to make the calling suite skip.
// Doorway events are sent by cameras with the backend's service key, never by
// the browser client. The live suites post them directly, with the key the
// throwaway backend was started with.
export async function ingestVisionEvent(event: VisionEventCreate): Promise<VisionEventResponse> {
  const serviceKey = process.env.LIVE_TEST_SERVICE_KEY;
  if (!serviceKey) {
    throw new Error("LIVE_TEST_SERVICE_KEY is needed to send doorway events to the throwaway backend");
  }
  const response = await fetch(`${getApiBaseUrl()}/api/v1/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": serviceKey },
    body: JSON.stringify(event),
  });
  if (!response.ok) {
    throw new Error(`doorway event was refused (HTTP ${response.status})`);
  }
  return (await response.json()) as VisionEventResponse;
}

export async function requireLiveBackend(): ReturnType<typeof api.checkHealth> {
  const email = process.env.LIVE_TEST_ADMIN_EMAIL;
  const password = process.env.LIVE_TEST_ADMIN_PASSWORD;
  if (!email || !password) {
    throw new Error(
      "live suites run only against a throwaway backend named by LIVE_TEST_ADMIN_EMAIL / LIVE_TEST_ADMIN_PASSWORD",
    );
  }

  const health = await api.checkHealth();
  if (prepared) {
    return health;
  }
  const token = await adminToken(email, password);

  const register = api.register.bind(api);
  api.register = async (data) => {
    const created = await register(data);
    const decision = data.role === "TEACHER" ? { assigned_classes: [LIVE_TEST_CLASS] } : {};
    const approved = await fetch(
      `${getApiBaseUrl()}/api/v1/admin/approvals/${encodeURIComponent(created.user_id)}/approve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify(decision),
      },
    );
    if (!approved.ok) {
      throw new Error(`live test account could not be approved (HTTP ${approved.status})`);
    }
    return created;
  };

  const createSession = api.createSession.bind(api);
  api.createSession = (data) =>
    createSession({ ...data, class_code: data.class_code ?? LIVE_TEST_CLASS });

  prepared = true;
  return health;
}
