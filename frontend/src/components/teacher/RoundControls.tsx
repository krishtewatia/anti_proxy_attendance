import React, { useState } from "react";
import { api } from "../../services";
import type { AttendanceSummaryItem } from "../../types";
import { formatDateTime, formatTime } from "../../utils/dates";
import {
  ROUND_NAMES,
  finalLabel,
  focusRound,
  nextStep,
  roundStatusText,
  splitByRound,
  stepActions,
  type RoundInfo,
  type RoundName,
} from "../../utils/rounds.ts";

interface RoundControlsProps {
  sessionId: string;
  info: RoundInfo;
  records: AttendanceSummaryItem[];
  manualMode: boolean;
  onManualMode: (on: boolean) => void;
  onChanged: () => Promise<void>;
}

// A class in two steps: ENTRY (camera, then finalize), then EXIT the same way,
// then the session. The panel shows, for the round in progress, who is present
// (newest first) and who is still absent; tap a name to change it by hand.
export const RoundControls: React.FC<RoundControlsProps> = ({ sessionId, info, records, manualMode, onManualMode, onChanged }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const round = focusRound(info);
  const step = nextStep(info);
  const { present, absent } = splitByRound(records, round, query);
  const canEdit = info.rounds[round]?.may_edit !== false && info.teacher_may_edit !== false;

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

  const act = (action: "open" | "close" | "finalize", name: RoundName) => {
    if (action === "finalize") {
      const counts = splitByRound(records, name);
      const ok = window.confirm(
        `Finalize ${name}? ${counts.present.length} present, ${counts.absent.length} absent.\n` +
          `The camera stops for ${name}; you can still change marks by hand for 24 hours.`,
      );
      if (!ok) return;
      void run(() => api.finalizeRound(sessionId, name));
      return;
    }
    void run(() => api.changeRound(sessionId, name, action));
  };

  const toggle = (student: AttendanceSummaryItem) => {
    const current = student.rounds?.[round]?.status === "PRESENT";
    void run(() => api.markRound(sessionId, round, student.identity, current ? "ABSENT" : "PRESENT"));
  };

  const row = (student: AttendanceSummaryItem, isPresent: boolean) => (
    <button
      key={student.identity}
      type="button"
      className={`erp-student-row ${isPresent ? "row-present" : "row-absent"}`}
      style={{ width: "100%", textAlign: "left", cursor: canEdit ? "pointer" : "default", border: "none" }}
      disabled={busy || !canEdit}
      title={canEdit ? `Tap to mark ${isPresent ? "absent" : "present"} in ${round}` : `${round} is locked`}
      onClick={() => toggle(student)}
    >
      <div className="erp-student-details">
        <span className="erp-student-name">{student.student_name}</span>
        <span className="erp-student-roll">
          {student.roll_number || "—"}
          {isPresent && student.rounds?.[round]?.at ? ` · ${formatTime(student.rounds[round]?.at)}` : ""}
          {student.rounds?.[round]?.source === "MANUAL" ? " · by hand" : ""}
        </span>
      </div>
      <span style={{ fontSize: "0.75rem", fontWeight: 600 }}>{finalLabel(student.lectures, info)}</span>
    </button>
  );

  return (
    <div style={{ display: "grid", gap: "0.75rem", gridTemplateColumns: "minmax(0, 1fr)" }}>
      <div className="erp-card" style={{ padding: "0.75rem 1rem", display: "grid", gap: "0.5rem" }}>
        <ol style={{ margin: 0, paddingLeft: "1.1rem", display: "grid", gap: "0.25rem", fontSize: "0.85rem" }}>
          {ROUND_NAMES.map((name) => (
            <li key={name} style={{ fontWeight: step === name ? 700 : 400 }}>
              {name}: {roundStatusText(info, name, formatDateTime)}
            </li>
          ))}
          <li style={{ fontWeight: step === "FINALIZE" ? 700 : 400 }}>
            Session: {info.complete ? "ready to finalize (button below)" : "after ENTRY and EXIT are finalized"}
          </li>
        </ol>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" }}>
          {stepActions(info).map((a) => (
            <button
              key={a.action}
              type="button"
              className={`erp-btn ${a.action === "finalize" ? "erp-btn-primary" : "erp-btn-secondary"}`}
              disabled={busy}
              onClick={() => act(a.action, a.round)}
            >
              {a.label}
            </button>
          ))}
          <label style={{ display: "flex", gap: "0.35rem", alignItems: "center", marginLeft: "auto", fontSize: "0.85rem" }}>
            <input type="checkbox" checked={manualMode} onChange={(e) => onManualMode(e.target.checked)} />
            Manual mode (no camera)
          </label>
        </div>
      </div>
      {error && (
        <div className="alert-banner error" role="alert">
          <span>{error}</span>
        </div>
      )}
      {!canEdit && (
        <div className="alert-banner warning">
          <span>{round} is locked. Ask an administrator to unlock it.</span>
        </div>
      )}
      <input
        type="search"
        className="erp-search-input"
        placeholder="Search name or roll no"
        aria-label="Search students"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
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
