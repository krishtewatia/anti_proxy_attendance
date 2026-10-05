export interface AdminUserInfo {
  user_id: string;
  email: string;
  role: "ADMIN" | "TEACHER" | "STUDENT";
  name?: string | null;
  student_id?: string | null;
  is_active: boolean;
  created_at?: string | null;
}
