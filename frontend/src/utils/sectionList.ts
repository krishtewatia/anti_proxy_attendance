// The college's official section list, matched against students' setups.
// Pure helpers only, so they can be tested without a browser.

import type { GroupChoice } from "./enrolment.ts";

export type MatchCategory =
  | "MATCH"
  | "DIFFERENT"
  | "EMAIL_DIFFERS"
  | "NOT_ON_LIST"
  | "NO_REQUEST"
  | "NOT_REGISTERED"
  | "APPROVED_AGREES"
  | "APPROVED_DIFFERS";

export const CATEGORY_ORDER: MatchCategory[] = [
  "MATCH",
  "DIFFERENT",
  "EMAIL_DIFFERS",
  "NOT_ON_LIST",
  "NO_REQUEST",
  "NOT_REGISTERED",
  "APPROVED_AGREES",
  "APPROVED_DIFFERS",
];

export const CATEGORY_LABELS: Record<MatchCategory, string> = {
  MATCH: "Matches the list",
  DIFFERENT: "Differs from the list",
  EMAIL_DIFFERS: "Email differs",
  NOT_ON_LIST: "Not on the list",
  NO_REQUEST: "No setup sent",
  NOT_REGISTERED: "Not registered",
  APPROVED_AGREES: "Approved, agrees",
  APPROVED_DIFFERS: "Approved, differs",
};

// The existing badge classes: green, amber, red, grey.
export const CATEGORY_BADGE: Record<MatchCategory, string> = {
  MATCH: "present",
  DIFFERENT: "warning",
  EMAIL_DIFFERS: "absent",
  NOT_ON_LIST: "warning",
  NO_REQUEST: "completed",
  NOT_REGISTERED: "completed",
  APPROVED_AGREES: "present",
  APPROVED_DIFFERS: "warning",
};

export interface ListEntry {
  name: string;
  email: string;
  section: string;
  choices: Record<string, GroupChoice>;
}

export interface ReportRow {
  roll_no: string | null;
  category: MatchCategory;
  list: ListEntry | null;
  student: { user_id: string; name: string | null; email: string | null } | null;
  request: { request_id: string; kind: string; section: string; choices: Record<string, GroupChoice> } | null;
  differences: string[];
  warnings: string[];
}

export interface MatchReport {
  cohort_id: string;
  source_name: string | null;
  uploaded_at: string | null;
  counts: Record<MatchCategory, number>;
  rows: ReportRow[];
}

export interface ListUploadReport {
  cohort_id: string;
  row_count: number;
  per_section: Record<string, number>;
  errors: { row: number; message: string }[];
  dry_run: boolean;
  stored: boolean;
}

export interface ListSummary {
  exists: boolean;
  row_count?: number;
  per_section?: Record<string, number>;
  source_name?: string;
  uploaded_at?: string;
}

export const TEMPLATE_HEADER = "roll_no,name,email,section,de2,de3,dlda";
export const TEMPLATE_EXAMPLE = "2401331540142,Student Name,name@niet.co.in,B,PA G2,DP,DL3";

// Request ids that can be approved together: waiting requests matching the list.
export function matchingRequestIds(report: MatchReport | null, section?: string): string[] {
  if (!report) return [];
  return report.rows
    .filter((r) => r.category === "MATCH" && r.request && (!section || r.request.section === section))
    .map((r) => (r.request as NonNullable<ReportRow["request"]>).request_id);
}

// What a setup request card says about the list.
export function listBadge(report: MatchReport | null, requestId: string): { label: string; badge: string; detail: string } | null {
  if (!report) return null;
  const row = report.rows.find((r) => r.request?.request_id === requestId);
  if (!row) return null;
  return { label: CATEGORY_LABELS[row.category], badge: CATEGORY_BADGE[row.category], detail: row.differences.join("; ") };
}

export function rowsIn(report: MatchReport | null, category: MatchCategory | "ALL", section = ""): ReportRow[] {
  if (!report) return [];
  return report.rows
    .filter((r) => category === "ALL" || r.category === category)
    .filter((r) => !section || r.list?.section === section || r.request?.section === section);
}
