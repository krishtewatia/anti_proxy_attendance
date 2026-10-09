// Registration approval: shared types and the rules the admin screen applies
// before it calls the API.

export interface PendingStudent {
  user_id: string;
  email: string;
  name?: string | null;
  student_id?: string | null;
  roll_number?: string | null;
  branch?: string | null;
  section?: string | null;
  class_code?: string | null;
  has_photo?: boolean;
  photo_url?: string | null;
  registered_at?: string | null;
}

export interface PendingTeacher {
  user_id: string;
  email: string;
  name?: string | null;
  teacher_id?: string | null;
  department?: string | null;
  requested_classes?: string[];
  requested_subjects?: string[];
  registered_at?: string | null;
}

export interface PendingAccount {
  user_id: string;
  email: string;
  role: string;
  registered_at?: string | null;
}

export interface PendingPhotoChange {
  identity: string;
  student_id: string;
  name?: string | null;
  class_code?: string | null;
  requested_at?: string | null;
  current_photo_url?: string | null;
  new_photo_url: string;
}

export interface PendingCounts {
  students: number;
  teachers: number;
  accounts: number;
  photo_changes: number;
  total: number;
}

export interface PendingApprovals {
  students: PendingStudent[];
  teachers: PendingTeacher[];
  accounts: PendingAccount[];
  photo_changes: PendingPhotoChange[];
  counts: PendingCounts;
}

export const EMPTY_COUNTS: PendingCounts = {
  students: 0,
  teachers: 0,
  accounts: 0,
  photo_changes: 0,
  total: 0,
};

// Text for the count badge on the navigation item; nothing when there is nothing to review.
export function pendingBadgeText(total: number | undefined | null): string | null {
  if (!total || total <= 0 || !Number.isFinite(total)) {
    return null;
  }
  return total > 99 ? "99+" : String(Math.floor(total));
}

// Class codes as the API stores them: trimmed, upper-case, no duplicates.
export function normalizeClassCodes(codes: string[]): string[] {
  const seen: string[] = [];
  for (const raw of codes) {
    const code = raw.trim().toUpperCase();
    if (code && !seen.includes(code)) {
      seen.push(code);
    }
  }
  return seen;
}

// A teacher cannot be approved without at least one class, and only with
// classes that exist. Returns the message to show, or null when it is valid.
export function validateTeacherApproval(selected: string[], availableClasses: string[]): string | null {
  const chosen = normalizeClassCodes(selected);
  if (chosen.length === 0) {
    return "Assign at least one class before approving a teacher.";
  }
  const known = normalizeClassCodes(availableClasses);
  const unknown = chosen.filter((code) => !known.includes(code));
  if (unknown.length > 0) {
    return `Unknown class: ${unknown.join(", ")}`;
  }
  return null;
}

// A student is approved into a class: both parts must be present.
export function validateStudentApproval(branch: string, section: string): string | null {
  if (!branch.trim() || !section.trim()) {
    return "Confirm the student's branch and section before approving.";
  }
  return null;
}

// "3 days ago" style age of a registration, for the list. Purged at 14 days.
export function registrationAge(registeredAt: string | null | undefined, now: Date = new Date()): string {
  if (!registeredAt) {
    return "";
  }
  const then = new Date(registeredAt);
  if (Number.isNaN(then.getTime())) {
    return "";
  }
  const days = Math.floor((now.getTime() - then.getTime()) / 86_400_000);
  if (days <= 0) {
    return "today";
  }
  return days === 1 ? "1 day ago" : `${days} days ago`;
}

export const PENDING_MAX_AGE_DAYS = 14;

// Days left before an untouched registration is removed automatically.
export function daysUntilPurge(registeredAt: string | null | undefined, now: Date = new Date()): number | null {
  if (!registeredAt) {
    return null;
  }
  const then = new Date(registeredAt);
  if (Number.isNaN(then.getTime())) {
    return null;
  }
  const elapsed = (now.getTime() - then.getTime()) / 86_400_000;
  return Math.max(0, Math.ceil(PENDING_MAX_AGE_DAYS - elapsed));
}

// True when the login error is the "awaiting approval" answer.
export function isPendingApprovalError(message: string): boolean {
  return message.toLowerCase().includes("awaiting admin approval");
}
