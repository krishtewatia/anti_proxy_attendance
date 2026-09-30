export type SessionStatus = 'SCHEDULED' | 'ACTIVE' | 'COMPLETED';

export interface SessionCreate {
  course_name: string;
  classroom_id: string;
  start_time: string; // ISO 8601 UTC
  end_time: string; // ISO 8601 UTC
  required_presence_percentage?: number;
}

export interface SessionResponse {
  session_id: string;
  course_name: string;
  classroom_id: string;
  start_time: string;
  end_time: string;
  required_presence_percentage: number;
  status: SessionStatus;
  created_by: string;
}
