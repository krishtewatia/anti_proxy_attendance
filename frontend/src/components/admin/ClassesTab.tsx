import React, { useState } from "react";
import { api } from "../../services";
import { AdminModal } from "./shared";
import { BRANCH_OPTIONS, errorText, fieldGap, type AdminTabProps } from "./adminShared.ts";

const EMPTY_CLASS = { class_code: "", branch: "Data Science", section: "A" };

export const ClassesTab: React.FC<AdminTabProps> = ({ students, academic, notify, reload }) => {
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [newClass, setNewClass] = useState(EMPTY_CLASS);

  const handleCreate = async () => {
    try {
      await api.addAdminClass(newClass);
      notify({ type: "success", text: `Class ${newClass.class_code} created!` });
      setIsAddOpen(false);
      setNewClass(EMPTY_CLASS);
      await reload();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to add class: ${errorText(err)}` });
    }
  };

  return (
    <div>
      <div className="erp-page-header">
        <h1 className="erp-page-title">Classes & Sections</h1>
        <p className="erp-page-subtitle">Academic cohorts and class groups</p>
      </div>

      <div className="erp-table-action-bar">
        <span style={{ fontSize: "0.875rem", color: "var(--erp-text-muted)" }}>Active Class Roster Groups</span>
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
              <th>Students</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {(academic?.classes || [
              { class_code: "DS-B", branch: "Data Science", section: "B" },
              { class_code: "DS-C", branch: "Data Science", section: "C" },
              { class_code: "CS-A", branch: "Computer Science", section: "A" },
            ]).map((cls) => (
              <tr key={cls.class_code}>
                <td style={{ fontWeight: 700, color: "var(--erp-navy)" }}>{cls.class_code}</td>
                <td>{cls.branch}</td>
                <td>Section {cls.section}</td>
                <td>{students.filter((s) => s.class_code === cls.class_code).length || 4}</td>
                <td>
                  <span className="status-badge present">Active</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {isAddOpen && (
        <AdminModal title="Add Academic Class" onClose={() => setIsAddOpen(false)} onSubmit={handleCreate} submitLabel="Add Class">
          <div className="form-group" style={fieldGap}>
            <label className="form-label">Class Code</label>
            <input type="text" required placeholder="e.g. DS-D or CS-B" value={newClass.class_code} onChange={(e) => setNewClass({ ...newClass, class_code: e.target.value })} className="auth-input" />
          </div>

          <div className="erp-form-grid-2">
            <div className="form-group">
              <label className="form-label">Branch</label>
              <select value={newClass.branch} onChange={(e) => setNewClass({ ...newClass, branch: e.target.value })} className="erp-select-input">
                {BRANCH_OPTIONS.map((branch) => (
                  <option key={branch} value={branch}>{branch}</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Section</label>
              <select value={newClass.section} onChange={(e) => setNewClass({ ...newClass, section: e.target.value })} className="erp-select-input">
                {["A", "B", "C", "D"].map((section) => (
                  <option key={section} value={section}>{section}</option>
                ))}
              </select>
            </div>
          </div>
        </AdminModal>
      )}
    </div>
  );
};
