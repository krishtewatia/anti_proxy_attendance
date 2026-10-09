import React, { useMemo, useState } from "react";
import { api } from "../../services";
import type { StudentProfileResponse } from "../../types";
import { studentEditChanges, studentIdChangeWarning, type StudentEditFields } from "../../utils/accounts.ts";
import { AuthenticatedImage } from "../common/AuthenticatedImage";
import { AdminModal, TemporaryPasswordNotice } from "./shared";
import { BRANCH_OPTIONS, dangerButton, errorText, fieldGap, smallButton, type AdminTabProps } from "./adminShared.ts";

const EMPTY_STUDENT = {
  name: "",
  email: "",
  password: "",
  student_id: "",
  roll_number: "",
  branch: "Data Science",
  section: "B",
};

function editFields(student: StudentProfileResponse): StudentEditFields {
  return {
    name: student.name,
    email: student.email,
    student_id: student.student_id,
    roll_number: student.roll_number,
    branch: student.branch,
    section: student.section,
  };
}

export const StudentsTab: React.FC<AdminTabProps> = ({ students, academic, notify, reload }) => {
  const [searchQuery, setSearchQuery] = useState("");
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [newStudent, setNewStudent] = useState(EMPTY_STUDENT);
  const [editing, setEditing] = useState<StudentProfileResponse | null>(null);
  const [editForm, setEditForm] = useState<StudentEditFields | null>(null);
  const [saving, setSaving] = useState(false);
  const [temporary, setTemporary] = useState<{ label: string; password: string } | null>(null);

  const branches = useMemo(() => {
    const fromCatalog = (academic?.branches || []).map((b) => b.name);
    return fromCatalog.length > 0 ? fromCatalog : BRANCH_OPTIONS;
  }, [academic]);

  const sectionsFor = (branch: string): string[] => {
    const match = (academic?.branches || []).find((b) => b.name === branch);
    return match && match.sections.length > 0 ? match.sections : ["A", "B", "C"];
  };

  const filteredStudents = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    if (!q) return students;
    return students.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        s.student_id.toLowerCase().includes(q) ||
        s.roll_number.toLowerCase().includes(q) ||
        s.email.toLowerCase().includes(q) ||
        s.class_code.toLowerCase().includes(q)
    );
  }, [students, searchQuery]);

  const handleCreate = async () => {
    try {
      await api.createAdminStudent(newStudent);
      notify({
        type: "success",
        text: `Student ${newStudent.name} created. They must choose their own password at first sign-in.`,
      });
      setIsAddOpen(false);
      setNewStudent(EMPTY_STUDENT);
      await reload();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to create student: ${errorText(err)}` });
    }
  };

  const handleDelete = async (userId: string, name: string) => {
    if (
      !window.confirm(
        `Delete student '${name}'?\n\nThis removes their account, photo, face template and all their attendance records. It cannot be undone.`,
      )
    )
      return;
    try {
      await api.deleteAdminStudent(userId);
      notify({ type: "success", text: `Student ${name} deleted successfully.` });
      await reload();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to delete student: ${errorText(err)}` });
    }
  };

  const openEdit = (student: StudentProfileResponse) => {
    setEditing(student);
    setEditForm(editFields(student));
  };

  const handleSaveEdit = async () => {
    if (!editing || !editForm) return;
    const changes = studentEditChanges(editFields(editing), editForm);
    if (Object.keys(changes).length === 0) {
      setEditing(null);
      return;
    }
    if (
      changes.student_id !== undefined &&
      !window.confirm(studentIdChangeWarning(editing.student_id, changes.student_id))
    ) {
      return;
    }
    setSaving(true);
    try {
      await api.updateAdminStudent(editing.user_id, changes);
      notify({ type: "success", text: `Student ${editForm.name} updated.` });
      setEditing(null);
      await reload();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to update student: ${errorText(err)}` });
    } finally {
      setSaving(false);
    }
  };

  const handleResetPassword = async (student: StudentProfileResponse) => {
    if (
      !window.confirm(
        `Reset the password for '${student.name}'?\n\nThey will be signed out everywhere and must choose a new password with the temporary one you give them.`,
      )
    )
      return;
    try {
      const result = await api.resetUserPassword(student.user_id);
      setTemporary({ label: student.name, password: result.temporary_password });
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to reset the password: ${errorText(err)}` });
    }
  };

  return (
    <div>
      <div className="erp-page-header">
        <h1 className="erp-page-title">Students Registry</h1>
        <p className="erp-page-subtitle">Enrolled students, academic branch, section, and status.</p>
      </div>

      <div className="erp-table-action-bar">
        <input
          type="text"
          placeholder="Search by student name, ID, roll no..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="erp-search-input"
        />
        <button type="button" className="erp-btn erp-btn-primary" onClick={() => setIsAddOpen(true)}>
          + Add New Student
        </button>
      </div>

      <div className="erp-table-container">
        <table className="erp-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Student ID</th>
              <th>ERP/Roll No</th>
              <th>Branch</th>
              <th>Section</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredStudents.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ textAlign: "center", padding: "2rem", color: "var(--erp-text-muted)" }}>
                  No students found.
                </td>
              </tr>
            ) : (
              filteredStudents.map((s) => (
                <tr key={s.user_id}>
                  <td style={{ fontWeight: 600 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                      {/* The photo needs the admin's token, so it cannot be a plain <img src>. */}
                      <AuthenticatedImage
                        src={s.photo_url}
                        alt={s.name}
                        style={{ width: "32px", height: "32px", borderRadius: "50%", objectFit: "cover", border: "1px solid var(--erp-border)" }}
                        fallback={
                          <div style={{ width: "32px", height: "32px", borderRadius: "50%", background: "#e2e8f0", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "0.75rem", fontWeight: 700, color: "#475569" }}>
                            {s.name.charAt(0).toUpperCase()}
                          </div>
                        }
                      />
                      <span>{s.name}</span>
                    </div>
                  </td>
                  <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.8125rem", color: "var(--erp-primary)" }}>
                    {s.student_id}
                  </td>
                  <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.8125rem" }}>{s.roll_number}</td>
                  <td>{s.branch}</td>
                  <td>Section {s.section || "B"}</td>
                  <td>
                    <span className={`status-badge ${s.has_biometric ? "present" : "completed"}`}>
                      {s.has_biometric ? "Enrolled" : "Active"}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: "0.5rem" }}>
                      <button type="button" className="erp-btn erp-btn-secondary" style={smallButton} onClick={() => openEdit(s)}>
                        Edit
                      </button>
                      <button type="button" className="erp-btn erp-btn-secondary" style={smallButton} onClick={() => handleResetPassword(s)}>
                        Reset Password
                      </button>
                      <button type="button" className="erp-btn erp-btn-secondary" style={dangerButton} onClick={() => handleDelete(s.user_id, s.name)}>
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
        <AdminModal title="Create Student" onClose={() => setIsAddOpen(false)} onSubmit={handleCreate} submitLabel="CREATE STUDENT">
          <div className="form-group" style={fieldGap}>
            <label className="form-label">Student Name</label>
            <input type="text" required placeholder="Full Name" value={newStudent.name} onChange={(e) => setNewStudent({ ...newStudent, name: e.target.value })} className="auth-input" />
          </div>

          <div className="erp-form-grid-2" style={fieldGap}>
            <div className="form-group">
              <label className="form-label">Student ID</label>
              <input type="text" required placeholder="e.g. DS202605" value={newStudent.student_id} onChange={(e) => setNewStudent({ ...newStudent, student_id: e.target.value })} className="auth-input" />
            </div>
            <div className="form-group">
              <label className="form-label">ERP / Roll Number</label>
              <input type="text" required placeholder="e.g. 12349" value={newStudent.roll_number} onChange={(e) => setNewStudent({ ...newStudent, roll_number: e.target.value })} className="auth-input" />
            </div>
          </div>

          <div className="erp-form-grid-2" style={fieldGap}>
            <div className="form-group">
              <label className="form-label">Branch</label>
              <select value={newStudent.branch} onChange={(e) => setNewStudent({ ...newStudent, branch: e.target.value })} className="erp-select-input">
                {branches.map((branch) => (
                  <option key={branch} value={branch}>{branch}</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Section</label>
              <select value={newStudent.section} onChange={(e) => setNewStudent({ ...newStudent, section: e.target.value })} className="erp-select-input">
                {sectionsFor(newStudent.branch).map((section) => (
                  <option key={section} value={section}>Section {section}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-group" style={fieldGap}>
            <label className="form-label">Email Address</label>
            <input type="email" required placeholder="student@institution.edu" value={newStudent.email} onChange={(e) => setNewStudent({ ...newStudent, email: e.target.value })} className="auth-input" />
          </div>

          <div className="form-group">
            <label className="form-label">Temporary Password</label>
            <input type="password" required minLength={6} placeholder="First password" value={newStudent.password} onChange={(e) => setNewStudent({ ...newStudent, password: e.target.value })} className="auth-input" autoComplete="new-password" />
            <small style={{ color: "var(--erp-text-muted)", fontSize: "0.75rem" }}>
              The student must choose their own password at first sign-in.
            </small>
          </div>
        </AdminModal>
      )}

      {editing && editForm && (
        <AdminModal title="Edit Student" onClose={() => setEditing(null)} onSubmit={handleSaveEdit} submitLabel="Save Changes" busy={saving}>
          <div className="form-group" style={fieldGap}>
            <label className="form-label">Student Name</label>
            <input type="text" required minLength={2} value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} className="auth-input" />
          </div>

          <div className="erp-form-grid-2" style={fieldGap}>
            <div className="form-group">
              <label className="form-label">Student ID</label>
              <input type="text" required minLength={2} value={editForm.student_id} onChange={(e) => setEditForm({ ...editForm, student_id: e.target.value })} className="auth-input" />
            </div>
            <div className="form-group">
              <label className="form-label">ERP / Roll Number</label>
              <input type="text" required minLength={2} value={editForm.roll_number} onChange={(e) => setEditForm({ ...editForm, roll_number: e.target.value })} className="auth-input" />
            </div>
          </div>

          <div className="erp-form-grid-2" style={fieldGap}>
            <div className="form-group">
              <label className="form-label">Branch</label>
              <select value={editForm.branch} onChange={(e) => setEditForm({ ...editForm, branch: e.target.value })} className="erp-select-input">
                {[...new Set([...branches, editForm.branch])].filter(Boolean).map((branch) => (
                  <option key={branch} value={branch}>{branch}</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Section</label>
              <select value={editForm.section} onChange={(e) => setEditForm({ ...editForm, section: e.target.value })} className="erp-select-input">
                {[...new Set([...sectionsFor(editForm.branch), editForm.section])].filter(Boolean).map((section) => (
                  <option key={section} value={section}>Section {section}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Email Address</label>
            <input type="email" required value={editForm.email} onChange={(e) => setEditForm({ ...editForm, email: e.target.value })} className="auth-input" />
            <small style={{ color: "var(--erp-text-muted)", fontSize: "0.75rem" }}>
              The student signs in with this address.
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
