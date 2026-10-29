// The pilot organisation model as the admin screens see it: structure,
// subject catalog, classes, timetable versions and slots, calendar, settings.
// Pure helpers only, so they can be tested without a browser.

export type GroupSetKind = "ELECTIVE" | "WORKSHOP";

export interface GroupOption {
  option_code: string;
  name: string;
  subject_keys: string[];
  groups: string[];
}

export interface GroupSet {
  set_code: string;
  kind: GroupSetKind;
  name: string;
  options: GroupOption[];
}

export interface Cohort {
  cohort_id: string;
  branch: string;
  year: number;
  semester: string;
  term_id: string;
  name: string;
  sections: string[];
  elective_sets: GroupSet[];
  workshop_sets: GroupSet[];
}

export interface Term {
  term_id: string;
  name: string;
  start_date: string | null;
  end_date: string | null;
  status: string;
}

export interface OrgStructure {
  terms: Term[];
  branches: { code: string; name: string; department: string; cohorts: Cohort[] }[];
}

export type CodeStatus = "CONFIRMED" | "INCOMPLETE" | "MISMATCH";

export interface OrgSubject {
  key: string;
  code: string;
  name: string;
  type: string;
  tracked: boolean;
  code_status: CodeStatus;
  code_note: string;
  short_names: string[];
}

export type Audience =
  | { kind: "SECTION"; section: string }
  | { kind: "GROUP"; set_code: string; set_kind: GroupSetKind; option_code: string; group_code: string };

export interface OrgClass {
  class_id: string;
  term_id: string;
  cohort_id: string;
  subject_key: string;
  audience: Audience;
  label: string;
  teacher_ids: string[];
  status: string;
}

export type FlagKind = "CONFIRM" | "INCOMPLETE_CODE" | "CODE_MISMATCH" | "NO_ROOM" | "CLASH" | "PERIODS_CHECK";

export interface SlotFlag {
  kind: FlagKind;
  text: string;
  resolved?: boolean;
  resolved_note?: string;
}

export interface OrgSlot {
  slot_id: string;
  version_id: string;
  row: number;
  class_id: string;
  subject_key: string;
  audience: Audience;
  day: string;
  start: string;
  end: string;
  start_minute: number;
  end_minute: number;
  periods: number;
  room: string;
  note: string;
  flags: SlotFlag[];
  open_flags?: number;
  label: string;
}

export interface TimetableVersion {
  version_id: string;
  cohort_id: string;
  status: "DRAFT" | "ACTIVE";
  effective_from: string | null;
  source_name: string;
  rows: number;
  slots: number;
  flagged_slots: number;
  created_at: string;
}

export interface ImportReport {
  dry_run: boolean;
  rows: number;
  slots: number;
  classes: number;
  section_classes: number;
  group_classes: number;
  errors: { row: number; message: string }[];
  flag_counts: Partial<Record<FlagKind, number>>;
  flagged_rows: { row: number; summary: string; flags: SlotFlag[] }[];
  version_id?: string;
}

export interface CalendarEntry {
  exception_id: string;
  cohort_id: string;
  date: string;
  class_id: string | null;
  reason: string;
}

export interface PilotSettings {
  college_email_domain: string;
  edit_window_hours: number;
  shortage_threshold_percent: number;
}

export const DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT"] as const;
export const DAY_NAMES: Record<string, string> = {
  MON: "Monday",
  TUE: "Tuesday",
  WED: "Wednesday",
  THU: "Thursday",
  FRI: "Friday",
  SAT: "Saturday",
};

export const FLAG_LABELS: Record<FlagKind, string> = {
  CONFIRM: "To confirm",
  INCOMPLETE_CODE: "Incomplete code",
  CODE_MISMATCH: "Code mismatch",
  NO_ROOM: "No room",
  CLASH: "Clash",
  PERIODS_CHECK: "Check periods",
};

export const CODE_STATUS_LABELS: Record<CodeStatus, string> = {
  CONFIRMED: "Confirmed",
  INCOMPLETE: "Incomplete",
  MISMATCH: "Mismatch",
};

// "Section B" or "DE-II · Predictive Analytics · G1"
export function audienceLabel(audience: Audience, sets: GroupSet[] = []): string {
  if (audience.kind === "SECTION") return `Section ${audience.section}`;
  const set = sets.find((s) => s.set_code === audience.set_code);
  const option = set?.options.find((o) => o.option_code === audience.option_code);
  return `${audience.set_code} · ${option?.name ?? audience.option_code} · ${audience.group_code}`;
}

// The filter the timetable and class screens offer: one section, or one group set.
export type AudienceFilter = { kind: "ALL" } | { kind: "SECTION"; section: string } | { kind: "SET"; set_code: string };

