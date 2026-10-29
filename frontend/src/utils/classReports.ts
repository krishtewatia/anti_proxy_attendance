// Attendance reports for timetable classes: the student's subject-wise view
// (in lectures, "not entered" apart) and the teacher's downloads.
// Pure helpers only.

import { formatDate } from "./dates.ts";

export interface SubjectRow {
  subject_key: string;
  code: string;
  name: string;
  teacher: string;
  present: number;
  absent: number;
  not_entered: number;
  held: number;
  percentage: number | null;
  shortage: boolean;
}

export interface SubjectReport {
  subjects: SubjectRow[];
  overall: { present: number; absent: number; not_entered: number; held: number; percentage: number | null; shortage: boolean };
  not_counted: { code: string; name: string }[];
  threshold: number;
}

export interface LectureItem {
  date: string;
  time: string;
  lecture: number;
  status: "P" | "A";
  class: string | null;
  entry: string | null;
  exit: string | null;
}

export interface TeacherClassItem {
  class_id: string;
  label: string | null;
  subject: string;
  code: string;
  audience?: { kind?: string };
}

export interface ClassSessionItem {
  session_id: string;
  date: string | null;
  // The timetable slot's start, in college time ("09:10").
  time: string;
  // When attendance was actually taken (ENTRY opened), in college time.
  taken_at?: string | null;
  status: string;
  rounds_held: string[];
  periods: number | null;
}

// "28 Oct 2026, 09:10 · taken 14:01": the slot, and when it was taken if that differs.
export function sessionWhen(session: Pick<ClassSessionItem, "date" | "time" | "taken_at">): string {
  const when = [formatDate(session.date), session.time].filter(Boolean).join(", ");
  return session.taken_at && session.taken_at !== session.time ? `${when} · taken ${session.taken_at}` : when;
}

export function percentLabel(value: number | null): string {
  return value === null ? "—" : `${value}%`;
}

// The URL path of a class's download (class ids contain ":" and "/").
export function classPath(classId: string, file: "students.csv" | "register.csv" | "sessions" | "students"): string {
  return `/api/v1/teachers/classes/${encodeURIComponent(classId)}/${file}`;
}

// Register for a date range: empty dates mean "from the start" / "to today".
export function registerPath(classId: string, from: string, to: string): string {
  const query = new URLSearchParams(Object.entries({ from, to }).filter(([, v]) => v)).toString();
  return `${classPath(classId, "register.csv")}${query ? `?${query}` : ""}`;
}

// A safe file name from a class label, e.g. "Computer Networks - Section B".
export function fileName(label: string, kind: string): string {
  return `${kind}_${label}`.replace(/[^A-Za-z0-9_-]+/g, "_").replace(/_+/g, "_") + ".csv";
}

// A class's students with their attendance in it (the register's totals).
export interface ClassStudentRow {
  identity: string;
  roll_number: string;
  name: string;
  email: string;
  section: string;
  de2: string;
  de3: string;
  dlda: string;
  present: number;
  absent: number;
  held: number;
  percentage: number | null;
  shortage: boolean;
}

export interface ClassOverview {
  class_id: string;
  label: string | null;
  threshold: number;
  students: ClassStudentRow[];
  summary: { students: number; lectures_held: number; average: number | null; below_threshold: number };
}

// One session of a class: each student's ENTRY / EXIT marks and lectures.
export interface SessionSheetRow {
  identity: string;
  roll_number: string;
  name: string;
  on_roster: boolean;
  entry: "PRESENT" | "ABSENT";
  exit: "PRESENT" | "ABSENT";
  by_hand: boolean;
  lectures: string[];
}

export interface SessionSheet {
  session_id: string;
  date: string;
  time: string;
  periods: number;
  status: string;
  rounds_held: string[];
  teacher_may_edit: boolean;
  editable_until: string | null;
  students: SessionSheetRow[];
}

export type StudentSort = "roll" | "percentage";

// Search by name or roll number, optionally only those below the threshold;
// sorted by roll number, or by percentage (lowest first, none held last).
export function filterStudents(rows: ClassStudentRow[], query: string, belowOnly: boolean, sort: StudentSort): ClassStudentRow[] {
  const q = query.trim().toLowerCase();
  const kept = rows.filter(
    (r) => (!belowOnly || r.shortage) && (!q || r.name.toLowerCase().includes(q) || r.roll_number.toLowerCase().includes(q)),
  );
  const byRoll = (a: ClassStudentRow, b: ClassStudentRow) => a.roll_number.localeCompare(b.roll_number);
  if (sort === "roll") return kept.sort(byRoll);
  return kept.sort((a, b) => (a.percentage ?? Infinity) - (b.percentage ?? Infinity) || byRoll(a, b));
}
