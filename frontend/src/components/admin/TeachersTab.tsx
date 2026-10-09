import React, { useMemo, useState } from "react";
import { api } from "../../services";
import type { TeacherProfileResponse } from "../../types";
import { splitList, teacherEditChanges, type TeacherEditFields } from "../../utils/accounts.ts";
import { AdminModal, ClassPicker, TemporaryPasswordNotice } from "./shared";
import { dangerButton, errorText, fieldGap, smallButton, type AdminTabProps } from "./adminShared.ts";

const EMPTY_TEACHER = {
  name: "",
  email: "",
  password: "",
  teacher_id: "",
  department: "Data Science",
  assigned_classes: [] as string[],
  assigned_subjects: "",
};

interface TeacherEditForm extends Omit<TeacherEditFields, "assigned_subjects"> {
  assigned_subjects: string;
}

function editFields(teacher: TeacherProfileResponse): TeacherEditFields {
  return {
    name: teacher.name,
    email: teacher.email,
    teacher_id: teacher.teacher_id,
    department: teacher.department,
    assigned_classes: teacher.assigned_classes || [],
    assigned_subjects: teacher.assigned_subjects || [],
  };
}

export const TeachersTab: React.FC<AdminTabProps> = ({ teachers, academic, notify, reload }) => {
  const [searchQuery, setSearchQuery] = useState("");
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [newTeacher, setNewTeacher] = useState(EMPTY_TEACHER);
  const [editing, setEditing] = useState<TeacherProfileResponse | null>(null);
  const [editForm, setEditForm] = useState<TeacherEditForm | null>(null);
  const [saving, setSaving] = useState(false);
  const [temporary, setTemporary] = useState<{ label: string; password: string } | null>(null);

  const classCodes = useMemo(() => (academic?.classes || []).map((c) => c.class_code), [academic]);

  const filteredTeachers = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    if (!q) return teachers;
    return teachers.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        t.teacher_id.toLowerCase().includes(q) ||
        t.department.toLowerCase().includes(q) ||
        t.email.toLowerCase().includes(q)
    );
  }, [teachers, searchQuery]);

  const handleCreate = async () => {
    try {
      await api.createAdminTeacher({
        name: newTeacher.name,
        email: newTeacher.email,
        password: newTeacher.password,
        teacher_id: newTeacher.teacher_id,
        department: newTeacher.department,
        assigned_classes: newTeacher.assigned_classes,
        assigned_subjects: splitList(newTeacher.assigned_subjects),
      });
      notify({
        type: "success",
        text: `Teacher ${newTeacher.name} created. They must choose their own password at first sign-in.`,
      });
      setIsAddOpen(false);
      setNewTeacher(EMPTY_TEACHER);
      await reload();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to create teacher: ${errorText(err)}` });
    }
  };

  const handleDelete = async (teacher: TeacherProfileResponse) => {
    if (
      !window.confirm(
        `Delete teacher '${teacher.name}'?\n\nTheir account is removed. The sessions and attendance they recorded are kept.`,
      )
    )
      return;
    try {
      const result = await api.deleteAdminTeacher(teacher.user_id);
      const kept = result.sessions_kept ? ` ${result.sessions_kept} session(s) were kept.` : "";
      notify({ type: "success", text: `Teacher ${teacher.name} deleted.${kept}` });
      await reload();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to delete teacher: ${errorText(err)}` });
    }
  };

  const openEdit = (teacher: TeacherProfileResponse) => {
    const fields = editFields(teacher);
    setEditing(teacher);
    setEditForm({ ...fields, assigned_subjects: fields.assigned_subjects.join(", ") });
  };

  const handleSaveEdit = async () => {
    if (!editing || !editForm) return;
    const changes = teacherEditChanges(editFields(editing), {
      ...editForm,
      assigned_subjects: splitList(editForm.assigned_subjects),
    });
    if (Object.keys(changes).length === 0) {
      setEditing(null);
      return;
    }
    setSaving(true);
    try {
      await api.updateAdminTeacher(editing.user_id, changes);
      notify({ type: "success", text: `Teacher ${editForm.name} updated.` });
      setEditing(null);
      await reload();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to update teacher: ${errorText(err)}` });
    } finally {
      setSaving(false);
    }
  };

  const handleResetPassword = async (teacher: TeacherProfileResponse) => {
    if (
      !window.confirm(
        `Reset the password for '${teacher.name}'?\n\nThey will be signed out everywhere and must choose a new password with the temporary one you give them.`,
      )
    )
      return;
    try {
      const result = await api.resetUserPassword(teacher.user_id);
      setTemporary({ label: teacher.name, password: result.temporary_password });
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to reset the password: ${errorText(err)}` });
    }
  };

  return (
    <div>
      <div className="erp-page-header">
        <h1 className="erp-page-title">Faculty Registry</h1>
        <p className="erp-page-subtitle">Academic teaching staff, departmental appointments, and class assignments.</p>
      </div>

      <div className="erp-table-action-bar">
        <input
          type="text"
          placeholder="Search faculty by name, ID, department..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="erp-search-input"
        />
        <button type="button" className="erp-btn erp-btn-primary" onClick={() => setIsAddOpen(true)}>
          + Add New Teacher
        </button>
      </div>

      <div className="erp-table-container">
        <table className="erp-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Teacher ID</th>
              <th>Department</th>
              <th>Classes</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredTeachers.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ textAlign: "center", padding: "2rem", color: "var(--erp-text-muted)" }}>
                  No teachers found.
                </td>
              </tr>
            ) : (
              filteredTeachers.map((t) => (
                <tr key={t.user_id}>
                  <td style={{ fontWeight: 600 }}>{t.name}</td>
                  <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.8125rem", color: "var(--erp-primary)" }}>
                    {t.teacher_id}
                  </td>
                  <td>{t.department}</td>
                  <td>
                    {(t.assigned_classes || []).length === 0 ? (
                      <span style={{ fontSize: "0.75rem", color: "#b45309" }}>None: cannot open sessions</span>
                    ) : (
                      (t.assigned_classes || []).map((c) => (
                        <span
                          key={c}
                          style={{
                            background: "var(--erp-surface-subtle)",
                            border: "1px solid var(--erp-border)",
                            padding: "0.15rem 0.45rem",
                            borderRadius: "4px",
                            marginRight: "0.3rem",
                            fontSize: "0.75rem",
                            fontWeight: 600,
                          }}
                        >
                          {c}
                        </span>
                      ))
                    )}
                  </td>
                  <td>
                    <span className="status-badge present">Active</span>
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: "0.5rem" }}>
                      <button type="button" className="erp-btn erp-btn-secondary" style={smallButton} onClick={() => openEdit(t)}>
                        Edit
                      </button>
                      <button type="button" className="erp-btn erp-btn-secondary" style={smallButton} onClick={() => handleResetPassword(t)}>
                        Reset Password
                      </button>
                      <button type="button" className="erp-btn erp-btn-secondary" style={dangerButton} onClick={() => handleDelete(t)}>
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {isAddOpen && (
        <AdminModal title="Create Faculty Account" onClose={() => setIsAddOpen(false)} onSubmit={handleCreate} submitLabel="CREATE TEACHER">
          <div className="form-group" style={fieldGap}>
            <label className="form-label">Teacher Name</label>
            <input type="text" required placeholder="Full Name" value={newTeacher.name} onChange={(e) => setNewTeacher({ ...newTeacher, name: e.target.value })} className="auth-input" />
          </div>

          <div className="erp-form-grid-2" style={fieldGap}>
            <div className="form-group">
              <label className="form-label">Teacher ID</label>
              <input type="text" required placeholder="e.g. T002" value={newTeacher.teacher_id} onChange={(e) => setNewTeacher({ ...newTeacher, teacher_id: e.target.value })} className="auth-input" />
            </div>
            <div className="form-group">
              <label className="form-label">Department</label>
              <input type="text" required placeholder="e.g. Data Science" value={newTeacher.department} onChange={(e) => setNewTeacher({ ...newTeacher, department: e.target.value })} className="auth-input" />
            </div>
          </div>

          <div className="form-group" style={fieldGap}>
            <label className="form-label">Classes this teacher may take attendance for</label>
            <ClassPicker available={classCodes} selected={newTeacher.assigned_classes} onChange={(next) => setNewTeacher({ ...newTeacher, assigned_classes: next })} />
          </div>

          <div className="form-group" style={fieldGap}>
            <label className="form-label">Subjects (comma separated)</label>
            <input type="text" placeholder="e.g. Machine Learning, Deep Learning" value={newTeacher.assigned_subjects} onChange={(e) => setNewTeacher({ ...newTeacher, assigned_subjects: e.target.value })} className="auth-input" />
          </div>

          <div className="form-group" style={fieldGap}>
            <label className="form-label">Email Address</label>
            <input type="email" required placeholder="teacher@institution.edu" value={newTeacher.email} onChange={(e) => setNewTeacher({ ...newTeacher, email: e.target.value })} className="auth-input" />
          </div>

          <div className="form-group">
            <label className="form-label">Temporary Password</label>
            <input type="password" required minLength={6} placeholder="First password" value={newTeacher.password} onChange={(e) => setNewTeacher({ ...newTeacher, password: e.target.value })} className="auth-input" autoComplete="new-password" />
            <small style={{ color: "var(--erp-text-muted)", fontSize: "0.75rem" }}>
              The teacher must choose their own password at first sign-in.
            </small>
          </div>
        </AdminModal>
      )}

      {editing && editForm && (
        <AdminModal title="Edit Teacher" onClose={() => setEditing(null)} onSubmit={handleSaveEdit} submitLabel="Save Changes" busy={saving}>
          <div className="form-group" style={fieldGap}>
            <label className="form-label">Teacher Name</label>
            <input type="text" required minLength={2} value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} className="auth-input" />
          </div>

          <div className="erp-form-grid-2" style={fieldGap}>
            <div className="form-group">
              <label className="form-label">Teacher ID</label>
              <input type="text" required minLength={2} value={editForm.teacher_id} onChange={(e) => setEditForm({ ...editForm, teacher_id: e.target.value })} className="auth-input" />
            </div>
            <div className="form-group">
              <label className="form-label">Department</label>
              <input type="text" required minLength={2} value={editForm.department} onChange={(e) => setEditForm({ ...editForm, department: e.target.value })} className="auth-input" />
            </div>
          </div>

          <div className="form-group" style={fieldGap}>
            <label className="form-label">Classes this teacher may take attendance for</label>
            <ClassPicker available={classCodes} selected={editForm.assigned_classes} onChange={(next) => setEditForm({ ...editForm, assigned_classes: next })} />
          </div>

          <div className="form-group" style={fieldGap}>
            <label className="form-label">Subjects (comma separated)</label>
            <input type="text" value={editForm.assigned_subjects} onChange={(e) => setEditForm({ ...editForm, assigned_subjects: e.target.value })} className="auth-input" />
          </div>

          <div className="form-group">
            <label className="form-label">Email Address</label>
            <input type="email" required value={editForm.email} onChange={(e) => setEditForm({ ...editForm, email: e.target.value })} className="auth-input" />
            <small style={{ color: "var(--erp-text-muted)", fontSize: "0.75rem" }}>
              The teacher signs in with this address.
            </small>
          </div>
        </AdminModal>
      )}

      {temporary && (
        <TemporaryPasswordNotice accountLabel={temporary.label} temporaryPassword={temporary.password} onClose={() => setTemporary(null)} />
      )}
    </div>
  );
};
