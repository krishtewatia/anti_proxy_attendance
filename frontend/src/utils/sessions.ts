// Session status: one place that turns the backend's values into what is shown.
//
// The backend stores SCHEDULED, ACTIVE and FINALIZED. (Older code filtered on
// "COMPLETED", a value the backend never writes, so finished sessions never
// showed as completed.) COMPLETED is still accepted as a synonym of FINALIZED.

export type SessionStatusFilter = "ALL" | "SCHEDULED" | "ACTIVE" | "COMPLETED";

export const SESSION_STATUS_FILTERS: Array<{ value: SessionStatusFilter; label: string }> = [
  { value: "ALL", label: "All Sessions" },
  { value: "SCHEDULED", label: "Scheduled" },
  { value: "ACTIVE", label: "In Progress" },
  { value: "COMPLETED", label: "Completed" },
];

function normalize(status: string | null | undefined): string {
  return (status ?? "").trim().toUpperCase();
}

// A session whose attendance is closed.
export function isSessionCompleted(status: string | null | undefined): boolean {
  const value = normalize(status);
  return value === "FINALIZED" || value === "COMPLETED";
}

export function isSessionActive(status: string | null | undefined): boolean {
  return normalize(status) === "ACTIVE";
}

// The words shown for a status.
export function sessionStatusLabel(status: string | null | undefined): string {
  const value = normalize(status);
  if (isSessionCompleted(value)) return "Completed";
  if (value === "ACTIVE") return "In Progress";
  if (value === "SCHEDULED") return "Scheduled";
  return value ? value.charAt(0) + value.slice(1).toLowerCase() : "Unknown";
}

// The badge style for a status (classes defined in index.css).
export function sessionStatusBadgeClass(status: string | null | undefined): string {
  if (isSessionActive(status)) return "active";
  if (isSessionCompleted(status)) return "present";
  return "completed";
}

export function matchesStatusFilter(status: string | null | undefined, filter: SessionStatusFilter): boolean {
  if (filter === "ALL") return true;
  if (filter === "COMPLETED") return isSessionCompleted(status);
  return normalize(status) === filter;
}

export interface Page<T> {
  items: T[];
  page: number;
  pageCount: number;
  total: number;
  from: number;
  to: number;
}

// One page of a list. A page number outside the range is brought back inside it.
export function paginate<T>(all: T[], page: number, pageSize: number): Page<T> {
  const size = Math.max(1, Math.floor(pageSize));
  const pageCount = Math.max(1, Math.ceil(all.length / size));
  const current = Math.min(Math.max(1, Math.floor(page) || 1), pageCount);
  const start = (current - 1) * size;
  const items = all.slice(start, start + size);
  return {
    items,
    page: current,
    pageCount,
    total: all.length,
    from: all.length === 0 ? 0 : start + 1,
    to: start + items.length,
  };
}
