// What the backend stores. (COMPLETED is not written by it; kept for older data.)
export type SessionStatus = 'SCHEDULED' | 'ACTIVE' | 'COMPLETED' | 'FINALIZED';

export interface SessionCreate {
  course_name: string;
  // Not shown or asked for in the interface; the server fills in its default.
  classroom_id?: string;
  start_time: string; // ISO 8601 UTC
  end_time: string; // ISO 8601 UTC
  class_code?: string;
  subject?: string;
  branch?: string;
  section?: string;
  required_presence_percentage?: number;
}

export interface SessionResponse {
  session_id: string;
  course_name: string;
  classroom_id: string;
  start_time: string;
  end_time: string;
  class_code?: string;
  subject?: string;
  branch?: string;
  section?: string;
  required_presence_percentage: number;
  status: SessionStatus;
  created_by: string;
  // Sent by the administrator's session list only.
  teacher_name?: string | null;
  total_students?: number | null;
  present_count?: number | null;
  was_taken?: boolean | null;
}
