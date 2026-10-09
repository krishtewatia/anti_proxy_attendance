import React, { useCallback, useEffect, useState } from "react";
import { api } from "../../services";
import {
  classEditChanges,
  classEditFields,
  deleteBlockedReason,
  usageSummary,
  validateClassCode,
  type AdminClassRow,
  type ClassEditFields,
} from "../../utils/catalog.ts";
import { AdminModal } from "./shared";
import { dangerButton, errorText, fieldGap, smallButton, type AdminTabProps } from "./adminShared.ts";

const EMPTY_CLASS: ClassEditFields = { class_code: "", branch: "", section: "", semester: "" };

export const ClassesTab: React.FC<AdminTabProps> = ({ notify, reload }) => {
  const [rows, setRows] = useState<AdminClassRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [showArchived, setShowArchived] = useState(false);
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [newClass, setNewClass] = useState<ClassEditFields>(EMPTY_CLASS);
  const [editing, setEditing] = useState<AdminClassRow | null>(null);
  const [editForm, setEditForm] = useState<ClassEditFields>(EMPTY_CLASS);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setRows(await api.getAdminClasses());
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to load classes: ${errorText(err)}` });
    } finally {
      setLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    void load();
  }, [load]);

  // The other tabs choose from the active classes, so they are refreshed too.
  const refresh = async () => {
    await load();
    await reload();
  };

  const run = async (action: () => Promise<unknown>, done: string, failed: string): Promise<boolean> => {
    setBusy(true);
    try {
      await action();
      notify({ type: "success", text: done });
      await refresh();
      return true;
    } catch (err: unknown) {
      notify({ type: "error", text: `${failed}: ${errorText(err)}` });
      return false;
    } finally {
      setBusy(false);
    }
  };

  const handleCreate = async () => {
    const problem = validateClassCode(newClass.class_code);
    if (problem) {
      notify({ type: "error", text: problem });
      return;
    }
    const created = await run(
      () =>
        api.addAdminClass({
          class_code: newClass.class_code,
          branch: newClass.branch,
          section: newClass.section,
          semester: newClass.semester.trim() ? Number(newClass.semester) : undefined,
        }),
      `Class ${newClass.class_code.trim().toUpperCase()} created.`,
      "Failed to add class",
    );
    if (created) {
      setIsAddOpen(false);
      setNewClass(EMPTY_CLASS);
    }
  };

  const handleSaveEdit = async () => {
    if (!editing) return;
    const changes = classEditChanges(editing, editForm);
    if (Object.keys(changes).length === 0) {
      setEditing(null);
      return;
    }
    if (changes.class_code !== undefined) {
      const problem = validateClassCode(changes.class_code);
      if (problem) {
        notify({ type: "error", text: problem });
        return;
      }
    }
    if (await run(() => api.updateAdminClass(editing.class_code, changes), `Class ${editing.class_code} updated.`, "Failed to update class")) {
      setEditing(null);
    }
  };

  const handleArchive = async (row: AdminClassRow) => {
    const archive = row.status === "ACTIVE";
    if (
      archive &&
      !window.confirm(
        `Archive class ${row.class_code}?\n\nIt will no longer be offered for registration, new sessions or new assignments. ` +
          `Its students, teachers and past sessions are kept (${usageSummary(row.usage)}). You can restore it later.`,
      )
    )
      return;
    await run(
      () => api.setAdminClassArchived(row.class_code, archive),
      `Class ${row.class_code} ${archive ? "archived" : "restored"}.`,
      `Failed to ${archive ? "archive" : "restore"} class`,
    );
  };

  const handleDelete = async (row: AdminClassRow) => {
    if (!window.confirm(`Delete class ${row.class_code}? Nothing refers to it. This cannot be undone.`)) return;
    await run(() => api.deleteAdminClass(row.class_code), `Class ${row.class_code} deleted.`, "Failed to delete class");
  };

  const visible = rows.filter((row) => showArchived || row.status === "ACTIVE");
  const archivedCount = rows.filter((row) => row.status === "ARCHIVED").length;

  return (
    <div>
      <div className="erp-page-header">
        <h1 className="erp-page-title">Classes & Sections</h1>
        <p className="erp-page-subtitle">Academic cohorts and class groups</p>
      </div>

      <div className="erp-table-action-bar">
        <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.875rem", color: "var(--erp-text-muted)" }}>
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
          Show archived ({archivedCount})
        </label>
        <button type="button" className="erp-btn erp-btn-primary" onClick={() => setIsAddOpen(true)}>
          + Add Class
        </button>
      </div>

      <div className="erp-table-container">
        <table className="erp-table">
          <thead>
            <tr>
              <th>Class Code</th>
              <th>Department / Branch</th>
              <th>Section</th>
              <th>Semester</th>
              <th>In Use</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ textAlign: "center", padding: "2rem", color: "var(--erp-text-muted)" }}>
                  {loading ? "Loading classes..." : "No classes yet."}
                </td>
              </tr>
            ) : (
              visible.map((row) => {
                const blocked = deleteBlockedReason(row);
                return (
                  <tr key={row.class_code} style={row.status === "ARCHIVED" ? { opacity: 0.65 } : undefined}>
                    <td style={{ fontWeight: 700, color: "var(--erp-navy)" }}>{row.class_code}</td>
                    <td>{row.branch}</td>
                    <td>Section {row.section}</td>
                    <td>{row.semester ?? "—"}</td>
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
                            setEditForm(classEditFields(row));
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
        <AdminModal title="Add Academic Class" onClose={() => setIsAddOpen(false)} onSubmit={handleCreate} submitLabel="Add Class" busy={busy}>
          <div className="form-group" style={fieldGap}>
            <label className="form-label">Class Code</label>
            <input type="text" required placeholder="e.g. DS-D or ECE-A" value={newClass.class_code} onChange={(e) => setNewClass({ ...newClass, class_code: e.target.value })} className="auth-input" />
          </div>
          <div className="form-group" style={fieldGap}>
            <label className="form-label">Department / Branch</label>
            <input type="text" required placeholder="e.g. Data Science" value={newClass.branch} onChange={(e) => setNewClass({ ...newClass, branch: e.target.value })} className="auth-input" />
          </div>
          <div className="erp-form-grid-2">
            <div className="form-group">
              <label className="form-label">Section</label>
              <input type="text" required placeholder="e.g. A" maxLength={8} value={newClass.section} onChange={(e) => setNewClass({ ...newClass, section: e.target.value })} className="auth-input" />
            </div>
            <div className="form-group">
              <label className="form-label">Semester (optional)</label>
              <input type="number" min={1} max={12} value={newClass.semester} onChange={(e) => setNewClass({ ...newClass, semester: e.target.value })} className="auth-input" />
            </div>
          </div>
        </AdminModal>
      )}

      {editing && (
        <AdminModal title={`Edit Class ${editing.class_code}`} onClose={() => setEditing(null)} onSubmit={handleSaveEdit} submitLabel="Save Changes" busy={busy}>
          {editing.in_use && (
            <p style={{ fontSize: "0.8125rem", color: "#b45309", marginBottom: "1rem" }}>
              This class is in use ({usageSummary(editing.usage)}), so its code, branch and section cannot change.
              To replace it, archive it and create a new class.
            </p>
          )}
          <div className="form-group" style={fieldGap}>
            <label className="form-label">Class Code</label>
            <input type="text" required disabled={editing.in_use} value={editForm.class_code} onChange={(e) => setEditForm({ ...editForm, class_code: e.target.value })} className="auth-input" />
          </div>
          <div className="form-group" style={fieldGap}>
            <label className="form-label">Department / Branch</label>
            <input type="text" required disabled={editing.in_use} value={editForm.branch} onChange={(e) => setEditForm({ ...editForm, branch: e.target.value })} className="auth-input" />
          </div>
          <div className="erp-form-grid-2">
            <div className="form-group">
              <label className="form-label">Section</label>
              <input type="text" required disabled={editing.in_use} maxLength={8} value={editForm.section} onChange={(e) => setEditForm({ ...editForm, section: e.target.value })} className="auth-input" />
            </div>
            <div className="form-group">
              <label className="form-label">Semester (optional)</label>
              <input type="number" min={1} max={12} value={editForm.semester} onChange={(e) => setEditForm({ ...editForm, semester: e.target.value })} className="auth-input" />
            </div>
          </div>
        </AdminModal>
      )}
    </div>
  );
};
