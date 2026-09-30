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
  presence_duration_seconds: number;
  presence_percentage: number;
  required_presence_percentage: number;
  status: string;
}

export interface AttendanceSessionResponse {
  session_id: string;
  records: AttendanceSummaryItem[];
}

export interface SessionFinalizationResponse {
  session_id: string;
  records: AttendanceRecord[];
}
