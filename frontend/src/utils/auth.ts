import type { UserRole } from "../types";

export const ROLE_DASHBOARD_MAP: Record<UserRole, string> = {
  TEACHER: "/dashboard/teacher",
  STUDENT: "/dashboard/student",
  ADMIN: "/dashboard/admin",
};

/**
 * Single source of truth for role -> dashboard path resolution.
 */
export function getDashboardPath(role?: UserRole | null): string {
  if (!role || !(role in ROLE_DASHBOARD_MAP)) {
    return "/";
  }
  return ROLE_DASHBOARD_MAP[role];
}

/**
 * Type guard for UserRole.
 */
export function isValidRole(role: string): role is UserRole {
  return role === "TEACHER" || role === "STUDENT" || role === "ADMIN";
}
