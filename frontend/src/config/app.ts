// The name shown everywhere in the interface. Set VITE_APP_NAME at build time
// to rename the product without touching the code (in Docker it is taken from
// APP_NAME in .env; see docker-compose.yml).

const DEFAULT_APP_NAME = "Anti-Proxy Attendance System";

function configuredName(): string | undefined {
  const fromVite = (import.meta as { env?: Record<string, string | undefined> }).env?.VITE_APP_NAME;
  if (fromVite && fromVite.trim()) {
    return fromVite.trim();
  }
  // Node (the test suites).
  const nodeEnv = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env;
  const fromNode = nodeEnv?.VITE_APP_NAME;
  return fromNode && fromNode.trim() ? fromNode.trim() : undefined;
}

export const APP_NAME: string = configuredName() ?? DEFAULT_APP_NAME;
export const APP_TAGLINE = "Face-recognition attendance";
