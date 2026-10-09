// The administrator's attendance report: counted by the server from finalized sessions.

export interface ReportsSummary {
  finalized_sessions: number;
  classes_with_sessions: number;
  attendance_records: number;
  // null when there is nothing to count.
  average_turnout_percentage: number | null;
  students_counted: number;
  students_below_threshold: number;
  threshold_percentage: number;
}

// "84.5%" or a dash when the server had nothing to count. Never a made-up number.
export function formatTurnout(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  return `${Number.isInteger(value) ? value : value.toFixed(1)}%`;
}

// What a count cell shows: the number, or a dash when the server sent none.
export function formatCount(value: number | null | undefined): string {
  return value === null || value === undefined || !Number.isFinite(value) ? "—" : String(value);
}
