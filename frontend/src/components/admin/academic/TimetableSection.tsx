import React, { useCallback, useEffect, useState } from "react";
import { api } from "../../../services";
import {
  DAY_NAMES,
  FLAG_LABELS,
  audienceFilterLabel,
  audienceFilters,
  audienceLabel,
  decodeFilter,
  encodeFilter,
  matchesAudience,
  openFlags,
  versionInForce,
  weekGrid,
  type FlagKind,
  type ImportReport,
  type OrgSlot,
  type OrgSubject,
  type TimetableVersion,
} from "../../../utils/organisation.ts";
import { formatDate } from "../../../utils/dates.ts";
import { AdminModal } from "../shared";
import { errorText, fieldGap, smallButton } from "../adminShared.ts";
import type { AcademicSectionProps } from "../AcademicSetupTab";

const today = () => new Date().toISOString().slice(0, 10);

// Timetable versions: import a sheet (checked first), activate it from a date,
// look at the week, and work through the flagged rows.
export const TimetableSection: React.FC<AcademicSectionProps> = ({ cohort, groupSets, notify }) => {
  const [versions, setVersions] = useState<TimetableVersion[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [slots, setSlots] = useState<OrgSlot[]>([]);
  const [subjects, setSubjects] = useState<Record<string, OrgSubject>>({});
  const [view, setView] = useState<"week" | "flagged">("week");
  const [filter, setFilter] = useState(`SECTION:${cohort.sections[0] ?? ""}`);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<{ name: string; text: string; report: ImportReport } | null>(null);
  const [activating, setActivating] = useState<TimetableVersion | null>(null);
  const [effectiveFrom, setEffectiveFrom] = useState(today());
  const [resolving, setResolving] = useState<{ slot: OrgSlot; kind: FlagKind } | null>(null);
  const [resolveNote, setResolveNote] = useState("");

  const loadVersions = useCallback(async () => {
    try {
      const [list, subjectList] = await Promise.all([api.getTimetableVersions(cohort.cohort_id), api.getOrgSubjects()]);
      setVersions(list);
      setSubjects(Object.fromEntries(subjectList.map((s) => [s.key, s])));
      setSelected((current) => current || versionInForce(list, today())?.version_id || list[0]?.version_id || "");
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to load timetable versions: ${errorText(err)}` });
    }
  }, [cohort.cohort_id, notify]);

  const loadSlots = useCallback(async () => {
    if (!selected) {
      setSlots([]);
      return;
    }
    try {
      setSlots(await api.getTimetableSlots(selected));
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to load the timetable: ${errorText(err)}` });
    }
  }, [selected, notify]);

  useEffect(() => {
    void loadVersions();
  }, [loadVersions]);
  useEffect(() => {
    void loadSlots();
  }, [loadSlots]);

  const chooseFile = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      const text = await file.text();
      const report = await api.importTimetable(cohort.cohort_id, text, file.name, true);
      setPending({ name: file.name, text, report });
    } catch (err: unknown) {
      notify({ type: "error", text: `Could not check ${file.name}: ${errorText(err)}` });
    } finally {
      setBusy(false);
    }
  };

  const storeDraft = async () => {
    if (!pending) return;
    setBusy(true);
    try {
      const stored = await api.importTimetable(cohort.cohort_id, pending.text, pending.name, false);
      notify({ type: "success", text: `${pending.name} stored as a draft. Check it, then activate it from a date.` });
      setPending(null);
      setSelected(stored.version_id ?? "");
      await loadVersions();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to store ${pending.name}: ${errorText(err)}` });
    } finally {
      setBusy(false);
    }
  };

  const activate = async () => {
    if (!activating) return;
    setBusy(true);
    try {
      await api.activateTimetableVersion(activating.version_id, effectiveFrom);
      notify({ type: "success", text: `Timetable in force from ${formatDate(effectiveFrom)}. Earlier days keep the earlier timetable.` });
      setActivating(null);
      await loadVersions();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to activate: ${errorText(err)}` });
    } finally {
      setBusy(false);
    }
  };

  const resolve = async () => {
    if (!resolving) return;
    setBusy(true);
    try {
      await api.resolveTimetableFlag(resolving.slot.slot_id, resolving.kind, resolveNote);
      notify({ type: "success", text: `Marked as checked: ${resolving.slot.label}.` });
      setResolving(null);
      setResolveNote("");
      await loadSlots();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to save: ${errorText(err)}` });
    } finally {
      setBusy(false);
    }
  };

  const inForce = versionInForce(versions, today());
  const active = decodeFilter(filter);
  const shown = slots.filter((s) => matchesAudience(s.audience, active));
  const flagged = slots.filter((s) => openFlags(s).length > 0);
  const grid = weekGrid(shown);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: "1.5rem" }}>
      <div className="erp-card" style={{ padding: "1.25rem 1.5rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
          <div>
            <h2 className="erp-section-title" style={{ margin: 0 }}>Timetable versions</h2>
            <p style={{ margin: "0.25rem 0 0", fontSize: "0.875rem", color: "var(--erp-text-muted)" }}>
              {inForce ? `In force today: ${inForce.source_name}, since ${formatDate(inForce.effective_from)}.` : "No timetable is in force yet."}
            </p>
          </div>
          <label className="erp-btn erp-btn-primary" style={{ cursor: busy ? "wait" : "pointer" }}>
            {busy && !pending ? "Checking..." : "Import a sheet (CSV)"}
            <input
              type="file"
              accept=".csv,text/csv"
              style={{ display: "none" }}
              disabled={busy}
              onChange={(e) => {
                void chooseFile(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
          </label>
        </div>

        {versions.length > 0 && (
          <div className="erp-table-container" style={{ marginTop: "1rem" }}>
            <table className="erp-table">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Imported</th>
                  <th>Slots</th>
                  <th>Flagged</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {versions.map((v) => (
                  <tr key={v.version_id} style={v.version_id === selected ? { background: "var(--erp-surface-subtle)" } : undefined}>
                    <td style={{ fontWeight: 600 }}>{v.source_name}</td>
                    <td>{formatDate(v.created_at)}</td>
                    <td>{v.slots}</td>
                    <td>{v.flagged_slots}</td>
                    <td>
                      {v.status === "DRAFT" ? (
                        <span className="status-badge completed">Draft</span>
                      ) : v.version_id === inForce?.version_id ? (
                        <span className="status-badge present">In force</span>
                      ) : v.effective_from && v.effective_from > today() ? (
                        <span className="status-badge active">From {formatDate(v.effective_from)}</span>
                      ) : (
                        <span className="status-badge completed">Earlier version</span>
                      )}
                    </td>
                    <td style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                      <button type="button" className="erp-btn erp-btn-secondary" style={smallButton} onClick={() => setSelected(v.version_id)}>
                        View
                      </button>
                      {v.status === "DRAFT" && (
                        <button
                          type="button"
                          className="erp-btn erp-btn-primary"
                          style={smallButton}
                          onClick={() => {
                            setActivating(v);
                            setEffectiveFrom(today());
                          }}
                        >
                          Activate
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selected && (
        <div>
          <div className="erp-table-action-bar">
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <button
                type="button"
                className={`erp-btn ${view === "week" ? "erp-btn-primary" : "erp-btn-secondary"}`}
                style={smallButton}
                onClick={() => setView("week")}
              >
                Week
              </button>
              <button
                type="button"
                className={`erp-btn ${view === "flagged" ? "erp-btn-primary" : "erp-btn-secondary"}`}
                style={smallButton}
                onClick={() => setView("flagged")}
              >
                To check ({flagged.length})
              </button>
            </div>
            {view === "week" && (
              <select aria-label="Show the week of" className="erp-select-input" value={filter} onChange={(e) => setFilter(e.target.value)}>
                {audienceFilters(cohort)
                  .filter((f) => f.kind !== "ALL")
                  .map((f) => (
                    <option key={encodeFilter(f)} value={encodeFilter(f)}>
                      {audienceFilterLabel(f)}
                    </option>
                  ))}
              </select>
            )}
          </div>

          {view === "week" ? (
            <div className="erp-table-container">
              <table className="erp-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    {grid.days.map((day) => (
                      <th key={day}>{DAY_NAMES[day]}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {grid.rows.length === 0 && (
                    <tr>
                      <td colSpan={grid.days.length + 1} style={{ textAlign: "center", color: "var(--erp-text-muted)" }}>
                        No classes for {audienceFilterLabel(active)} in this version.
                      </td>
                    </tr>
                  )}
                  {grid.rows.map((row) => (
                    <tr key={`${row.start}-${row.end}`}>
                      <td style={{ whiteSpace: "nowrap", fontWeight: 600 }}>
                        {row.start}–{row.end}
                      </td>
                      {grid.days.map((day) => (
                        <td key={day} style={{ verticalAlign: "top", minWidth: "8rem" }}>
                          {row.cells[day].map((slot) => (
                            <SlotCell
                              key={slot.slot_id}
                              slot={slot}
                              name={subjects[slot.subject_key]?.name ?? slot.subject_key}
                              showGroup={active.kind === "SET"}
                            />
                          ))}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="erp-table-container">
              <table className="erp-table">
                <thead>
                  <tr>
                    <th>Sheet row</th>
                    <th>Slot</th>
                    <th>Taught to</th>
                    <th>To check</th>
                  </tr>
                </thead>
                <tbody>
                  {flagged.length === 0 && (
                    <tr>
                      <td colSpan={4} style={{ textAlign: "center", color: "var(--erp-text-muted)" }}>
                        Nothing left to check in this version.
                      </td>
                    </tr>
                  )}
                  {flagged.map((slot) => (
                    <tr key={slot.slot_id}>
                      <td>{slot.row}</td>
                      <td>
                        <div style={{ fontWeight: 600 }}>
                          {DAY_NAMES[slot.day]} {slot.start}–{slot.end}
                          {slot.periods > 1 ? ` (${slot.periods} periods)` : ""}
                        </div>
                        <div style={{ fontSize: "0.8125rem", color: "var(--erp-text-muted)" }}>
                          {subjects[slot.subject_key]?.name ?? slot.subject_key} · Room {slot.room || "—"}
                        </div>
                      </td>
                      <td>{audienceLabel(slot.audience, groupSets)}</td>
                      <td>
                        {openFlags(slot).map((flag) => (
                          <div key={flag.kind} style={{ marginBottom: "0.4rem" }}>
                            <span className="status-badge warning">{FLAG_LABELS[flag.kind]}</span>{" "}
                            <span style={{ fontSize: "0.8125rem" }}>{flag.text}</span>{" "}
                            {(flag.kind === "CONFIRM" || flag.kind === "NO_ROOM" || flag.kind === "CLASH" || flag.kind === "PERIODS_CHECK") && (
                              <button
                                type="button"
                                className="erp-btn erp-btn-secondary"
                                style={smallButton}
                                onClick={() => {
                                  setResolving({ slot, kind: flag.kind });
                                  setResolveNote("");
                                }}
                              >
                                Mark checked
                              </button>
                            )}
                          </div>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p style={{ fontSize: "0.8125rem", color: "var(--erp-text-muted)" }}>
                Code flags clear when the subject's code is confirmed under Subjects. To change a slot itself (for example
                two single periods into one double), import a corrected sheet as a new version.
              </p>
            </div>
          )}
        </div>
      )}

      {pending && (
        <AdminModal
          title={`Check of ${pending.name}`}
          onClose={() => setPending(null)}
          onSubmit={pending.report.errors.length ? undefined : () => void storeDraft()}
          submitLabel="STORE AS DRAFT"
          busy={busy}
        >
          <p style={{ marginTop: 0 }}>
            {pending.report.rows} rows → {pending.report.slots} slots in {pending.report.classes} classes ({pending.report.section_classes}{" "}
            section, {pending.report.group_classes} year-wide group).
          </p>
          {pending.report.errors.length > 0 ? (
            <div className="alert-banner error" role="alert">
              <div>
                <strong>{pending.report.errors.length} error(s): nothing can be stored until the sheet is corrected.</strong>
                <ul style={{ margin: "0.5rem 0 0", paddingLeft: "1.2rem" }}>
                  {pending.report.errors.slice(0, 15).map((e) => (
                    <li key={`${e.row}-${e.message}`}>
                      Row {e.row}: {e.message}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ) : (
            <p>No errors.</p>
          )}
          {Object.keys(pending.report.flag_counts).length > 0 && (
            <p>
              To check after import:{" "}
              {(Object.entries(pending.report.flag_counts) as [FlagKind, number][])
                .map(([kind, count]) => `${count} × ${FLAG_LABELS[kind]}`)
                .join(", ")}
              .
            </p>
          )}
          <p style={{ fontSize: "0.8125rem", color: "var(--erp-text-muted)", marginBottom: 0 }}>
            A draft changes nothing until it is activated from a date.
          </p>
        </AdminModal>
      )}

      {activating && (
        <AdminModal title={`Activate ${activating.source_name}`} onClose={() => setActivating(null)} onSubmit={() => void activate()} submitLabel="ACTIVATE" busy={busy}>
          <div className="form-group" style={fieldGap}>
            <label className="form-label" htmlFor="effective-from">
              In force from
            </label>
            <input id="effective-from" type="date" required className="auth-input" value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} />
          </div>
          <p style={{ fontSize: "0.875rem", marginBottom: 0 }}>
            Lectures before this date keep the timetable that was in force then. It must be later than the date of the version in force now.
          </p>
        </AdminModal>
      )}

      {resolving && (
        <AdminModal
          title="Mark as checked"
          onClose={() => setResolving(null)}
          onSubmit={() => void resolve()}
          submitLabel="SAVE"
          busy={busy}
        >
          <p style={{ marginTop: 0 }}>
            <strong>{resolving.slot.label}</strong>
            <br />
            {FLAG_LABELS[resolving.kind]}: {resolving.slot.flags.find((f) => f.kind === resolving.kind)?.text}
          </p>
          <div className="form-group">
            <label className="form-label" htmlFor="resolve-note">
              What was checked
            </label>
            <input
              id="resolve-note"
              required
              className="auth-input"
              placeholder="e.g. Confirmed with the timetable coordinator: two single periods"
              value={resolveNote}
              onChange={(e) => setResolveNote(e.target.value)}
            />
          </div>
        </AdminModal>
      )}
    </div>
  );
};

const SlotCell: React.FC<{ slot: OrgSlot; name: string; showGroup: boolean }> = ({ slot, name, showGroup }) => {
  const flags = openFlags(slot);
  return (
    <div style={{ marginBottom: "0.5rem", fontSize: "0.8125rem" }}>
      <div style={{ fontWeight: 600 }}>
        {name}
        {slot.periods > 1 ? ` ×${slot.periods}` : ""}
      </div>
      <div style={{ color: "var(--erp-text-muted)" }}>
        {showGroup && slot.audience.kind === "GROUP" ? `${slot.audience.group_code} · ` : ""}
        {slot.room || "No room"}
      </div>
      {flags.length > 0 && (
        <span className="status-badge warning" title={flags.map((f) => `${FLAG_LABELS[f.kind]}: ${f.text}`).join("\n")}>
          {flags.length === 1 ? FLAG_LABELS[flags[0].kind] : `${flags.length} to check`}
        </span>
      )}
    </div>
  );
};
