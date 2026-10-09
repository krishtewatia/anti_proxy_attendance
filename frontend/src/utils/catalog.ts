// Classes and subjects: shared types and the rules the screens apply.

export type CatalogStatus = "ACTIVE" | "ARCHIVED";

// What the registration form may see without signing in.
export interface PublicClass {
  class_code: string;
  branch: string;
  section: string;
}

export interface AdminClassRow extends PublicClass {
  class_id: string;
  semester?: number | null;
  status: CatalogStatus;
  usage: { students: number; teachers: number; sessions: number };
  in_use: boolean;
}

export interface AdminSubjectRow {
  subject_id: string;
  name: string;
  code?: string | null;
  branch?: string | null;
  status: CatalogStatus;
  usage: { teachers: number; sessions: number };
  in_use: boolean;
}

const CLASS_CODE = /^[A-Z0-9][A-Z0-9&_-]{1,19}$/;

// "ds-b " -> "DS-B"
export function normalizeClassCode(code: string): string {
  return code.trim().toUpperCase();
}

// Returns the message to show for a class code that cannot be used, or null.
export function validateClassCode(code: string): string | null {
  if (!CLASS_CODE.test(normalizeClassCode(code))) {
    return "A class code is 2 to 20 letters, digits, '-', '_' or '&' (for example DS-B).";
  }
  return null;
}

// "DS-B · Data Science, Section B"
export function classLabel(item: PublicClass): string {
  return `${item.class_code} · ${item.branch}, Section ${item.section}`;
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

// "2 students, 1 teacher" or "Not in use"
export function usageSummary(usage: Record<string, number>): string {
  const parts = Object.entries(usage)
    .filter(([, count]) => count > 0)
    .map(([kind, count]) => plural(count, kind.replace(/s$/, "")));
  return parts.length > 0 ? parts.join(", ") : "Not in use";
}

// Something that is in use can be archived but not deleted.
export function deleteBlockedReason(row: { in_use: boolean; usage: Record<string, number> }): string | null {
  if (!row.in_use) {
    return null;
  }
  return `In use (${usageSummary(row.usage)}). Archive it instead.`;
}

export interface ClassEditFields {
  class_code: string;
  branch: string;
  section: string;
  semester: string;
}

export interface ClassChanges {
  class_code?: string;
  branch?: string;
  section?: string;
  semester?: number;
  clear_semester?: boolean;
}

export function classEditFields(row: AdminClassRow): ClassEditFields {
  return {
    class_code: row.class_code,
    branch: row.branch,
    section: row.section,
    semester: row.semester == null ? "" : String(row.semester),
  };
}

// Only what changed is sent. The code, branch and section of a class that is
// in use are never sent: the server would refuse them.
export function classEditChanges(row: AdminClassRow, edited: ClassEditFields): ClassChanges {
  const changes: ClassChanges = {};
  if (!row.in_use) {
    const code = normalizeClassCode(edited.class_code);
    if (code !== row.class_code) changes.class_code = code;
    if (edited.branch.trim() !== row.branch) changes.branch = edited.branch.trim();
    if (edited.section.trim().toUpperCase() !== row.section) changes.section = edited.section.trim().toUpperCase();
  }
  const before = row.semester == null ? "" : String(row.semester);
  const after = edited.semester.trim();
  if (after !== before) {
    if (after === "") {
      changes.clear_semester = true;
    } else {
      changes.semester = Number(after);
    }
  }
  return changes;
}

export interface SubjectEditFields {
  name: string;
  code: string;
  branch: string;
}

export function subjectEditChanges(row: AdminSubjectRow, edited: SubjectEditFields): Partial<SubjectEditFields> {
  const changes: Partial<SubjectEditFields> = {};
  if (!row.in_use && edited.name.trim() !== row.name) changes.name = edited.name.trim();
  if (edited.code.trim() !== (row.code ?? "")) changes.code = edited.code.trim();
  if (edited.branch.trim() !== (row.branch ?? "")) changes.branch = edited.branch.trim();
  return changes;
}

// The classes a form offers: the active ones, plus the one already chosen even
// if it has since been archived (so an edit form never silently changes it).
export function classChoices<T extends PublicClass>(active: T[], current?: string | null): PublicClass[] {
  const choices: PublicClass[] = [...active];
  if (current && !active.some((item) => item.class_code === current)) {
    choices.push({ class_code: current, branch: "archived class", section: "-" });
  }
  return choices;
}
