export type SessionStatus = 'SCHEDULED' | 'ACTIVE' | 'COMPLETED' | 'FINALIZED';

export interface SessionCreate {
  course_name: string;
  classroom_id: string;
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
}
