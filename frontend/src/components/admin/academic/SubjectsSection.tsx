import React, { useCallback, useEffect, useState } from "react";
import { api } from "../../../services";
import { CODE_STATUS_LABELS, type CodeStatus, type OrgSubject } from "../../../utils/organisation.ts";
import { AdminModal } from "../shared";
import { errorText, fieldGap, smallButton } from "../adminShared.ts";
import type { AcademicSectionProps } from "../AcademicSetupTab";

const STATUS_BADGE: Record<CodeStatus, string> = {
  CONFIRMED: "present",
  INCOMPLETE: "warning",
  MISMATCH: "warning",
};

// The subject catalog. Codes are the ERP's; an incomplete or mismatched code
// is fixed here, and the flag disappears from every timetable slot.
export const SubjectsSection: React.FC<AcademicSectionProps> = ({ notify }) => {
  const [subjects, setSubjects] = useState<OrgSubject[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<OrgSubject | null>(null);
  const [form, setForm] = useState({ code: "", name: "", code_status: "CONFIRMED" as CodeStatus, code_note: "" });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setSubjects(await api.getOrgSubjects());
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to load subjects: ${errorText(err)}` });
    } finally {
      setLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    void load();
  }, [load]);

  const startEdit = (subject: OrgSubject) => {
    setEditing(subject);
    setForm({ code: subject.code, name: subject.name, code_status: subject.code_status, code_note: subject.code_note });
  };

  const save = async () => {
    if (!editing) return;
    setBusy(true);
    try {
      await api.updateOrgSubject(editing.key, form);
      notify({ type: "success", text: `${form.name} saved.` });
      setEditing(null);
      await load();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to save ${editing.name}: ${errorText(err)}` });
    } finally {
      setBusy(false);
    }
  };

  const query = search.trim().toLowerCase();
  const visible = subjects.filter(
    (s) => !query || s.name.toLowerCase().includes(query) || s.code.toLowerCase().includes(query) || s.key.toLowerCase().includes(query),
  );
  const toCheck = subjects.filter((s) => s.code_status !== "CONFIRMED").length;

  return (
    <div>
      <div className="erp-table-action-bar">
        <input
          type="search"
          className="erp-search-input"
          placeholder="Search by name or code"
          aria-label="Search subjects"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span style={{ fontSize: "0.875rem", color: "var(--erp-text-muted)" }}>
          {subjects.length} subjects · {toCheck} code{toCheck === 1 ? "" : "s"} to check
        </span>
      </div>

      <div className="erp-table-container">
        <table className="erp-table">
          <thead>
            <tr>
              <th>ERP code</th>
              <th>Subject</th>
              <th>Type</th>
              <th>Counted</th>
              <th>Code</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 && (
              <tr>
                <td colSpan={6} style={{ textAlign: "center", color: "var(--erp-text-muted)" }}>
                  {loading ? "Loading..." : "No subject matches."}
                </td>
              </tr>
            )}
            {visible.map((subject) => (
              <tr key={subject.key}>
                <td style={{ fontFamily: "var(--font-mono)", fontWeight: 600 }}>{subject.code}</td>
                <td>
                  <div style={{ fontWeight: 600 }}>{subject.name}</div>
                  {subject.code_note && (
                    <div style={{ fontSize: "0.75rem", color: "var(--erp-text-muted)" }}>{subject.code_note}</div>
                  )}
                </td>
                <td>{subject.type.charAt(0) + subject.type.slice(1).toLowerCase()}</td>
                <td>
                  {subject.tracked ? (
                    "Yes"
                  ) : (
                    <span className="status-badge completed" title="Outside this system: never counted, no timetable slots">
                      Not tracked
                    </span>
                  )}
                </td>
                <td>
                  <span className={`status-badge ${STATUS_BADGE[subject.code_status]}`}>
                    {CODE_STATUS_LABELS[subject.code_status]}
                  </span>
                </td>
                <td>
                  <button type="button" className="erp-btn erp-btn-secondary" style={smallButton} onClick={() => startEdit(subject)}>
                    Edit
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editing && (
        <AdminModal title={`Edit ${editing.name}`} onClose={() => setEditing(null)} onSubmit={() => void save()} submitLabel="SAVE" busy={busy}>
          <div className="form-group" style={fieldGap}>
            <label className="form-label" htmlFor="subject-code">
              ERP code
            </label>
            <input id="subject-code" required className="auth-input" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />
          </div>
          <div className="form-group" style={fieldGap}>
            <label className="form-label" htmlFor="subject-name">
              Name
            </label>
            <input id="subject-name" required className="auth-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div className="form-group" style={fieldGap}>
            <label className="form-label" htmlFor="subject-status">
              Code status
            </label>
            <select
              id="subject-status"
              className="erp-select-input"
              value={form.code_status}
              onChange={(e) => setForm({ ...form, code_status: e.target.value as CodeStatus })}
            >
              {(Object.keys(CODE_STATUS_LABELS) as CodeStatus[]).map((status) => (
                <option key={status} value={status}>
                  {CODE_STATUS_LABELS[status]}
                </option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="subject-note">
              Note
            </label>
            <input id="subject-note" className="auth-input" value={form.code_note} onChange={(e) => setForm({ ...form, code_note: e.target.value })} />
            <small style={{ color: "var(--erp-text-muted)", fontSize: "0.75rem" }}>
              Internal key {editing.key} never changes, so classes and timetable slots stay linked.
            </small>
          </div>
        </AdminModal>
      )}
    </div>
  );
};
