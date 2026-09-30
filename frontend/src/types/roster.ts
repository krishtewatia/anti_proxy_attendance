export interface SessionRosterUpdate {
  identities: string[];
}

export interface SessionRosterResponse {
  session_id: string;
  identities: string[];
}
