import React, { useState } from "react";
import { api } from "../../../services";
import type { Term } from "../../../utils/organisation.ts";
import { formatDate } from "../../../utils/dates.ts";
import { errorText, fieldGap } from "../adminShared.ts";
import type { AcademicSectionProps } from "../AcademicSetupTab";

// Branch -> year/semester -> sections, and the two kinds of year-wide groups,
// which are shown apart because they are unrelated: a student's elective
// groups and their DLDA workshop group are chosen separately.
export const StructureSection: React.FC<AcademicSectionProps & { terms: Term[] }> = ({
  cohort,
  terms,
  notify,
  refreshStructure,
}) => {
  const term = terms.find((t) => t.term_id === cohort.term_id);
  const [start, setStart] = useState(term?.start_date ?? "");
  const [end, setEnd] = useState(term?.end_date ?? "");
  const [busy, setBusy] = useState(false);

  const saveDates = async () => {
    setBusy(true);
    try {
      await api.setTermDates(cohort.term_id, start || null, end || null);
      notify({ type: "success", text: "Term dates saved." });
      await refreshStructure();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to save the term dates: ${errorText(err)}` });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: "1.5rem" }}>
      <div className="erp-card" style={{ padding: "1.5rem" }}>
        <h2 className="erp-section-title" style={{ marginTop: 0 }}>
          {cohort.branch} → Year {cohort.year}, Semester {cohort.semester}
        </h2>
        <p style={{ color: "var(--erp-text-muted)", marginTop: 0 }}>
          Sections: <strong>{cohort.sections.join(", ")}</strong>
        </p>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void saveDates();
          }}
        >
          <div className="erp-form-grid-2" style={fieldGap}>
            <div className="form-group">
              <label className="form-label" htmlFor="term-start">
                Term starts
              </label>
              <input id="term-start" type="date" className="auth-input" value={start} onChange={(e) => setStart(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="term-end">
                Term ends
              </label>
              <input id="term-end" type="date" className="auth-input" value={end} onChange={(e) => setEnd(e.target.value)} />
            </div>
          </div>
          <p style={{ fontSize: "0.8125rem", color: "var(--erp-text-muted)", marginTop: 0 }}>
            {term?.start_date
              ? `Term ${term.term_id}: ${formatDate(term.start_date)} to ${term.end_date ? formatDate(term.end_date) : "not set"}.`
              : "The start date is needed before \"attendance not entered\" can be counted."}
          </p>
          <button type="submit" className="erp-btn erp-btn-primary" disabled={busy}>
            {busy ? "Saving..." : "Save term dates"}
          </button>
        </form>
      </div>

      <GroupSetTable title="Elective groups" note="A student picks one option and one group in each elective." sets={cohort.elective_sets} />
      <GroupSetTable
        title="Workshop groups"
        note="Separate from the elective groups: a student's DLDA group has nothing to do with their elective groups."
        sets={cohort.workshop_sets}
      />
    </div>
  );
};

const GroupSetTable: React.FC<{ title: string; note: string; sets: AcademicSectionProps["groupSets"] }> = ({ title, note, sets }) => (
  <section aria-label={title}>
    <h2 className="erp-section-title">{title}</h2>
    <p style={{ color: "var(--erp-text-muted)", fontSize: "0.875rem", marginTop: 0 }}>{note}</p>
    <div className="erp-table-container">
      <table className="erp-table">
        <thead>
          <tr>
            <th>Set</th>
            <th>Option</th>
            <th>Groups</th>
            <th>Subjects</th>
          </tr>
        </thead>
        <tbody>
          {sets.flatMap((set) =>
            set.options.map((option, index) => (
              <tr key={`${set.set_code}-${option.option_code}`}>
                <td style={{ fontWeight: 600 }}>{index === 0 ? `${set.set_code} · ${set.name}` : ""}</td>
                <td>{option.name}</td>
                <td>{option.groups.join(", ")}</td>
                <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.8125rem" }}>{option.subject_keys.join(", ")}</td>
              </tr>
            )),
          )}
        </tbody>
      </table>
    </div>
  </section>
);
