import React, { useState } from "react";
import type { AttendanceSummaryItem } from "../../types";
import { formatTime } from "../../utils/dates";
import { splitByRound, type RoundName } from "../../utils/rounds.ts";

interface RoundPanelProps {
  round: RoundName;
  records: AttendanceSummaryItem[];
  busy: boolean;
  error: string | null;
  onFinalize: () => void;
  onBack: () => void;
}

// Beside the camera on a round's page: who the camera has marked present in
// this round (newest first) and who is still absent. Read-only: only the camera
// marks during a round; corrections are made on the final attendance.
export const RoundPanel: React.FC<RoundPanelProps> = ({ round, records, busy, error, onFinalize, onBack }) => {
  const [query, setQuery] = useState("");
  const { present, absent } = splitByRound(records, round, query);

  const row = (student: AttendanceSummaryItem, isPresent: boolean) => (
    <div key={student.identity} className={`erp-student-row ${isPresent ? "row-present" : "row-absent"}`}>
      <div className="erp-student-details">
        <span className="erp-student-name">{student.student_name}</span>
        <span className="erp-student-roll">
          {student.roll_number || "—"}
          {isPresent && student.rounds?.[round]?.at ? ` · ${formatTime(student.rounds[round]?.at)}` : ""}
        </span>
      </div>
    </div>
  );

  return (
    <div style={{ display: "grid", gap: "0.75rem", gridTemplateColumns: "minmax(0, 1fr)" }}>
      <div className="erp-card erp-round-actions">
        <strong>{round}: the camera marks students present</strong>
        <div className="erp-round-actions-buttons">
          <button type="button" className="erp-btn erp-btn-primary" disabled={busy} onClick={onFinalize}>
            Finalize {round}
          </button>
          <button type="button" className="erp-btn erp-btn-secondary" disabled={busy} onClick={onBack}>
            Back to class
          </button>
        </div>
      </div>
      {error && (
        <div className="alert-banner error" role="alert">
          <span>{error}</span>
        </div>
      )}
      <input type="search" className="erp-search-input" placeholder="Search name or roll no" aria-label="Search students" value={query} onChange={(e) => setQuery(e.target.value)} />
      <div className="erp-roster-header">
        <h3 className="erp-roster-title">{round}: present</h3>
        <div className="erp-roster-count">{present.length}</div>
      </div>
      <div className="erp-students-list">{present.map((s) => row(s, true))}</div>
      <div className="erp-roster-header">
        <h3 className="erp-roster-title">{round}: still absent</h3>
        <div className="erp-roster-count">{absent.length}</div>
      </div>
      <div className="erp-students-list">{absent.map((s) => row(s, false))}</div>
    </div>
  );
};
