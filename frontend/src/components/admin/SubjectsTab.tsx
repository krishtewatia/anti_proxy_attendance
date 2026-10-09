import React, { useState } from "react";
import { api } from "../../services";
import { AdminModal } from "./shared";
import { BRANCH_OPTIONS, errorText, fieldGap, type AdminTabProps } from "./adminShared.ts";

const EMPTY_SUBJECT = { name: "", code: "", branch: "Data Science" };

export const SubjectsTab: React.FC<AdminTabProps> = ({ academic, notify, reload }) => {
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [newSubject, setNewSubject] = useState(EMPTY_SUBJECT);

  const handleCreate = async () => {
    try {
      await api.addAdminSubject(newSubject);
      notify({ type: "success", text: `Subject ${newSubject.name} created!` });
      setIsAddOpen(false);
      setNewSubject(EMPTY_SUBJECT);
      await reload();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to add subject: ${errorText(err)}` });
    }
  };

  return (
    <div>
      <div className="erp-page-header">
        <h1 className="erp-page-title">Curriculum Subjects</h1>
        <p className="erp-page-subtitle">Degree syllabus subjects and academic modules</p>
      </div>

      <div className="erp-table-action-bar">
        <span style={{ fontSize: "0.875rem", color: "var(--erp-text-muted)" }}>Curriculum Catalog</span>
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
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {(academic?.subjects || [
              { name: "Machine Learning", code: "DS301", branch: "Data Science" },
              { name: "Computer Networks", code: "CS302", branch: "Computer Science" },
              { name: "DBMS", code: "CS204", branch: "Computer Science" },
              { name: "DevOps", code: "IT305", branch: "Information Technology" },
            ]).map((sub) => (
              <tr key={sub.name}>
                <td style={{ fontWeight: 600 }}>{sub.name}</td>
                <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.8125rem", color: "var(--erp-primary)" }}>
                  {sub.code}
                </td>
                <td>{sub.branch}</td>
                <td>
                  <span className="status-badge present">Approved</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {isAddOpen && (
        <AdminModal title="Add Curriculum Subject" onClose={() => setIsAddOpen(false)} onSubmit={handleCreate} submitLabel="Add Subject">
          <div className="form-group" style={fieldGap}>
            <label className="form-label">Subject Name</label>
            <input type="text" required placeholder="e.g. Artificial Intelligence" value={newSubject.name} onChange={(e) => setNewSubject({ ...newSubject, name: e.target.value })} className="auth-input" />
          </div>

          <div className="erp-form-grid-2">
            <div className="form-group">
              <label className="form-label">Subject Code</label>
              <input type="text" required placeholder="e.g. AI401" value={newSubject.code} onChange={(e) => setNewSubject({ ...newSubject, code: e.target.value })} className="auth-input" />
            </div>
            <div className="form-group">
              <label className="form-label">Department / Branch</label>
              <select value={newSubject.branch} onChange={(e) => setNewSubject({ ...newSubject, branch: e.target.value })} className="erp-select-input">
                {BRANCH_OPTIONS.map((branch) => (
                  <option key={branch} value={branch}>{branch}</option>
                ))}
              </select>
            </div>
          </div>
        </AdminModal>
      )}
    </div>
  );
};
