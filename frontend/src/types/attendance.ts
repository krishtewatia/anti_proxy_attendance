export type AttendanceStatus = 'PRESENT' | 'ABSENT';

export interface AttendanceInterval {
  entry_time: string; // ISO 8601 UTC
  exit_time: string; // ISO 8601 UTC
}

export interface AttendanceRecord {
  attendance_id: string;
  session_id: string;
  identity: string;
  presence_intervals: AttendanceInterval[];
  presence_duration_seconds: number;
  presence_percentage: number;
  required_presence_percentage: number;
  status: AttendanceStatus;
  updated_at?: string;
  created_at?: string;
}

export interface AttendanceSummaryItem {
  attendance_id: string;
  identity: string;
  student_id?: string;
  student_name?: string;
  roll_number?: string | null;
  presence_duration_seconds: number;
  presence_percentage: number;
  required_presence_percentage: number;
  status: string;
  manually_corrected?: boolean;
}

export interface AttendanceSessionResponse {
  session_id: string;
  course_name?: string;
  total_students?: number;
  present_count?: number;
  // false when the session was never taken: its records are not absences.
  was_taken?: boolean;
  records: AttendanceSummaryItem[];
}

export interface SessionFinalizationResponse {
  session_id: string;
  records: AttendanceRecord[];
}

export interface AttendanceCorrectionCreate {
  new_status: AttendanceStatus;
  new_presence_seconds: number;
  reason: string;
}

export interface AttendanceCorrectionResponse {
  correction_id: string;
  attendance_id: string;
  session_id: string;
  identity: string;
  corrected_by: string;
  previous_status: AttendanceStatus;
  new_status: AttendanceStatus;
  previous_presence_seconds: number;
  new_presence_seconds: number;
  reason: string;
  corrected_at: string;
}
