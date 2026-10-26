import React, { useCallback, useEffect, useState } from "react";
import { api } from "../../services";
import { DAY_NAMES, weekGrid, type OrgSlot } from "../../utils/organisation.ts";
import { SLOT_STATE, audienceShort, type TeacherSlot, type TeacherTimetable } from "../../utils/teaching.ts";

interface TodayTimetableProps {
  // Opens the attendance screen on a session (started now, or already running).
  onOpenSession: (sessionId: string, slot: TeacherSlot) => Promise<void> | void;
}

// The teacher's day from the timetable: each class with Start / Open, and the
// week underneath. Each section's and group's class is its own session.
export const TodayTimetable: React.FC<TodayTimetableProps> = ({ onOpenSession }) => {
  const [data, setData] = useState<TeacherTimetable | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.getTeacherTimetable());
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const start = async (slot: TeacherSlot) => {
    setBusy(slot.slot_id);
    setError(null);
    try {
      const session = await api.startFromSlot(slot.slot_id, data?.date);
      if (session.status === "SCHEDULED") await api.startSession(session.session_id);
      await onOpenSession(session.session_id, slot);
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  if (!data) return error ? <div className="alert-banner error" style={{ marginBottom: "1rem" }}><span>{error}</span></div> : null;
  if (data.class_count === 0) return null;

  // The week grid shares the admin's week view (start/end, periods, label).
  const grid = weekGrid(
    data.week.map((s) => ({
      ...s, version_id: "", row: 0, start_minute: Number(s.start.slice(0, 2)) * 60 + Number(s.start.slice(3)), end_minute: 0,
      note: "", flags: [], subject_key: s.code, label: `${s.subject} · ${audienceShort(s.audience)}`,
    })) as unknown as OrgSlot[],
  );

  return (
    <div style={{ display: "grid", gap: "1.5rem", marginBottom: "1.5rem", gridTemplateColumns: "minmax(0, 1fr)" }}>
      {error && <div className="alert-banner error" role="alert"><span>{error}</span></div>}
      <div className="erp-card" style={{ padding: "1.25rem 1.5rem" }}>
        <h2 className="erp-section-title" style={{ marginTop: 0 }}>Today</h2>
        {data.today.length === 0 ? (
          <p style={{ margin: 0, color: "var(--erp-text-muted)" }}>No classes today.</p>
        ) : (
          <div style={{ display: "grid", gap: "0.6rem" }}>
            {data.today.map((slot) => {
              const state = SLOT_STATE[slot.state ?? "UPCOMING"];
              return (
                <div key={slot.slot_id} style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "center", justifyContent: "space-between", padding: "0.6rem 0", borderBottom: "1px solid var(--erp-border)" }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 600 }}>{slot.start}–{slot.end} · {slot.subject}</div>
                    <div style={{ fontSize: "0.8rem", color: "var(--erp-text-muted)" }}>
                      {audienceShort(slot.audience)} · {slot.periods === 2 ? "double period" : "single period"}{slot.room ? ` · ${slot.room}` : ""}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                    <span className={`status-badge ${state.badge}`}>{state.label}</span>
                    {state.action && (
                      <button type="button" className="erp-btn erp-btn-primary" disabled={busy !== null} onClick={() => void start(slot)}>
                        {busy === slot.slot_id ? "Opening..." : state.action}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {grid.rows.length > 0 && (
        <div className="erp-card" style={{ padding: "1.25rem 1.5rem" }}>
          <h2 className="erp-section-title" style={{ marginTop: 0 }}>This week</h2>
          <div className="erp-table-container">
            <table className="erp-table">
              <thead>
                <tr>
                  <th>Time</th>
                  {grid.days.map((d) => <th key={d}>{DAY_NAMES[d]}</th>)}
                </tr>
              </thead>
              <tbody>
                {grid.rows.map((row) => (
                  <tr key={`${row.start}-${row.end}`}>
                    <td style={{ whiteSpace: "nowrap", fontWeight: 600 }}>{row.start}–{row.end}</td>
                    {grid.days.map((d) => (
                      <td key={d} style={{ fontSize: "0.8rem", minWidth: "8rem" }}>
                        {row.cells[d].map((s) => <div key={s.slot_id}>{s.label}</div>)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
