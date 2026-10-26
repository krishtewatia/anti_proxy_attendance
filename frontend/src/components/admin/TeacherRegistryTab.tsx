import React, { useCallback, useEffect, useState } from "react";
import { api } from "../../services";
import { OrgNavigator } from "./OrgNavigator";
import { AdminModal, TemporaryPasswordNotice } from "./shared";
import { dangerButton, errorText, fieldGap, smallButton, type Banner } from "./adminShared.ts";
import type { NavSelection, NavYear } from "../../utils/orgNavigator.ts";
import { classLabel, teachersFor, type RegistryTeacher } from "../../utils/registry.ts";
import { classGroups } from "../../utils/teaching.ts";
import type { OrgClass } from "../../utils/organisation.ts";

interface TeacherRegistryTabProps {
  years: NavYear[];
  selection: NavSelection;
  onSelect: (next: NavSelection) => void;
  notify: (banner: Banner) => void;
}

const EMPTY_NEW = { name: "", email: "", password: "" };

// Teachers by year and branch, each with the classes they take. Classes are
// assigned to teachers by the administrator (PR 6); until then a teacher is
// listed under "No classes assigned yet".
export const TeacherRegistryTab: React.FC<TeacherRegistryTabProps> = ({ years, selection, onSelect, notify }) => {
  const [teachers, setTeachers] = useState<RegistryTeacher[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState(EMPTY_NEW);
  const [busy, setBusy] = useState(false);
  const [temporary, setTemporary] = useState<{ label: string; password: string } | null>(null);
  // Assigning classes: the year and branch's classes, and the ticked ones.
  const [assigning, setAssigning] = useState<RegistryTeacher | null>(null);
  const [classes, setClasses] = useState<OrgClass[]>([]);
  const [ticked, setTicked] = useState<Set<string>>(new Set());

  const openAssign = async (t: RegistryTeacher) => {
    try {
      setClasses(await api.getOrgClasses(selection.cohortId));
      setTicked(new Set(t.classes.filter((c) => c.cohort_id === selection.cohortId).map((c) => c.class_id)));
      setAssigning(t);
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to load the classes: ${errorText(err)}` });
    }
  };

  const saveAssign = async () => {
    if (!assigning) return;
    setBusy(true);
    try {
      // Classes in other years and branches stay as they are.
      const elsewhere = assigning.classes.filter((c) => c.cohort_id !== selection.cohortId).map((c) => c.class_id);
      await api.setTeacherClasses(assigning.user_id, [...elsewhere, ...ticked]);
      notify({ type: "success", text: `Classes of ${label(assigning)} saved (${ticked.size} here).` });
      setAssigning(null);
      await load();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to save the classes: ${errorText(err)}` });
    } finally {
      setBusy(false);
    }
  };
  const teacherNames = new Map((teachers ?? []).map((t) => [t.user_id, t.name || t.email || t.user_id]));

  const load = useCallback(async () => {
    try {
      setTeachers((await api.getTeacherRegistry()).teachers);
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to load teachers: ${errorText(err)}` });
    }
  }, [notify]);

  useEffect(() => {
    void load();
  }, [load]);

  const { assigned, unassigned } = teachersFor(teachers ?? [], selection.cohortId);
  const inSection = (t: RegistryTeacher) =>
    t.classes.filter(
      (c) =>
        c.cohort_id === selection.cohortId &&
        (!selection.section || (c.audience.kind === "SECTION" && c.audience.section === selection.section)) &&
        (!selection.setCode || (c.audience.kind === "GROUP" && c.audience.set_code === selection.setCode && (!selection.group || c.audience.group_code === selection.group))),
    );
  const shown = assigned.filter((t) => inSection(t).length > 0);
  const label = (t: RegistryTeacher) => t.name || t.email || "this teacher";

  const create = async () => {
    setBusy(true);
    try {
      await api.createAdminTeacher({ name: form.name.trim(), email: form.email.trim(), password: form.password });
      notify({ type: "success", text: `${form.name} added. They choose their own password at first sign-in.` });
      setAdding(false);
      setForm(EMPTY_NEW);
      await load();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to add the teacher: ${errorText(err)}` });
    } finally {
      setBusy(false);
    }
  };

  const resetPassword = async (t: RegistryTeacher) => {
    if (!window.confirm(`Reset the password for ${label(t)}? They are signed out everywhere.`)) return;
    try {
      const result = await api.resetUserPassword(t.user_id);
      setTemporary({ label: label(t), password: result.temporary_password });
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to reset the password: ${errorText(err)}` });
    }
  };

  const remove = async (t: RegistryTeacher) => {
    if (!window.confirm(`Delete ${label(t)}? The sessions and attendance they recorded are kept.`)) return;
    try {
      await api.deleteAdminTeacher(t.user_id);
      notify({ type: "success", text: `${label(t)} deleted.` });
      await load();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to delete: ${errorText(err)}` });
    }
  };

  const table = (rows: RegistryTeacher[], classesOf: (t: RegistryTeacher) => string[], empty: string) => (
    <div className="erp-table-container">
      <table className="erp-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Classes</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={4} style={{ textAlign: "center", padding: "1.5rem", color: "var(--erp-text-muted)" }}>{teachers ? empty : "Loading..."}</td>
            </tr>
          )}
          {rows.map((t) => (
            <tr key={t.user_id}>
              <td>
                <div style={{ fontWeight: 600 }}>{t.name || "—"}</div>
                <div style={{ fontSize: "0.75rem", color: "var(--erp-text-muted)", overflowWrap: "anywhere" }}>{t.email}</div>
              </td>
              <td style={{ fontSize: "0.8rem" }}>{classesOf(t).join(" · ") || "—"}</td>
              <td>
                <span className={`status-badge ${t.approved ? "present" : "warning"}`}>{t.approved ? "Active" : "Waiting"}</span>
              </td>
              <td>
                <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                  <button type="button" className="erp-btn erp-btn-primary" style={smallButton} onClick={() => void openAssign(t)}>Assign classes</button>
                  <button type="button" className="erp-btn erp-btn-secondary" style={smallButton} onClick={() => void resetPassword(t)}>Reset password</button>
                  <button type="button" className="erp-btn erp-btn-secondary" style={dangerButton} onClick={() => void remove(t)}>Delete</button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  return (
    <div>
      <div className="erp-page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "1rem", flexWrap: "wrap" }}>
        <div>
          <h1 className="erp-page-title">Teachers</h1>
          <p className="erp-page-subtitle">By year and branch, with the classes each one takes.</p>
        </div>
        <button type="button" className="erp-btn erp-btn-primary" onClick={() => setAdding(true)}>+ Add teacher</button>
      </div>

      <OrgNavigator years={years} value={selection} onChange={onSelect} />

      <h2 className="erp-section-title">Teaching here ({shown.length})</h2>
      {table(shown, (t) => inSection(t).map(classLabel), "No teacher has classes here yet. Classes are assigned to teachers in the next update.")}

      <h2 className="erp-section-title" style={{ marginTop: "1.5rem" }}>No classes assigned yet ({unassigned.length})</h2>
      {table(unassigned, () => [], (teachers ?? []).length === 0 ? "No teachers yet. Add one, or they sign up with their college email." : "Every teacher has classes.")}

      {adding && (
        <AdminModal title="Add teacher" onClose={() => setAdding(false)} onSubmit={() => void create()} submitLabel="ADD TEACHER" busy={busy}>
          <div className="form-group" style={fieldGap}>
            <label className="form-label" htmlFor="teacher-name">Name</label>
            <input id="teacher-name" required className="auth-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div className="form-group" style={fieldGap}>
            <label className="form-label" htmlFor="teacher-email">College email</label>
            <input id="teacher-email" type="email" required className="auth-input" placeholder="name@college email domain" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="teacher-password">Temporary password</label>
            <input id="teacher-password" type="password" required minLength={6} autoComplete="new-password" className="auth-input" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            <small style={{ color: "var(--erp-text-muted)", fontSize: "0.75rem" }}>They choose their own password at first sign-in.</small>
          </div>
        </AdminModal>
      )}

      {assigning && (
        <AdminModal title={`Classes of ${label(assigning)}`} onClose={() => setAssigning(null)} onSubmit={() => void saveAssign()} submitLabel="SAVE" busy={busy}>
          <p style={{ marginTop: 0, fontSize: "0.85rem", color: "var(--erp-text-muted)" }}>
            Tick the classes this teacher takes. A class can have several teachers; any of them can run its sessions.
          </p>
          <div style={{ display: "grid", gap: "0.85rem", maxHeight: "55vh", overflowY: "auto" }}>
            {classGroups(classes).map((group) => (
              <div key={group.title}>
                <div style={{ fontWeight: 700, fontSize: "0.8rem", marginBottom: "0.3rem" }}>{group.title}</div>
                {group.classes.map((cls) => {
                  const others = cls.teacher_ids.filter((id) => id !== assigning.user_id).map((id) => teacherNames.get(id) ?? id);
                  return (
                    <label key={cls.class_id} style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start", fontSize: "0.85rem", padding: "0.15rem 0" }}>
                      <input
                        type="checkbox"
                        checked={ticked.has(cls.class_id)}
                        onChange={(e) => {
                          const next = new Set(ticked);
                          if (e.target.checked) next.add(cls.class_id);
                          else next.delete(cls.class_id);
                          setTicked(next);
                        }}
                      />
                      <span>
                        {cls.label}
                        {others.length > 0 && <span style={{ color: "var(--erp-text-muted)" }}> · also {others.join(", ")}</span>}
                      </span>
                    </label>
                  );
                })}
              </div>
            ))}
          </div>
        </AdminModal>
      )}

      {temporary && (
        <TemporaryPasswordNotice accountLabel={temporary.label} temporaryPassword={temporary.password} onClose={() => setTemporary(null)} />
      )}
    </div>
  );
};
