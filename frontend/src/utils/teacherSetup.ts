// Teachers choose their own subjects and, for each, the sections or groups
// they teach; an administrator approves. Pure helpers only.

export interface SetupTarget {
  kind: "SECTION" | "GROUP";
  code: string;
  label: string;
  class_id: string;
}

export interface SetupSubject {
  subject_key: string;
  code: string;
  name: string;
  type: string;
  targets: SetupTarget[];
}

export interface TeacherSetupOptions {
  cohorts: { cohort_id: string; name: string; year: number; branch: string; subjects: SetupSubject[] }[];
}

export interface ClassLabel {
  class_id: string;
  cohort_id: string;
  subject: string;
  code: string;
  target: string;
}

export interface TeacherRequest {
  request_id: string;
  status: "PENDING" | "APPROVED" | "REJECTED" | "WITHDRAWN";
  class_ids: string[];
  reason?: string | null;
  submitted_at?: string;
}

export interface MyTeacherSetup {
  approved: boolean;
  classes: ClassLabel[];
  latest_request: TeacherRequest | null;
}

export interface WaitingTeacherRequest extends TeacherRequest {
  user_id: string;
  name: string | null;
  email: string | null;
  change: boolean;
  classes: ClassLabel[];
}

// subject_key -> class ids ticked for it.
export type SubjectChoice = Record<string, string[]>;

export function choiceFromClassIds(subjects: SetupSubject[], classIds: string[]): SubjectChoice {
  const wanted = new Set(classIds);
  const out: SubjectChoice = {};
  for (const subject of subjects) {
    const ticked = subject.targets.filter((t) => wanted.has(t.class_id)).map((t) => t.class_id);
    if (ticked.length) out[subject.subject_key] = ticked;
  }
  return out;
}

export function classIdsOf(choice: SubjectChoice): string[] {
  return Object.values(choice).flat();
}

// The first thing missing, in the teacher's words, or null.
export function choiceProblem(choice: SubjectChoice): string | null {
  const keys = Object.keys(choice);
  if (keys.length === 0) return "Choose at least one subject.";
  if (keys.some((k) => choice[k].length === 0)) return "For each subject, choose the sections or groups you teach.";
  return null;
}

// "Computer Networks: Section A, Section B", one line per subject.
export function summaryLines(classes: ClassLabel[]): string[] {
  const bySubject = new Map<string, string[]>();
  for (const c of classes) bySubject.set(c.subject, [...(bySubject.get(c.subject) ?? []), c.target]);
  return [...bySubject.entries()].map(([subject, targets]) => `${subject}: ${targets.join(", ")}`);
}

export function teacherStatusCard(status: MyTeacherSetup | null): { tone: "info" | "warning" | "success" | "error"; title: string; text: string } {
  const latest = status?.latest_request;
  if (latest?.status === "PENDING") {
    return { tone: "warning", title: "Waiting for approval", text: "Your subjects and sections were sent. An administrator approves them, or adjusts them." };
  }
  if (latest?.status === "REJECTED" && !status?.classes.length) {
    return { tone: "error", title: "Not approved", text: `Reason: ${latest.reason ?? "—"}. Correct your choice and send it again.` };
  }
  if (status?.approved && status.classes.length) {
    return { tone: "success", title: "Approved", text: "These are your classes. To change them, send a new choice; these stay until it is approved." };
  }
  return { tone: "info", title: "Choose your subjects", text: "Choose the subjects you teach and, for each one, the sections or groups. An administrator approves them." };
}
