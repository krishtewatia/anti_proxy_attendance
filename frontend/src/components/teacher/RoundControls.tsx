import React, { useState } from "react";
import { api } from "../../services";
import type { AttendanceSummaryItem } from "../../types";
import { ROUND_NAMES, lectureLabel, roundActions, type RoundInfo, type RoundName } from "../../utils/rounds.ts";

interface RoundControlsProps {
  sessionId: string;
  info: RoundInfo;
  records: AttendanceSummaryItem[];
  manualMode: boolean;
  onManualMode: (on: boolean) => void;
  onChanged: () => Promise<void>;
}

// ENTRY and EXIT rounds: the open/close bar, manual mode, and per student the
// two round marks (tap to toggle) and the lectures they give.
export const RoundControls: React.FC<RoundControlsProps> = ({ sessionId, info, records, manualMode, onManualMode, onChanged }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
      await onChanged();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const toggle = (student: AttendanceSummaryItem, round: RoundName) => {
    const current = student.rounds?.[round]?.status === "PRESENT";
    void run(() => api.markRound(sessionId, round, student.identity, current ? "ABSENT" : "PRESENT"));
  };

  return (
    <div style={{ display: "grid", gap: "0.75rem", gridTemplateColumns: "minmax(0, 1fr)" }}>
      <div className="erp-card" style={{ padding: "0.75rem 1rem", display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" }}>
        <strong style={{ marginRight: "0.5rem" }}>
          {info.open_round ? `${info.open_round} round is live` : "No round open"} · {info.periods === 2 ? "double period" : "single period"}
        </strong>
        {roundActions(info).map((a) => (
          <button
            key={a.round}
            type="button"
            className={`erp-btn ${a.action === "close" ? "erp-btn-secondary" : "erp-btn-primary"}`}
            disabled={busy}
            onClick={() => void run(() => api.changeRound(sessionId, a.round, a.action))}
          >
            {a.label}
          </button>
        ))}
        <label style={{ display: "flex", gap: "0.35rem", alignItems: "center", marginLeft: "auto", fontSize: "0.85rem" }}>
          <input type="checkbox" checked={manualMode} onChange={(e) => onManualMode(e.target.checked)} />
          Manual mode (no camera)
        </label>
      </div>
      {error && (
        <div className="alert-banner error" role="alert">
          <span>{error}</span>
        </div>
      )}
      {info.teacher_may_edit === false && (
        <div className="alert-banner warning">
          <span>This session can no longer be changed here. Ask an administrator to unlock it.</span>
        </div>
      )}
      <div className="erp-students-list">
        {records.map((student) => (
          <div key={student.identity} className={`erp-student-row ${student.status === "PRESENT" ? "row-present" : "row-absent"}`}>
            <div className="erp-student-details">
              <span className="erp-student-name">{student.student_name}</span>
              <span className="erp-student-roll">{student.roll_number || "—"}</span>
            </div>
            <div style={{ display: "flex", gap: "0.35rem", alignItems: "center" }}>
              {ROUND_NAMES.map((round) => {
                const present = student.rounds?.[round]?.status === "PRESENT";
                return (
                  <button
                    key={round}
                    type="button"
                    className={`status-badge ${present ? "present" : "absent"}`}
                    style={{ border: "none", cursor: "pointer" }}
                    title={`${round}: tap to mark ${present ? "absent" : "present"}`}
                    disabled={busy || info.teacher_may_edit === false}
                    onClick={() => toggle(student, round)}
                  >
                    {round === "ENTRY" ? "IN" : "OUT"} {present ? "P" : "A"}
                  </button>
                );
              })}
              <span style={{ fontSize: "0.8rem", fontWeight: 600, minWidth: "2.5rem", textAlign: "right" }}>
                {lectureLabel(student.lectures, info.periods)}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
