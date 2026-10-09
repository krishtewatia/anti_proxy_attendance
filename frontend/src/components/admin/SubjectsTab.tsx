import React, { useCallback, useEffect, useState } from "react";
import { api } from "../../services";
import {
  deleteBlockedReason,
  subjectEditChanges,
  usageSummary,
  type AdminSubjectRow,
  type SubjectEditFields,
} from "../../utils/catalog.ts";
import { AdminModal } from "./shared";
import { dangerButton, errorText, fieldGap, smallButton, type AdminTabProps } from "./adminShared.ts";

const EMPTY_SUBJECT: SubjectEditFields = { name: "", code: "", branch: "" };

export const SubjectsTab: React.FC<AdminTabProps> = ({ notify, reload }) => {
  const [rows, setRows] = useState<AdminSubjectRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [showArchived, setShowArchived] = useState(false);
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [newSubject, setNewSubject] = useState<SubjectEditFields>(EMPTY_SUBJECT);
  const [editing, setEditing] = useState<AdminSubjectRow | null>(null);
  const [editForm, setEditForm] = useState<SubjectEditFields>(EMPTY_SUBJECT);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setRows(await api.getAdminSubjects());
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to load subjects: ${errorText(err)}` });
    } finally {
      setLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (action: () => Promise<unknown>, done: string, failed: string): Promise<boolean> => {
    setBusy(true);
    try {
      await action();
      notify({ type: "success", text: done });
      await load();
      await reload();
      return true;
    } catch (err: unknown) {
      notify({ type: "error", text: `${failed}: ${errorText(err)}` });
      return false;
    } finally {
      setBusy(false);
    }
  };

  const handleCreate = async () => {
    const created = await run(
      () =>
        api.addAdminSubject({
          name: newSubject.name,
          code: newSubject.code.trim() || undefined,
          branch: newSubject.branch.trim() || undefined,
        }),
      `Subject ${newSubject.name.trim()} created.`,
      "Failed to add subject",
    );
    if (created) {
      setIsAddOpen(false);
      setNewSubject(EMPTY_SUBJECT);
    }
  };

  const handleSaveEdit = async () => {
    if (!editing) return;
    const changes = subjectEditChanges(editing, editForm);
    if (Object.keys(changes).length === 0) {
      setEditing(null);
      return;
    }
    if (await run(() => api.updateAdminSubject(editing.subject_id, changes), `Subject ${editing.name} updated.`, "Failed to update subject")) {
      setEditing(null);
    }
  };

  const handleArchive = async (row: AdminSubjectRow) => {
    const archive = row.status === "ACTIVE";
    if (
      archive &&
      !window.confirm(
        `Archive subject ${row.name}?\n\nIt will no longer be offered for new sessions or new assignments. ` +
          `Teachers who have it and past sessions are kept (${usageSummary(row.usage)}). You can restore it later.`,
      )
    )
      return;
    await run(
      () => api.setAdminSubjectArchived(row.subject_id, archive),
      `Subject ${row.name} ${archive ? "archived" : "restored"}.`,
      `Failed to ${archive ? "archive" : "restore"} subject`,
    );
  };

  const handleDelete = async (row: AdminSubjectRow) => {
    if (!window.confirm(`Delete subject ${row.name}? Nothing refers to it. This cannot be undone.`)) return;
    await run(() => api.deleteAdminSubject(row.subject_id), `Subject ${row.name} deleted.`, "Failed to delete subject");
  };

  const visible = rows.filter((row) => showArchived || row.status === "ACTIVE");
  const archivedCount = rows.filter((row) => row.status === "ARCHIVED").length;

  return (
    <div>
      <div className="erp-page-header">
        <h1 className="erp-page-title">Curriculum Subjects</h1>
        <p className="erp-page-subtitle">Degree syllabus subjects and academic modules</p>
      </div>

      <div className="erp-table-action-bar">
        <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.875rem", color: "var(--erp-text-muted)" }}>
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
          Show archived ({archivedCount})
        </label>
        <button type="button" className="erp-btn erp-btn-primary" onClick={() => setIsAddOpen(true)}>
          + Add Subject
        </button>
      </div>

      <div className="erp-table-container">
        <table className="erp-table">
          <thead>
            <tr>
              <th>Subject Name</th>
              <th>Subject Code</th>
              <th>Department</th>
              <th>In Use</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ textAlign: "center", padding: "2rem", color: "var(--erp-text-muted)" }}>
                  {loading ? "Loading subjects..." : "No subjects yet."}
                </td>
              </tr>
            ) : (
              visible.map((row) => {
                const blocked = deleteBlockedReason(row);
                return (
                  <tr key={row.subject_id} style={row.status === "ARCHIVED" ? { opacity: 0.65 } : undefined}>
                    <td style={{ fontWeight: 600 }}>{row.name}</td>
                    <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.8125rem", color: "var(--erp-primary)" }}>
                      {row.code || "—"}
                    </td>
                    <td>{row.branch || "—"}</td>
                    <td style={{ fontSize: "0.8125rem" }}>{usageSummary(row.usage)}</td>
                    <td>
                      <span className={`status-badge ${row.status === "ACTIVE" ? "present" : "completed"}`}>
                        {row.status === "ACTIVE" ? "Active" : "Archived"}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: "0.5rem" }}>
                        <button
                          type="button"
                          className="erp-btn erp-btn-secondary"
                          style={smallButton}
                          disabled={busy}
                          onClick={() => {
                            setEditing(row);
                            setEditForm({ name: row.name, code: row.code ?? "", branch: row.branch ?? "" });
                          }}
                        >
                          Edit
                        </button>
                        <button type="button" className="erp-btn erp-btn-secondary" style={smallButton} disabled={busy} onClick={() => handleArchive(row)}>
                          {row.status === "ACTIVE" ? "Archive" : "Restore"}
                        </button>
                        <button
                          type="button"
                          className="erp-btn erp-btn-secondary"
                          style={dangerButton}
                          disabled={busy || blocked !== null}
                          title={blocked ?? undefined}
                          onClick={() => handleDelete(row)}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {isAddOpen && (
        <AdminModal title="Add Curriculum Subject" onClose={() => setIsAddOpen(false)} onSubmit={handleCreate} submitLabel="Add Subject" busy={busy}>
          <div className="form-group" style={fieldGap}>
            <label className="form-label">Subject Name</label>
            <input type="text" required minLength={2} placeholder="e.g. Artificial Intelligence" value={newSubject.name} onChange={(e) => setNewSubject({ ...newSubject, name: e.target.value })} className="auth-input" />
          </div>
          <div className="erp-form-grid-2">
            <div className="form-group">
              <label className="form-label">Subject Code (optional)</label>
              <input type="text" placeholder="e.g. AI401" value={newSubject.code} onChange={(e) => setNewSubject({ ...newSubject, code: e.target.value })} className="auth-input" />
            </div>
            <div className="form-group">
              <label className="form-label">Department / Branch (optional)</label>
              <input type="text" placeholder="e.g. Data Science" value={newSubject.branch} onChange={(e) => setNewSubject({ ...newSubject, branch: e.target.value })} className="auth-input" />
            </div>
          </div>
        </AdminModal>
      )}

      {editing && (
        <AdminModal title="Edit Subject" onClose={() => setEditing(null)} onSubmit={handleSaveEdit} submitLabel="Save Changes" busy={busy}>
          {editing.in_use && (
            <p style={{ fontSize: "0.8125rem", color: "#b45309", marginBottom: "1rem" }}>
              This subject is in use ({usageSummary(editing.usage)}), so its name cannot change. To replace it,
              archive it and create a new subject.
            </p>
          )}
          <div className="form-group" style={fieldGap}>
            <label className="form-label">Subject Name</label>
            <input type="text" required minLength={2} disabled={editing.in_use} value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} className="auth-input" />
          </div>
          <div className="erp-form-grid-2">
            <div className="form-group">
              <label className="form-label">Subject Code (optional)</label>
              <input type="text" value={editForm.code} onChange={(e) => setEditForm({ ...editForm, code: e.target.value })} className="auth-input" />
            </div>
            <div className="form-group">
              <label className="form-label">Department / Branch (optional)</label>
              <input type="text" value={editForm.branch} onChange={(e) => setEditForm({ ...editForm, branch: e.target.value })} className="auth-input" />
            </div>
          </div>
        </AdminModal>
      )}
    </div>
  );
};
