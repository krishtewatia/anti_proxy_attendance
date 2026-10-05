export type StudentLiveState = 'INSIDE' | 'OUTSIDE' | 'NOT_SEEN';
export type SessionLiveState = 'UPCOMING' | 'LIVE' | 'ENDED';

export interface StudentLiveItem {
  identity: string;
  is_rostered: boolean;
  state: StudentLiveState;
  last_event_time: string | null;
  last_event_direction: 'ENTRY' | 'EXIT' | null;
  presence_duration_seconds: number;
  presence_percentage: number;
  projected_status: 'PRESENT' | 'ABSENT';
  is_on_track: boolean;
  no_exit_observed: boolean;
  anomalies: string[];
}

export interface CameraHealthItem {
  camera_id: string;
  classroom_id: string;
  status: string;
  role?: string | null;
  fps?: number | null;
  last_seen?: string | null;
  heartbeat_age_seconds?: number | null;
  is_stale: boolean;
}

export interface RecentLiveEvent {
  event_id: string;
  identity: string;
  direction: 'ENTRY' | 'EXIT';
  timestamp: string;
  camera_id?: string | null;
  confidence?: number | null;
}

export interface SessionLiveSnapshotResponse {
  session_id: string;
  course_name: string;
  classroom_id: string;
  session_state: SessionLiveState;
  status: string;
  start_time: string;
  end_time: string;
  required_presence_percentage: number;
  cameras: CameraHealthItem[];
  students: StudentLiveItem[];
  recent_events: RecentLiveEvent[];
  server_time: string;
  is_stale: boolean;
}
