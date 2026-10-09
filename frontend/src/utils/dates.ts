// One way to write dates and times everywhere: "7 Oct 2026" and "6:50 am".
// (A numeric date such as 7/10/2026 reads as 7 October or as July 10.)

const DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });
const TIME = new Intl.DateTimeFormat("en-GB", { hour: "numeric", minute: "2-digit", hour12: true });

function parse(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

// "7 Oct 2026"; a dash when there is no usable date.
export function formatDate(value: string | Date | null | undefined): string {
  const date = parse(value);
  return date ? DATE.format(date) : "—";
}

// "6:50 am"
export function formatTime(value: string | Date | null | undefined): string {
  const date = parse(value);
  return date ? TIME.format(date).replace(/\s?(AM|PM)$/i, (m) => " " + m.trim().toLowerCase()) : "—";
}

// "7 Oct 2026, 6:50 am"
export function formatDateTime(value: string | Date | null | undefined): string {
  const date = parse(value);
  return date ? `${formatDate(date)}, ${formatTime(date)}` : "—";
}

// What a turnout cell shows. A session where attendance was never taken has
// no turnout: "Not taken", not 0%.
export function formatSessionTurnout(session: {
  was_taken?: boolean | null;
  attendance_percentage?: number | null;
}): string {
  if (session.was_taken === false) return "Not taken";
  const value = session.attendance_percentage;
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${Number.isInteger(value) ? value : value.toFixed(1)}%`;
}
