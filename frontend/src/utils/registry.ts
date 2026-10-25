// The admin registries (students, teachers), organised Year > Branch > Section.
// Pure helpers only, so they can be tested without a browser.

import type { GroupChoice } from "./enrolment.ts";
import type { LevelCounts } from "./orgNavigator.ts";

export type StudentStatus = "APPROVED" | "CHANGE_WAITING" | "WAITING" | "NO_SETUP";

export interface RegistryStudent {
  user_id: string;
  name: string | null;
  roll_number: string | null;
  email: string | null;
  status: StudentStatus;
  cohort_id: string | null;
  year: number | null;
  branch: string | null;
  section: string | null;
  choices: Record<string, GroupChoice>;
  request_id: string | null;
  has_photo: boolean;
  photo_url: string | null;
}

export interface StudentRegistry {
  students: RegistryStudent[];
  counts: {
    no_setup: number;
    cohorts: Record<string, LevelCounts & { sections: Record<string, LevelCounts> }>;
  };
}

export interface RegistryTeacherClass {
  class_id: string;
  cohort_id: string;
  subject_key: string;
  subject: string;
  code: string;
  audience: { kind: "SECTION"; section: string } | { kind: "GROUP"; set_code: string; option_code: string; group_code: string };
}

export interface RegistryTeacher {
  user_id: string;
  name: string | null;
  email: string | null;
  department: string | null;
  approved: boolean;
  classes: RegistryTeacherClass[];
  cohorts: { cohort_id: string; year: number | null; branch: string | null }[];
}

export const STATUS_LABELS: Record<StudentStatus, string> = {
  APPROVED: "Approved",
  CHANGE_WAITING: "Change waiting",
  WAITING: "Waiting for approval",
  NO_SETUP: "No setup yet",
};

export const STATUS_BADGE: Record<StudentStatus, string> = {
  APPROVED: "present",
  CHANGE_WAITING: "warning",
  WAITING: "warning",
  NO_SETUP: "completed",
};

// "PA G2", "DP", "DL3": a choice in as few characters as possible.
export function shortChoice(setCode: string, choice: GroupChoice | undefined): string {
  if (!choice) return "—";
  return choice.option === choice.group || choice.option === setCode ? choice.group : `${choice.option} ${choice.group}`;
}

// "Section B · CN", "DE-II PA G2 · PRED": one class of a teacher.
export function classLabel(c: RegistryTeacherClass): string {
  const who = c.audience.kind === "SECTION" ? `Section ${c.audience.section}` : `${c.audience.set_code} ${shortChoice(c.audience.set_code, { option: c.audience.option_code, group: c.audience.group_code })}`;
  return `${who} · ${c.subject}`;
}

// Teachers of one year and branch (by the classes they take), plus those with none yet.
export function teachersFor(teachers: RegistryTeacher[], cohortId: string): { assigned: RegistryTeacher[]; unassigned: RegistryTeacher[] } {
  return {
    assigned: teachers.filter((t) => t.cohorts.some((c) => c.cohort_id === cohortId)),
    unassigned: teachers.filter((t) => t.classes.length === 0),
  };
}
