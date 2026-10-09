// Account management: the rules the screens apply before they call the API.

export const MIN_PASSWORD_LENGTH = 8;
export const MIN_ADMIN_PASSWORD_LENGTH = 12;

// Checks a password change before it is sent. Returns the message to show, or null.
export function validatePasswordChange(current: string, next: string, confirm: string): string | null {
  if (!current) {
    return "Enter your current password.";
  }
  if (next.length < MIN_PASSWORD_LENGTH) {
    return `The new password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  if (next === current) {
    return "The new password must be different from the current one.";
  }
  if (next !== confirm) {
    return "The two new passwords do not match.";
  }
  return null;
}

// True when an API error says the account must change its password first.
export function isPasswordChangeRequired(message: string): boolean {
  return message.toLowerCase().includes("must change your password");
}

// "DS-B, ds-c ,," -> ["DS-B", "ds-c"]
export function splitList(text: string): string[] {
  const seen: string[] = [];
  for (const part of text.split(",")) {
    const value = part.trim();
    if (value && !seen.includes(value)) {
      seen.push(value);
    }
  }
  return seen;
}

function sameList(a: string[] | undefined, b: string[] | undefined): boolean {
  const left = a ?? [];
  const right = b ?? [];
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

export interface StudentEditFields {
  name: string;
  email: string;
  student_id: string;
  roll_number: string;
  // The student's class, by its code.
  class_code: string;
}

// Only what the administrator actually changed is sent, so an untouched
// field can never overwrite something on the server.
export function studentEditChanges(
  original: StudentEditFields,
  edited: StudentEditFields,
): Partial<StudentEditFields> {
  const changes: Partial<StudentEditFields> = {};
  for (const key of ["name", "email", "student_id", "roll_number"] as const) {
    const value = edited[key].trim();
    if (value !== (original[key] ?? "").trim()) {
      changes[key] = value;
    }
  }
  const classCode = edited.class_code.trim().toUpperCase();
  if (classCode !== (original.class_code ?? "").trim().toUpperCase()) {
    changes.class_code = classCode;
  }
  return changes;
}

export interface TeacherEditFields {
  name: string;
  email: string;
  teacher_id: string;
  department: string;
  assigned_classes: string[];
  assigned_subjects: string[];
}

export function teacherEditChanges(
  original: TeacherEditFields,
  edited: TeacherEditFields,
): Partial<TeacherEditFields> {
  const changes: Partial<TeacherEditFields> = {};
  for (const key of ["name", "email", "teacher_id", "department"] as const) {
    const value = edited[key].trim();
    if (value !== (original[key] ?? "").trim()) {
      changes[key] = value;
    }
  }
  if (!sameList(original.assigned_classes, edited.assigned_classes)) {
    changes.assigned_classes = edited.assigned_classes;
  }
  if (!sameList(original.assigned_subjects, edited.assigned_subjects)) {
    changes.assigned_subjects = edited.assigned_subjects;
  }
  return changes;
}

// What the confirmation says before a student ID is changed.
export function studentIdChangeWarning(oldId: string, newId: string): string {
  return (
    `Change the student ID from ${oldId} to ${newId}?\n\n` +
    "Attendance history, the photo and face recognition stay with the student. " +
    "Reports and exports will show the new ID from now on."
  );
}

export interface AdminAccount {
  user_id: string;
  email: string;
  name: string;
  must_change_password: boolean;
  created_at?: string | null;
}

// An administrator can delete another administrator, never themself and never the last one.
export function adminDeleteBlockedReason(
  target: AdminAccount,
  currentUserId: string,
  totalAdmins: number,
): string | null {
  if (target.user_id === currentUserId) {
    return "You cannot delete your own account.";
  }
  if (totalAdmins <= 1) {
    return "The last administrator cannot be deleted.";
  }
  return null;
}
