export interface StudentProfile {
  user_id: string;
  identity: string;
}

export interface StudentProfileBind {
  identity: string;
}

export interface StudentDirectoryItem {
  identity: string;
  name: string;
  email: string;
  student_id: string;
  roll_number?: string;
  branch?: string;
  section?: string;
  class_code?: string;
  has_biometric: boolean;
}

export interface StudentRegisterRequest {
  name: string;
  email: string;
  password: string;
  student_id: string;
  roll_number: string;
  // The class by its code; branch and section are the older way to name it.
  class_code?: string;
  branch?: string;
  section?: string;
  photo_base64?: string;
}

export interface StudentProfileResponse {
  user_id: string;
  identity: string;
  name: string;
  email: string;
  student_id: string;
  roll_number: string;
  branch: string;
  section: string;
  class_code: string;
  photo_url?: string;
  has_biometric: boolean;
  created_at?: string;
}

export interface SubjectAttendanceItem {
  subject: string;
  present: number;
  total: number;
  percentage: number;
}

export interface StudentAttendanceHistoryItem {
  session_id: string;
  course_name: string;
  subject: string;
  class_code: string;
  date_str: string;
  status: string;
}

export interface StudentAttendanceDashboardResponse {
  profile: StudentProfileResponse;
  overall_present: number;
  overall_total: number;
  // null when no session has been taken yet.
  overall_percentage: number | null;
  sessions_not_taken?: number;
  subjects: SubjectAttendanceItem[];
  history: StudentAttendanceHistoryItem[];
}
