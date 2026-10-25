import React, { useCallback, useEffect, useState } from "react";
import { api } from "../../../services";
import { choiceLabel } from "../../../utils/enrolment.ts";
import {
  CATEGORY_BADGE,
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  TEMPLATE_EXAMPLE,
  TEMPLATE_HEADER,
  rowsIn,
  type ListSummary,
  type ListUploadReport,
  type MatchCategory,
  type MatchReport,
} from "../../../utils/sectionList.ts";
import { errorText, smallButton } from "../adminShared.ts";
import type { AcademicSectionProps } from "../AcademicSetupTab";

function downloadTemplate() {
  const blob = new Blob([`${TEMPLATE_HEADER}\n${TEMPLATE_EXAMPLE}\n`], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "section_list_template.csv";
  link.click();
  URL.revokeObjectURL(url);
}

// The college's official section list: upload it (checked first), then see
// how it compares with what each student registered and asked for.
export const SectionListsSection: React.FC<AcademicSectionProps> = ({ cohort, notify }) => {
  const [summary, setSummary] = useState<ListSummary | null>(null);
  const [report, setReport] = useState<MatchReport | null>(null);
  const [pending, setPending] = useState<{ name: string; text: string; report: ListUploadReport } | null>(null);
  const [category, setCategory] = useState<MatchCategory | "ALL">("ALL");
  const [section, setSection] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const current = await api.getSectionList(cohort.cohort_id);
      setSummary(current);
      setReport(current.exists ? await api.getSectionListReport(cohort.cohort_id) : null);
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to load the section list: ${errorText(err)}` });
    }
  }, [cohort.cohort_id, notify]);

  useEffect(() => {
    void load();
  }, [load]);

  const chooseFile = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      const text = await file.text();
      setPending({ name: file.name, text, report: await api.uploadSectionList(cohort.cohort_id, text, file.name, true) });
    } catch (err: unknown) {
      notify({ type: "error", text: `Could not check ${file.name}: ${errorText(err)}` });
    } finally {
      setBusy(false);
    }
  };

  const store = async () => {
    if (!pending) return;
    setBusy(true);
    try {
      await api.uploadSectionList(cohort.cohort_id, pending.text, pending.name, false);
      notify({ type: "success", text: `${pending.name} stored: ${pending.report.row_count} students.` });
      setPending(null);
      await load();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to store ${pending.name}: ${errorText(err)}` });
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("Delete the stored section list? Setups and approvals are not affected.")) return;
    setBusy(true);
    try {
      await api.deleteSectionList(cohort.cohort_id);
      notify({ type: "success", text: "The section list was deleted." });
      await load();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to delete: ${errorText(err)}` });
    } finally {
      setBusy(false);
    }
  };

  const shown = rowsIn(report, category, section);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: "1.5rem" }}>
      <div className="erp-card" style={{ padding: "1.25rem 1.5rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
          <div>
            <h2 className="erp-section-title" style={{ margin: 0 }}>Official section list</h2>
            <p style={{ margin: "0.25rem 0 0", fontSize: "0.875rem", color: "var(--erp-text-muted)" }}>
              {summary?.exists
                ? `${summary.source_name}: ${summary.row_count} students (${Object.entries(summary.per_section ?? {}).map(([s, n]) => `${s}: ${n}`).join(", ")}).`
                : "No list stored yet. Columns: roll number, name, email, section, DE-II, DE-III, DLDA."}
            </p>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <button type="button" className="erp-btn erp-btn-secondary" onClick={downloadTemplate}>Download template</button>
            {summary?.exists && (
              <button type="button" className="erp-btn erp-btn-secondary" disabled={busy} onClick={() => void remove()}>Delete list</button>
            )}
            <label className="erp-btn erp-btn-primary" style={{ cursor: busy ? "wait" : "pointer" }}>
              {busy && !pending ? "Checking..." : summary?.exists ? "Replace list (CSV)" : "Upload list (CSV)"}
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
        </div>

        {pending && (
          <div style={{ marginTop: "1rem" }}>
            <p style={{ margin: "0 0 0.5rem" }}>
              <strong>{pending.name}</strong>: {pending.report.row_count} students read
              {Object.keys(pending.report.per_section).length > 0 &&
                ` (${Object.entries(pending.report.per_section).map(([s, n]) => `${s}: ${n}`).join(", ")})`}
              , {pending.report.errors.length} error{pending.report.errors.length === 1 ? "" : "s"}.
            </p>
            {pending.report.errors.length > 0 && (
              <ul style={{ margin: "0 0 0.75rem 1rem", padding: 0, fontSize: "0.85rem" }}>
                {pending.report.errors.map((e) => (
                  <li key={e.row}>Row {e.row}: {e.message}</li>
                ))}
              </ul>
            )}
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button
                type="button"
                className="erp-btn erp-btn-primary"
                disabled={busy || pending.report.errors.length > 0 || pending.report.row_count === 0}
                onClick={() => void store()}
              >
                Store list
              </button>
              <button type="button" className="erp-btn erp-btn-secondary" onClick={() => setPending(null)}>Cancel</button>
            </div>
            {pending.report.errors.length > 0 && (
              <p style={{ fontSize: "0.8rem", color: "var(--erp-text-muted)" }}>Fix the rows above and upload the file again.</p>
            )}
          </div>
        )}
      </div>

      {report && (
        <div className="erp-card" style={{ padding: "1.25rem 1.5rem" }}>
          <h2 className="erp-section-title" style={{ marginTop: 0 }}>Compared with students' setups</h2>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.75rem" }}>
            <button type="button" className={`erp-btn ${category === "ALL" ? "erp-btn-primary" : "erp-btn-secondary"}`} style={smallButton} onClick={() => setCategory("ALL")}>
              All ({report.rows.length})
            </button>
            {CATEGORY_ORDER.filter((c) => report.counts[c] > 0).map((c) => (
              <button key={c} type="button" className={`erp-btn ${category === c ? "erp-btn-primary" : "erp-btn-secondary"}`} style={smallButton} onClick={() => setCategory(c)}>
                {CATEGORY_LABELS[c]} ({report.counts[c]})
              </button>
            ))}
            <select className="erp-select-input" style={{ width: "auto" }} aria-label="Section" value={section} onChange={(e) => setSection(e.target.value)}>
              <option value="">All sections</option>
              {cohort.sections.map((s) => (
                <option key={s} value={s}>Section {s}</option>
              ))}
            </select>
          </div>
          <p style={{ margin: "0 0 0.75rem", fontSize: "0.85rem", color: "var(--erp-text-muted)" }}>
            Requests that match the list can be approved together under Pending Approvals, after checking their photos.
          </p>
          <div className="erp-table-container">
            <table className="erp-table">
              <thead>
                <tr>
                  <th>Roll No</th>
                  <th>Name</th>
                  <th>On the list</th>
                  <th>Student's setup</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {shown.length === 0 && (
                  <tr>
                    <td colSpan={5} style={{ textAlign: "center", color: "var(--erp-text-muted)" }}>Nobody in this view.</td>
                  </tr>
                )}
                {shown.map((row) => (
                  <tr key={`${row.roll_no}-${row.request?.request_id ?? ""}`}>
                    <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.8125rem" }}>{row.roll_no ?? "—"}</td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{row.list?.name ?? row.student?.name ?? "—"}</div>
                      <div style={{ fontSize: "0.75rem", color: "var(--erp-text-muted)", overflowWrap: "anywhere" }}>{row.list?.email ?? row.student?.email}</div>
                    </td>
                    <td style={{ fontSize: "0.8rem" }}>
                      {row.list
                        ? [`Section ${row.list.section}`, ...Object.entries(row.list.choices).map(([k, v]) => choiceLabel(k, v))].join(" · ")
                        : "—"}
                    </td>
                    <td style={{ fontSize: "0.8rem" }}>
                      {row.request
                        ? [`Section ${row.request.section}`, ...Object.entries(row.request.choices).map(([k, v]) => choiceLabel(k, v))].join(" · ")
                        : "—"}
                    </td>
                    <td>
                      <span className={`status-badge ${CATEGORY_BADGE[row.category]}`}>{CATEGORY_LABELS[row.category]}</span>
                      {[...row.differences, ...row.warnings].map((text) => (
                        <div key={text} style={{ fontSize: "0.75rem", color: "var(--erp-text-muted)" }}>{text}</div>
                      ))}
                    </td>
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