export function audienceFilterLabel(filter: AudienceFilter): string {
  if (filter.kind === "ALL") return "Everything";
  if (filter.kind === "SECTION") return `Section ${filter.section}`;
  return `${filter.set_code} groups`;
}

export function matchesAudience(audience: Audience, filter: AudienceFilter): boolean {
  if (filter.kind === "ALL") return true;
  if (filter.kind === "SECTION") return audience.kind === "SECTION" && audience.section === filter.section;
  return audience.kind === "GROUP" && audience.set_code === filter.set_code;
}

export function encodeFilter(filter: AudienceFilter): string {
  if (filter.kind === "ALL") return "ALL";
  return filter.kind === "SECTION" ? `SECTION:${filter.section}` : `SET:${filter.set_code}`;
}

export function decodeFilter(value: string): AudienceFilter {
  const [kind, rest] = value.split(":");
  if (kind === "SECTION" && rest) return { kind: "SECTION", section: rest };
  if (kind === "SET" && rest) return { kind: "SET", set_code: rest };
  return { kind: "ALL" };
}

// The filters for a cohort: each section, then each group set (electives first).
export function audienceFilters(cohort: Cohort | undefined): AudienceFilter[] {
  if (!cohort) return [{ kind: "ALL" }];
  return [
    { kind: "ALL" },
    ...cohort.sections.map((section): AudienceFilter => ({ kind: "SECTION", section })),
    ...[...cohort.elective_sets, ...cohort.workshop_sets].map((s): AudienceFilter => ({ kind: "SET", set_code: s.set_code })),
  ];
}

export function openFlags(slot: OrgSlot): SlotFlag[] {
  return slot.flags.filter((flag) => !flag.resolved);
}

// One row per distinct time range, one column per weekday; each cell lists the
// slots that start then. Used for the week view of the timetable.
export interface WeekRow {
  start: string;
  end: string;
  startMinute: number;
  cells: Record<string, OrgSlot[]>;
}

export function weekGrid(slots: OrgSlot[]): { days: string[]; rows: WeekRow[] } {
  const days = DAYS.filter((day) => day !== "SAT" || slots.some((s) => s.day === "SAT"));
  const rows = new Map<string, WeekRow>();
  for (const slot of slots) {
    const key = `${slot.start}-${slot.end}`;
    if (!rows.has(key)) {
      rows.set(key, {
        start: slot.start,
        end: slot.end,
        startMinute: slot.start_minute,
        cells: Object.fromEntries(days.map((d) => [d, [] as OrgSlot[]])),
      });
    }
    rows.get(key)!.cells[slot.day]?.push(slot);
  }
  const sorted = [...rows.values()].sort((a, b) => a.startMinute - b.startMinute || a.end.localeCompare(b.end));
  for (const row of sorted) {
    for (const day of days) row.cells[day].sort((a, b) => a.label.localeCompare(b.label));
  }
  return { days: [...days], rows: sorted };
}

// Lectures a week for each class: a double period is two lectures.
export function lecturesPerWeek(slots: OrgSlot[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const slot of slots) counts.set(slot.class_id, (counts.get(slot.class_id) ?? 0) + slot.periods);
  return counts;
}

// The version in force on a date: the active one with the latest effective date not after it.
export function versionInForce(versions: TimetableVersion[], isoDate: string): TimetableVersion | undefined {
  return versions
    .filter((v) => v.status === "ACTIVE" && v.effective_from !== null && v.effective_from <= isoDate)
    .sort((a, b) => (b.effective_from ?? "").localeCompare(a.effective_from ?? ""))[0];
}

export function versionStatusLabel(version: TimetableVersion, today: string): string {
  if (version.status === "DRAFT") return "Draft";
  if (version.effective_from && version.effective_from > today) return `Active from ${version.effective_from}`;
  return "Active";
}

// The columns the timetable import reads (the same list as the server's
// TIMETABLE_COLUMNS; the sample CSV is made from that list).
export const TIMETABLE_COLUMNS = ["scope", "group", "day", "start", "end", "periods", "subject_short", "subject_name", "room", "note"];
export const TIMETABLE_SAMPLE_PATH = "/api/v1/admin/org/timetable/sample.csv";

// The timetable's four steps, as the admin sees them: choose the CSV, review
// the check, save it as a draft, activate it from a date.
export type StepState = "done" | "current" | "todo";

export function timetableSteps(opts: { checking: boolean; hasDraft: boolean; inForce: boolean }): { label: string; state: StepState }[] {
  const labels = ["Choose the timetable CSV", "Review the check", "Save as draft", "Activate from a date"];
  let current = 0;
  if (opts.checking) current = 1;
  else if (opts.hasDraft) current = 3;
  else if (opts.inForce) current = 4;
  return labels.map((label, i) => ({ label, state: i < current ? "done" : i === current ? "current" : "todo" }));
}
