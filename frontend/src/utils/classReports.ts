// Attendance reports for timetable classes: the student's subject-wise view
// (in lectures, "not entered" apart) and the teacher's downloads.
// Pure helpers only.

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
}

export interface ClassSessionItem {
  session_id: string;
  date: string | null;
  time: string;
  status: string;
  rounds_held: string[];
  periods: number | null;
}

export function percentLabel(value: number | null): string {
  return value === null ? "—" : `${value}%`;
}

// The URL path of a class's download (class ids contain ":" and "/").
export function classPath(classId: string, file: "students.csv" | "register.csv" | "sessions"): string {
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
