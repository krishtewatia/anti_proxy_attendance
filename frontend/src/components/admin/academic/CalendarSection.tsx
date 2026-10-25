import React, { useCallback, useEffect, useState } from "react";
import { api } from "../../../services";
import { audienceLabel, type CalendarEntry, type OrgClass } from "../../../utils/organisation.ts";
import { formatDate } from "../../../utils/dates.ts";
import { dangerButton, errorText, fieldGap } from "../adminShared.ts";
import type { AcademicSectionProps } from "../AcademicSetupTab";

// Days without teaching. A holiday covers the whole year; a cancelled class
// covers one class on one day. Neither counts as "attendance not entered".
export const CalendarSection: React.FC<AcademicSectionProps> = ({ cohort, groupSets, notify }) => {
  const [entries, setEntries] = useState<CalendarEntry[]>([]);
  const [classes, setClasses] = useState<OrgClass[]>([]);
  const [date, setDate] = useState("");
  const [reason, setReason] = useState("");
  const [classId, setClassId] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [list, classList] = await Promise.all([api.getCalendar(cohort.cohort_id), api.getOrgClasses(cohort.cohort_id)]);
      setEntries(list);
      setClasses(classList);
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to load the calendar: ${errorText(err)}` });
    }
  }, [cohort.cohort_id, notify]);

  useEffect(() => {
    void load();
  }, [load]);

  const classLabel = (id: string | null) => {
    if (!id) return "Whole year (holiday)";
    const found = classes.find((c) => c.class_id === id);
    return found ? `${found.label.split(" - ")[0]} · ${audienceLabel(found.audience, groupSets)}` : id;
  };

  const add = async () => {
    setBusy(true);
    try {
      await api.addCalendarEntry({ cohort_id: cohort.cohort_id, date, reason, class_id: classId || null });
      notify({ type: "success", text: `${formatDate(date)} recorded.` });
      setDate("");
      setReason("");
      setClassId("");
      await load();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to record the day: ${errorText(err)}` });
    } finally {
      setBusy(false);
    }
  };

  const remove = async (entry: CalendarEntry) => {
    if (!window.confirm(`Remove ${formatDate(entry.date)} (${entry.reason})?`)) return;
    try {
      await api.deleteCalendarEntry(entry.exception_id);
      notify({ type: "success", text: `${formatDate(entry.date)} removed.` });
      await load();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to remove: ${errorText(err)}` });
    }
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: "1.5rem" }}>
      <form
        className="erp-card"
        style={{ padding: "1.5rem" }}
        onSubmit={(e) => {
          e.preventDefault();
          void add();
        }}
      >
        <h2 className="erp-section-title" style={{ marginTop: 0 }}>Add a day without teaching</h2>
        <div className="erp-form-grid-2" style={fieldGap}>
          <div className="form-group">
            <label className="form-label" htmlFor="calendar-date">
              Date
            </label>
            <input id="calendar-date" type="date" required className="auth-input" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="calendar-reason">
              Reason
            </label>
            <input
              id="calendar-reason"
              required
              maxLength={200}
              className="auth-input"
              placeholder="e.g. Diwali"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
        </div>
        <div className="form-group" style={fieldGap}>
          <label className="form-label" htmlFor="calendar-class">
            Applies to
          </label>
          <select id="calendar-class" className="erp-select-input" value={classId} onChange={(e) => setClassId(e.target.value)}>
            <option value="">Whole year (holiday)</option>
            {classes.map((c) => (
              <option key={c.class_id} value={c.class_id}>
                {classLabel(c.class_id)} (cancelled class)
              </option>
            ))}
          </select>
        </div>
        <button type="submit" className="erp-btn erp-btn-primary" disabled={busy}>
          {busy ? "Saving..." : "Add"}
        </button>
      </form>

      <div className="erp-table-container">
        <table className="erp-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Applies to</th>
              <th>Reason</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {entries.length === 0 && (
              <tr>
                <td colSpan={4} style={{ textAlign: "center", color: "var(--erp-text-muted)" }}>
                  No holidays or cancelled classes recorded.
                </td>
              </tr>
            )}
            {entries.map((entry) => (
              <tr key={entry.exception_id}>
                <td style={{ whiteSpace: "nowrap" }}>{formatDate(entry.date)}</td>
                <td>{classLabel(entry.class_id)}</td>
                <td>{entry.reason}</td>
                <td>
                  <button type="button" className="erp-btn erp-btn-secondary" style={dangerButton} onClick={() => void remove(entry)}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
