export type DirectionType = 'ENTRY' | 'EXIT' | 'UNRESOLVED';

export interface VisionEvidence {
  peak_similarity: number;
  mean_similarity: number;
  supporting_frames: number;
  total_frames: number;
  consistency_pct: number;
  margin_over_runner_up?: number | null;
  runner_up_identity?: string | null;
}

export interface VisionEventCreate {
  event_id: string;
  camera_id: string;
  track_id: number;
  identity: string;
  direction: DirectionType;
  timestamp: string; // ISO 8601 UTC
  evidence: VisionEvidence;
}

export interface VisionEventResponse {
  event_id: string;
  status: string; // 'accepted' | 'duplicate' | 'logged'
  message?: string | null;
  processed_at?: string | null;
}
