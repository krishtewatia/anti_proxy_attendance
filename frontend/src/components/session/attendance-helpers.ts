import { formatDateTime } from "../../utils/dates.ts";

/**
 * Formatting utilities for session attendance display.
 */

export function formatPresenceDuration(seconds: number): string {
  if (!seconds || seconds <= 0) {
    return "0 min";
  }
  if (seconds < 60) {
    return "< 1 min";
  }
  const totalMinutes = Math.round(seconds / 60);
  if (totalMinutes >= 60) {
    const hours = Math.floor(totalMinutes / 60);
    const mins = totalMinutes % 60;
    return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
  }
  return `${totalMinutes} min`;
}

export function formatPresencePercentage(pct: number): string {
  if (!pct || pct <= 0) {
    return "0%";
  }
  return `${pct.toFixed(2)}%`;
}

export function formatCorrectionTimestamp(isoString: string): string {
  if (!isoString) return "";
  const formatted = formatDateTime(isoString);
  return formatted === "—" ? isoString : formatted;
}
