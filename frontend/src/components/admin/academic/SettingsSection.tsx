import React, { useCallback, useEffect, useState } from "react";
import { api } from "../../../services";
import type { PilotSettings } from "../../../utils/organisation.ts";
import { errorText, fieldGap } from "../adminShared.ts";
import type { AcademicSectionProps } from "../AcademicSetupTab";

// Pilot settings that change without a code change.
export const SettingsSection: React.FC<AcademicSectionProps> = ({ notify }) => {
  const [form, setForm] = useState<PilotSettings | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setForm(await api.getPilotSettings());
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to load the settings: ${errorText(err)}` });
    }
  }, [notify]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    if (!form) return;
    setBusy(true);
    try {
      setForm(await api.updatePilotSettings(form));
      notify({ type: "success", text: "Settings saved." });
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to save the settings: ${errorText(err)}` });
    } finally {
      setBusy(false);
    }
  };

  if (!form) return <div className="erp-empty-box">Loading...</div>;

  return (
    <form
      className="erp-card"
      style={{ padding: "1.5rem", maxWidth: "40rem" }}
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <div className="form-group" style={fieldGap}>
        <label className="form-label" htmlFor="setting-domain">
          College email domain
        </label>
        <input
          id="setting-domain"
          required
          className="auth-input"
          value={form.college_email_domain}
          onChange={(e) => setForm({ ...form, college_email_domain: e.target.value })}
        />
        <small style={{ color: "var(--erp-text-muted)", fontSize: "0.75rem" }}>
          Only addresses ending in @{form.college_email_domain.replace(/^@/, "")} can register (applies once registration moves to the new model).
        </small>
      </div>
      <div className="erp-form-grid-2" style={fieldGap}>
        <div className="form-group">
          <label className="form-label" htmlFor="setting-window">
            Correction window (hours)
          </label>
          <input
            id="setting-window"
            type="number"
            min={1}
            max={336}
            required
            className="auth-input"
            value={form.edit_window_hours}
            onChange={(e) => setForm({ ...form, edit_window_hours: Number(e.target.value) })}
          />
          <small style={{ color: "var(--erp-text-muted)", fontSize: "0.75rem" }}>
            After this, or once finalized, only an administrator can unlock a session.
          </small>
        </div>
        <div className="form-group">
          <label className="form-label" htmlFor="setting-threshold">
            Shortage below (%)
          </label>
          <input
            id="setting-threshold"
            type="number"
            min={1}
            max={100}
            required
            className="auth-input"
            value={form.shortage_threshold_percent}
            onChange={(e) => setForm({ ...form, shortage_threshold_percent: Number(e.target.value) })}
          />
        </div>
      </div>
      <button type="submit" className="erp-btn erp-btn-primary" disabled={busy}>
        {busy ? "Saving..." : "Save settings"}
      </button>
    </form>
  );
};
