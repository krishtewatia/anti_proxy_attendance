import React, { useCallback, useEffect, useState } from "react";
import { api } from "../../services";
import type { UserResponse } from "../../types";
import {
  MIN_ADMIN_PASSWORD_LENGTH,
  adminDeleteBlockedReason,
  type AdminAccount,
} from "../../utils/accounts.ts";
import { AdminModal, TemporaryPasswordNotice } from "./shared";
import { dangerButton, errorText, fieldGap, smallButton, type Banner } from "./adminShared.ts";

const EMPTY_ADMIN = { name: "", email: "", password: "" };

export const AdminsTab: React.FC<{ user: UserResponse; notify: (banner: Banner) => void }> = ({
  user,
  notify,
}) => {
  const [admins, setAdmins] = useState<AdminAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [newAdmin, setNewAdmin] = useState(EMPTY_ADMIN);
  const [temporary, setTemporary] = useState<{ label: string; password: string } | null>(null);

  const load = useCallback(async () => {
    try {
      setAdmins(await api.getAdmins());
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to load administrators: ${errorText(err)}` });
    } finally {
      setLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleCreate = async () => {
    try {
      await api.createAdmin(newAdmin);
      notify({
        type: "success",
        text: `Administrator ${newAdmin.name} created. They must choose their own password at first sign-in.`,
      });
      setIsAddOpen(false);
      setNewAdmin(EMPTY_ADMIN);
      await load();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to create administrator: ${errorText(err)}` });
    }
  };

  const handleDelete = async (admin: AdminAccount) => {
    if (!window.confirm(`Delete the administrator account ${admin.email}?`)) return;
    try {
      await api.deleteAdmin(admin.user_id);
      notify({ type: "success", text: `Administrator ${admin.email} deleted.` });
      await load();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to delete administrator: ${errorText(err)}` });
    }
  };

  const handleResetPassword = async (admin: AdminAccount) => {
    if (
      !window.confirm(
        `Reset the password for ${admin.email}?\n\nThey will be signed out everywhere and must choose a new password with the temporary one you give them.`,
      )
    )
      return;
    try {
      const result = await api.resetUserPassword(admin.user_id);
      setTemporary({ label: admin.email, password: result.temporary_password });
      await load();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to reset the password: ${errorText(err)}` });
    }
  };

  return (
    <div>
      <div className="erp-page-header">
        <h1 className="erp-page-title">Administrators</h1>
        <p className="erp-page-subtitle">Accounts that can approve registrations and manage everything here.</p>
      </div>

      <div className="erp-table-action-bar">
        <span style={{ fontSize: "0.875rem", color: "var(--erp-text-muted)" }}>
          {loading ? "Loading..." : `${admins.length} administrator account(s)`}
        </span>
        <button type="button" className="erp-btn erp-btn-primary" onClick={() => setIsAddOpen(true)}>
          + Add Administrator
        </button>
      </div>

      <div className="erp-table-container">
        <table className="erp-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {admins.map((admin) => {
              const isSelf = admin.user_id === user.user_id;
              const blocked = adminDeleteBlockedReason(admin, user.user_id, admins.length);
              return (
                <tr key={admin.user_id}>
                  <td style={{ fontWeight: 600 }}>
                    {admin.name || "—"}
                    {isSelf && <span style={{ color: "var(--erp-text-muted)", fontWeight: 400 }}> (you)</span>}
                  </td>
                  <td>{admin.email}</td>
                  <td>
                    <span className={`status-badge ${admin.must_change_password ? "completed" : "present"}`}>
                      {admin.must_change_password ? "Must change password" : "Active"}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: "0.5rem" }}>
                      <button
                        type="button"
                        className="erp-btn erp-btn-secondary"
                        style={smallButton}
                        disabled={isSelf}
                        title={isSelf ? "Use Change Password for your own account." : undefined}
                        onClick={() => handleResetPassword(admin)}
                      >
                        Reset Password
                      </button>
                      <button
                        type="button"
                        className="erp-btn erp-btn-secondary"
                        style={dangerButton}
                        disabled={blocked !== null}
                        title={blocked ?? undefined}
                        onClick={() => handleDelete(admin)}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {isAddOpen && (
        <AdminModal title="Add Administrator" onClose={() => setIsAddOpen(false)} onSubmit={handleCreate} submitLabel="Create Administrator">
          <div className="form-group" style={fieldGap}>
            <label className="form-label">Name</label>
            <input type="text" required minLength={2} value={newAdmin.name} onChange={(e) => setNewAdmin({ ...newAdmin, name: e.target.value })} className="auth-input" />
          </div>
          <div className="form-group" style={fieldGap}>
            <label className="form-label">Email Address</label>
            <input type="email" required value={newAdmin.email} onChange={(e) => setNewAdmin({ ...newAdmin, email: e.target.value })} className="auth-input" />
          </div>
          <div className="form-group">
            <label className="form-label">Temporary Password</label>
            <input type="password" required minLength={MIN_ADMIN_PASSWORD_LENGTH} value={newAdmin.password} onChange={(e) => setNewAdmin({ ...newAdmin, password: e.target.value })} className="auth-input" autoComplete="new-password" />
            <small style={{ color: "var(--erp-text-muted)", fontSize: "0.75rem" }}>
              At least {MIN_ADMIN_PASSWORD_LENGTH} characters. They must choose their own at first sign-in.
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
