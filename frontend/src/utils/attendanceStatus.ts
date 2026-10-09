// How attendance figures are read when some sessions were never taken.
// A session that was never taken is not an absence and is counted nowhere.

export const SHORTAGE_THRESHOLD = 75;

// True only when attendance was taken at least once and the percentage is
// below the minimum. With nothing taken there is nothing to be short of.
export function isAttendanceShortage(percentage: number | null | undefined, sessionsTaken: number): boolean {
  if (sessionsTaken <= 0 || percentage === null || percentage === undefined || !Number.isFinite(percentage)) {
    return false;
  }
  return percentage < SHORTAGE_THRESHOLD;
}

// True when there is no percentage to show at all.
export function nothingTaken(percentage: number | null | undefined, sessionsTaken: number): boolean {
  return sessionsTaken <= 0 || percentage === null || percentage === undefined;
}

// The badge for one row of a student's history.
export function historyStatusBadge(status: string): { label: string; className: string } {
  if (status === "NOT_TAKEN") return { label: "Not taken", className: "completed" };
  if (status === "PRESENT") return { label: "✓ PRESENT", className: "present" };
  return { label: "— ABSENT", className: "absent" };
}
