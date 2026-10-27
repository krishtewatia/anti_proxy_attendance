export interface TeacherRegisterRequest {
  name: string;
  email: string;
  password: string;
  // An internal key the server makes up; teachers are known by email.
  teacher_id?: string;
  department?: string;
  assigned_classes?: string[];
  assigned_subjects?: string[];
}

export interface TeacherProfileResponse {
  user_id: string;
  teacher_id: string;
  name: string;
  email: string;
  department: string;
  assigned_classes: string[];
  assigned_subjects: string[];
}

export interface TeacherSessionSummaryItem {
  // Timetable classes only: false until ENTRY and EXIT are both finalized.
  rounds_complete?: boolean | null;
  session_id: string;
  course_name: string;
  class_code?: string;
  subject?: string;
  total_students: number;
  present_count: number;
  attendance_percentage: number;
  status: string;
  // False when the session was created but attendance was never taken.
  was_taken?: boolean;
  start_time?: string | null;
  created_at?: string;
}

export interface TeacherDashboardResponse {
  teacher: TeacherProfileResponse;
  active_session?: TeacherSessionSummaryItem | null;
  previous_sessions: TeacherSessionSummaryItem[];
}

export interface TeacherAssignClassesRequest {
  assigned_classes: string[];
  assigned_subjects: string[];
}
