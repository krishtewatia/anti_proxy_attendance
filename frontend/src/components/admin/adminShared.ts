import type React from "react";
import type {
  AcademicStructureResponse,
  SessionResponse,
  StudentProfileResponse,
  TeacherProfileResponse,
} from "../../types";

export interface Banner {
  type: "success" | "error";
  text: string;
}

// What every admin tab gets from the dashboard that owns the data.
export interface AdminData {
  students: StudentProfileResponse[];
  teachers: TeacherProfileResponse[];
  academic: AcademicStructureResponse | null;
  sessions: SessionResponse[];
}

export interface AdminTabProps extends AdminData {
  notify: (banner: Banner) => void;
  reload: () => Promise<void> | void;
}

export function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export const BRANCH_OPTIONS = ["Data Science", "Computer Science", "AI & ML"];

export const smallButton: React.CSSProperties = { padding: "0.25rem 0.6rem", fontSize: "0.75rem" };
export const dangerButton: React.CSSProperties = { ...smallButton, color: "#b91c1c" };
export const fieldGap: React.CSSProperties = { marginBottom: "1rem" };
