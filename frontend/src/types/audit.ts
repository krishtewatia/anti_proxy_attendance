export type AuditActorRole = "TEACHER" | "STUDENT" | "ADMIN" | "SYSTEM";

export type AuditAction =
  | "USER_REGISTERED"
  | "USER_LOGIN"
  | "USER_LOGOUT"
  | "SESSION_CREATED"
  | "SESSION_UPDATED"
  | "ROSTER_UPDATED"
  | "ATTENDANCE_FINALIZED"
  | "ATTENDANCE_CORRECTED"
  | "STUDENT_PROFILE_CREATED"
  | "STUDENT_PROFILE_UPDATED";

export type AuditResourceType =
  | "USER"
  | "SESSION"
  | "SESSION_ROSTER"
  | "ATTENDANCE"
  | "STUDENT_PROFILE"
  | "SYSTEM";

export interface AuditEventResponse {
  audit_id: string;
  actor_user_id: string;
  actor_role: AuditActorRole;
  action: AuditAction;
  resource_type: AuditResourceType;
  resource_id: string;
  timestamp: string;
  metadata: Record<string, unknown>;
}
