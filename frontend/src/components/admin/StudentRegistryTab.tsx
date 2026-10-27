import React, { useCallback, useEffect, useState } from "react";
import { api } from "../../services";
import { AuthenticatedImage } from "../common/AuthenticatedImage";
import { OrgNavigator } from "./OrgNavigator";
import { PeopleCsvPanel } from "./PeopleCsvPanel";
import { AdminModal, TemporaryPasswordNotice } from "./shared";
import { dangerButton, errorText, fieldGap, smallButton, type Banner } from "./adminShared.ts";
import { selectionQuery, type NavSelection, type NavYear } from "../../utils/orgNavigator.ts";
import { STATUS_BADGE, STATUS_LABELS, shortChoice, type RegistryStudent, type StudentRegistry, type StudentStatus } from "../../utils/registry.ts";

interface StudentRegistryTabProps {
  years: NavYear[];
  selection: NavSelection;
  onSelect: (next: NavSelection) => void;
  notify: (banner: Banner) => void;
  onOpenApprovals: () => void;
}

const STATUS_FILTERS: (StudentStatus | "")[] = ["", "APPROVED", "WAITING", "CHANGE_WAITING"];

// Every student of the chosen year, branch and section (or group), approved or
// not, with what the admin can do for each one.
export const StudentRegistryTab: React.FC<StudentRegistryTabProps> = ({ years, selection, onSelect, notify, onOpenApprovals }) => {
  const [data, setData] = useState<StudentRegistry | null>(null);
  const [status, setStatus] = useState<StudentStatus | "">("");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<RegistryStudent | null>(null);
  const [editing, setEditing] = useState<{ name: string; email: string; roll_number: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [temporary, setTemporary] = useState<{ label: string; password: string } | null>(null);
  const noSetupView = status === "NO_SETUP";

  const load = useCallback(async () => {
    try {
      const query = noSetupView ? { status: "NO_SETUP" } : { ...selectionQuery(selection), ...(status ? { status } : {}) };
      setData(await api.getStudentRegistry({ ...query, ...(search.trim() ? { q: search.trim() } : {}) }));
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to load students: ${errorText(err)}` });
    }
  }, [selection, status, search, noSetupView, notify]);

  useEffect(() => {
    void load();
  }, [load]);

  const sets = years.flatMap((y) => y.branches).find((b) => b.cohortId === selection.cohortId)?.groupSets.map((s) => s.set_code) ?? [];
  const label = (s: RegistryStudent) => s.name || s.roll_number || s.email || "this student";

  const resetPassword = async (student: RegistryStudent) => {
    if (!window.confirm(`Reset the password for ${label(student)}? They are signed out everywhere and choose a new one with the temporary password.`)) return;
    try {
      const result = await api.resetUserPassword(student.user_id);
      setTemporary({ label: label(student), password: result.temporary_password });
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to reset the password: ${errorText(err)}` });
    }
  };

  const remove = async (student: RegistryStudent) => {
    if (!window.confirm(`Delete ${label(student)}? This removes the account, photos, face template, setup and attendance. It cannot be undone.`)) return;
    try {
      await api.deleteAdminStudent(student.user_id);
      notify({ type: "success", text: `${label(student)} deleted.` });
      setOpen(null);
      await load();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to delete: ${errorText(err)}` });
    }
  };

  const save = async () => {
    if (!open || !editing) return;
    const changes: Record<string, string> = {};
    if (editing.name.trim() !== (open.name ?? "")) changes.name = editing.name.trim();
    if (editing.email.trim().toLowerCase() !== (open.email ?? "")) changes.email = editing.email.trim();
    if (editing.roll_number.trim() !== (open.roll_number ?? "")) changes.roll_number = editing.roll_number.trim();
    if (Object.keys(changes).length === 0) {
      setEditing(null);
      return;
    }
    setBusy(true);
    try {
      await api.updateAdminStudent(open.user_id, changes);
      notify({ type: "success", text: `${editing.name} saved.` });
      setEditing(null);
      setOpen(null);
      await load();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to save: ${errorText(err)}` });
    } finally {
      setBusy(false);
    }
  };

  const students = data?.students ?? [];

  return (
    <div>
      <div className="erp-page-header">
        <h1 className="erp-page-title">Students</h1>
        <p className="erp-page-subtitle">Every student, by year, branch and section, approved or not.</p>
      </div>

      {!noSetupView && (
        <OrgNavigator years={years} value={selection} onChange={onSelect} counts={data?.counts.cohorts} />
      )}

      <div className="erp-table-action-bar" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
        {STATUS_FILTERS.map((value) => (
          <button key={value || "all"} type="button" className={`erp-btn ${status === value ? "erp-btn-primary" : "erp-btn-secondary"}`} style={smallButton} onClick={() => setStatus(value)}>
            {value ? STATUS_LABELS[value] : "All"}
          </button>
        ))}
        <button type="button" className={`erp-btn ${noSetupView ? "erp-btn-primary" : "erp-btn-secondary"}`} style={smallButton} onClick={() => setStatus(noSetupView ? "" : "NO_SETUP")}>
          No setup yet ({data?.counts.no_setup ?? 0})
        </button>
        <input type="search" className="erp-search-input" placeholder="Search roll no or name" aria-label="Search students" value={search} onChange={(e) => setSearch(e.target.value)} />
        <PeopleCsvPanel
          kind="students"
          query={noSetupView ? { status: "NO_SETUP" } : { ...selectionQuery(selection), ...(status ? { status } : {}), ...(search.trim() ? { q: search.trim() } : {}) }}
          notify={notify}
          onImported={() => void load()}
        />
      </div>
      {noSetupView && (
        <p style={{ fontSize: "0.85rem", color: "var(--erp-text-muted)" }}>
          Signed up but have not chosen a section yet, so they belong to no year or section.
        </p>
      )}

      <div className="erp-table-container">
        <table className="erp-table">
          <thead>
            <tr>
              <th>Roll No</th>
              <th>Name</th>
              <th>Section</th>
              {sets.map((code) => (
                <th key={code}>{code}</th>
              ))}
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {students.length === 0 && (
              <tr>
                <td colSpan={4 + sets.length} style={{ textAlign: "center", padding: "2rem", color: "var(--erp-text-muted)" }}>
                  {data ? "Nobody here." : "Loading..."}
                </td>
              </tr>
            )}
            {students.map((s) => (
              <tr key={s.user_id} style={{ cursor: "pointer" }} onClick={() => setOpen(s)}>
                <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.8125rem", color: "var(--erp-primary)" }}>{s.roll_number ?? "—"}</td>
                <td>
                  <div style={{ fontWeight: 600 }}>{s.name ?? "—"}</div>
                  <div style={{ fontSize: "0.75rem", color: "var(--erp-text-muted)", overflowWrap: "anywhere" }}>{s.email}</div>
                </td>
                <td>{s.section ?? "—"}</td>
                {sets.map((code) => (
                  <td key={code}>{shortChoice(code, s.choices[code])}</td>
                ))}
                <td>
                  <span className={`status-badge ${STATUS_BADGE[s.status]}`}>{STATUS_LABELS[s.status]}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {open && !editing && (
        <AdminModal title={label(open)} onClose={() => setOpen(null)} onSubmit={() => setOpen(null)} submitLabel="CLOSE">
          <div style={{ display: "flex", gap: "1rem", alignItems: "flex-start", flexWrap: "wrap", ...fieldGap }}>
            <AuthenticatedImage
              src={open.photo_url ?? undefined}
              alt={`Photo of ${label(open)}`}
              style={{ width: "96px", height: "96px", borderRadius: "8px", objectFit: "cover", border: "1px solid var(--erp-border)" }}
              fallback={<div style={{ width: "96px", height: "96px", borderRadius: "8px", background: "var(--erp-surface-subtle)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--erp-text-muted)", fontSize: "0.75rem" }}>No photo</div>}
            />
            <div style={{ fontSize: "0.875rem", display: "grid", gap: "0.25rem" }}>
              <div>Roll No <strong style={{ fontFamily: "var(--font-mono)" }}>{open.roll_number ?? "—"}</strong></div>
              <div style={{ overflowWrap: "anywhere" }}>{open.email}</div>
              <div>{open.section ? `Section ${open.section}` : "No section yet"}</div>
              <div>{Object.entries(open.choices).map(([code, c]) => `${code} ${shortChoice(code, c)}`).join(" · ") || "No groups yet"}</div>
              <div><span className={`status-badge ${STATUS_BADGE[open.status]}`}>{STATUS_LABELS[open.status]}</span></div>
            </div>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {open.request_id && (
              <button type="button" className="erp-btn erp-btn-primary" style={smallButton} onClick={() => { setOpen(null); onOpenApprovals(); }}>
                Review the waiting request
              </button>
            )}
            <button type="button" className="erp-btn erp-btn-secondary" style={smallButton} onClick={() => setEditing({ name: open.name ?? "", email: open.email ?? "", roll_number: open.roll_number ?? "" })}>
              Edit
            </button>
            <button type="button" className="erp-btn erp-btn-secondary" style={smallButton} onClick={() => void resetPassword(open)}>
              Reset password
            </button>
            <button type="button" className="erp-btn erp-btn-secondary" style={dangerButton} onClick={() => void remove(open)}>
              Delete
            </button>
          </div>
        </AdminModal>
      )}

      {open && editing && (
        <AdminModal title={`Edit ${label(open)}`} onClose={() => setEditing(null)} onSubmit={() => void save()} submitLabel="SAVE" busy={busy}>
          {(["name", "email", "roll_number"] as const).map((field) => (
            <div key={field} className="form-group" style={fieldGap}>
              <label className="form-label" htmlFor={`registry-${field}`}>{field === "roll_number" ? "Roll No" : field === "email" ? "Email" : "Name"}</label>
              <input
                id={`registry-${field}`}
                required
                className="auth-input"
                inputMode={field === "roll_number" ? "numeric" : undefined}
                value={editing[field]}
                onChange={(e) => setEditing({ ...editing, [field]: e.target.value })}
              />
            </div>
          ))}
          <small style={{ color: "var(--erp-text-muted)", fontSize: "0.75rem" }}>
            Photos, face template and attendance stay linked when the roll number or email is corrected.
          </small>
        </AdminModal>
      )}

      {temporary && (
        <TemporaryPasswordNotice accountLabel={temporary.label} temporaryPassword={temporary.password} onClose={() => setTemporary(null)} />
      )}
    </div>
  );
};
