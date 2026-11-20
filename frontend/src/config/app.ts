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

// Shown in every page footer.
export const AUTHOR_NAME = "Krish Tewatia";
export const AUTHOR_URL = "https://github.com/krishtewatia";

// The "Contact us" address and whether the demo is on are settings of the
// server (CONTACT_EMAIL, PUBLIC_DEMO_ENABLED), read from GET /api/v1/site, so
// one published image serves every site.

// Organisations that use the service. Each has its own page at /<slug> with
// its sign-in and registration. One organisation per deployment for now: the
// backend holds a single organisation's data.
export interface Organisation {
  slug: string;
  shortName: string;
  name: string;
  place: string;
  status: string;
  description: string;
}

export const ORGANISATIONS: Organisation[] = [
  {
    slug: "niet",
    shortName: "NIET",
    name: "Noida Institute of Engineering and Technology",
    place: "Greater Noida, Uttar Pradesh",
    status: "Pilot",
    description: "B.Tech CSE (Data Science), 3rd year: classes, timetable and attendance for every section.",
  },
];

export function organisationBySlug(slug: string): Organisation | undefined {
  return ORGANISATIONS.find((org) => org.slug === slug.toLowerCase());
}
