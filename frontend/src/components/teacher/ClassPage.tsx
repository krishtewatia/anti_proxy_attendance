import React, { useState } from "react";
import { api } from "../../services";
import type { AttendanceSummaryItem } from "../../types";
import { formatDateTime } from "../../utils/dates";
import {
  EDIT_WINDOW_CLOSED_TEXT,
  ROUND_NAMES,
  canEditFinal,
  cardAction,
  editWindowClosed,
  finalLabel,
  roundStatusText,
  splitByRound,
  type RoundInfo,
  type RoundName,
} from "../../utils/rounds.ts";

interface ClassPageProps {
  sessionId: string;
  info: RoundInfo;
  records: AttendanceSummaryItem[];
  // True while the class is running (rounds can be opened with the camera).
  running: boolean;
  onOpenRound: (round: RoundName) => Promise<void>;
  onFinalizeSession: () => void;
  finalizing: boolean;
  onChanged: () => Promise<void>;
}

// The class: ENTRY and EXIT as two cards (each opened on its own camera page),
// the final attendance once both are finalized (the only place marks are
// changed by hand, within the time window), and Finalize attendance.
export const ClassPage: React.FC<ClassPageProps> = ({ sessionId, info, records, running, onOpenRound, onFinalizeSession, finalizing, onChanged }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

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

  const act = (round: RoundName) => {
    const action = cardAction(info, round, running);
    if (!action || action.disabled) return;
    if (action.kind === "open") {
      void run(() => onOpenRound(round));
      return;
    }
    const { present, absent } = splitByRound(records, round);
    if (window.confirm(`Finalize ${round}? ${present.length} present, ${absent.length} absent. Corrections are then made on the final attendance.`)) {
      void run(() => api.finalizeRound(sessionId, round));
    }
  };

  const toggle = (student: AttendanceSummaryItem, round: RoundName) => {
    if (!canEditFinal(info, round)) return;
    const present = student.rounds?.[round]?.status === "PRESENT";
    void run(() => api.markRound(sessionId, round, student.identity, present ? "ABSENT" : "PRESENT"));
  };
  const closed = editWindowClosed(info);

  const shown = records.filter((r) => {
    const q = query.trim().toLowerCase();
    return !q || (r.student_name ?? "").toLowerCase().includes(q) || (r.roll_number ?? "").toLowerCase().includes(q);
  });

  return (
    <div className="erp-class-page">
      {error && (
        <div className="alert-banner error" role="alert">
          <span>{error}</span>
        </div>
      )}
      <div className="erp-round-cards">
        {ROUND_NAMES.map((round, index) => {
          const { present, absent } = splitByRound(records, round);
          const action = cardAction(info, round, running);
          return (
            <div key={round} className="erp-card erp-round-card">
              <div className="erp-round-card-title">
                <span>{index + 1}. {round}</span>
                <span className="erp-round-card-counts">{present.length} present · {absent.length} absent</span>
              </div>
              <div className="erp-round-card-status">{roundStatusText(info, round, formatDateTime)}</div>
              {action && (
                <button
                  type="button"
                  className={`erp-btn ${action.kind === "finalize" ? "erp-btn-secondary" : "erp-btn-primary"}`}
                  disabled={busy || action.disabled}
                  title={action.disabled ? "Finalize ENTRY first" : undefined}
                  onClick={() => act(round)}
                >
                  {action.label}
                </button>
              )}
            </div>
          );
        })}
      </div>

      <div className="erp-card" style={{ padding: "1rem" }}>
        <h2 className="erp-section-title" style={{ marginTop: 0 }}>Final attendance</h2>
        {!info.complete ? (
          <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--erp-text-muted)" }}>
            Shown once ENTRY and EXIT are both finalized. Marks can then be corrected here by hand for 48 hours after each round was finalized.
          </p>
        ) : (
          <>
            {closed ? (
              <div className="alert-banner warning" role="status" style={{ marginBottom: "0.5rem" }}>
                <span>{EDIT_WINDOW_CLOSED_TEXT}</span>
              </div>
            ) : (
              <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: "var(--erp-text-muted)" }}>
                Tap IN or OUT to correct a student by hand
                {info.editable_until ? `. You can make changes until ${formatDateTime(info.editable_until)}.` : "."}
              </p>
            )}
            <input type="search" className="erp-search-input" placeholder="Search name or roll no" aria-label="Search students" value={query} onChange={(e) => setQuery(e.target.value)} style={{ marginBottom: "0.5rem" }} />
            <div className="erp-students-list">
              {shown.map((student) => (
                <div key={student.identity} className={`erp-student-row ${student.status === "PRESENT" ? "row-present" : "row-absent"}`}>
                  <div className="erp-student-details">
                    <span className="erp-student-name">{student.student_name}</span>
                    <span className="erp-student-roll">{student.roll_number || "—"}</span>
                  </div>
                  <div style={{ display: "flex", gap: "0.35rem", alignItems: "center" }}>
                    {ROUND_NAMES.map((round) => {
                      const present = student.rounds?.[round]?.status === "PRESENT";
                      const editable = canEditFinal(info, round);
                      return (
                        <button
                          key={round}
                          type="button"
                          className={`status-badge ${present ? "present" : "absent"}`}
                          style={{ border: "none", cursor: editable ? "pointer" : "default", minHeight: "32px", whiteSpace: "nowrap" }}
                          disabled={busy || !editable}
                          title={editable ? `${round}: tap to mark ${present ? "absent" : "present"}` : EDIT_WINDOW_CLOSED_TEXT}
                          onClick={() => toggle(student, round)}
                        >
                          {round === "ENTRY" ? "IN" : "OUT"} {present ? "P" : "A"}
                        </button>
                      );
                    })}
                    <span style={{ fontSize: "0.8rem", fontWeight: 700, minWidth: "2.5rem", textAlign: "right" }}>{finalLabel(student.lectures, info)}</span>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {running && (
        <div className="erp-live-action-bar">
          <button
            type="button"
            className="erp-btn erp-btn-danger"
            onClick={onFinalizeSession}
            disabled={finalizing || !info.complete}
            title={info.complete ? undefined : "Finalize ENTRY and EXIT first"}
            style={{ minWidth: "220px", padding: "0.85rem 1.5rem", fontSize: "1rem" }}
          >
            {finalizing ? "Finalizing..." : "FINALIZE ATTENDANCE"}
          </button>
          {!info.complete && (
            <div style={{ fontSize: "0.8rem", color: "var(--erp-text-muted)", marginTop: "0.4rem" }}>
              Finalize ENTRY and EXIT first; the final attendance is given when both are done.
            </div>
          )}
        </div>
      )}
    </div>
  );
};
