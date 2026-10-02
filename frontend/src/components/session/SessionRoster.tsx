import React, { useEffect, useState } from "react";
import { api } from "../../services";
import "./session-roster.css";

export interface SessionRosterProps {
  sessionId: string;
}

export const SessionRoster: React.FC<SessionRosterProps> = ({ sessionId }) => {
  const [savedIdentities, setSavedIdentities] = useState<string[]>([]);
  const [stagedIdentities, setStagedIdentities] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [newIdentity, setNewIdentity] = useState("");
  const [inputError, setInputError] = useState<string | null>(null);

  // Fetch initial roster from backend
  const fetchRoster = async () => {
    setLoading(true);
    setLoadError(null);

    try {
      const data = await api.getSessionRoster(sessionId);
      const list = Array.isArray(data.identities) ? data.identities : [];
      setSavedIdentities(list);
      setStagedIdentities(list);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);

      // Backend returns 404 if no roster has been enrolled yet.
      // Treat 404 as empty roster rather than a fatal error.
      if (
        msg.includes("404") ||
        msg.toLowerCase().includes("not found")
      ) {
        setSavedIdentities([]);
        setStagedIdentities([]);
      } else {
        setLoadError(msg);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRoster();
  }, [sessionId]);

  // Auto-dismiss success message after 4 seconds
  useEffect(() => {
    if (!successMessage) return;
    const timer = setTimeout(() => {
      setSuccessMessage(null);
    }, 4000);
    return () => clearTimeout(timer);
  }, [successMessage]);

  // Has unsaved edits
  const hasChanges =
    stagedIdentities.length !== savedIdentities.length ||
    stagedIdentities.some((id, index) => id !== savedIdentities[index]);

  // Add identity to local staged list
  const handleAdd = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const trimmed = newIdentity.trim();

    if (!trimmed) {
      setInputError("Please enter a CV identity.");
      return;
    }

    if (stagedIdentities.includes(trimmed)) {
      setInputError(`"${trimmed}" is already in the roster.`);
      return;
    }

    setStagedIdentities((prev) => [...prev, trimmed]);
    setNewIdentity("");
    setInputError(null);
    setSaveError(null);
    setSuccessMessage(null);
  };

  // Remove identity from local staged list
  const handleRemove = (identityToRemove: string) => {
    setStagedIdentities((prev) => prev.filter((id) => id !== identityToRemove));
    setInputError(null);
    setSaveError(null);
    setSuccessMessage(null);
  };

  // Discard local changes and restore last server-loaded roster
  const handleCancel = () => {
    setStagedIdentities([...savedIdentities]);
    setNewIdentity("");
    setInputError(null);
    setSaveError(null);
  };

  // Persist updated roster to backend
  const handleSave = async () => {
    if (saving || !hasChanges) return;

    setSaving(true);
    setSaveError(null);
    setSuccessMessage(null);

    try {
      const result = await api.updateSessionRoster(sessionId, stagedIdentities);
      const updatedList = Array.isArray(result.identities) ? result.identities : [];
      setSavedIdentities(updatedList);
      setStagedIdentities(updatedList);
      setSuccessMessage("Roster updated successfully.");

      // Refresh from backend to confirm persistence
      try {
        const fresh = await api.getSessionRoster(sessionId);
        const freshList = Array.isArray(fresh.identities) ? fresh.identities : [];
        setSavedIdentities(freshList);
        setStagedIdentities(freshList);
      } catch {
        // Fallback to update response if subsequent GET has minor issue
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setSaveError(msg);
      // Staged state is intentionally preserved so teacher does not lose their edits
    } finally {
      setSaving(false);
    }
  };

  // State 1: Loading Skeleton
  if (loading) {
    return (
      <section className="session-roster-card" aria-label="Student Roster">
        <div className="roster-header">
          <div className="roster-skeleton-header" />
        </div>
        <div className="roster-skeleton-box" />
      </section>
    );
  }

  return (
    <section className="session-roster-card" aria-label="Student Roster">
      {/* Header */}
      <div className="roster-header">
        <div className="roster-header-top">
          <h2 className="roster-title">Student Roster</h2>
          <span className="roster-count-badge">
            {stagedIdentities.length}{" "}
            {stagedIdentities.length === 1 ? "enrolled" : "enrolled"}
          </span>
        </div>
        <p className="roster-subtitle">
          Manage enrolled CV identities expected for automated vision verification.
        </p>
      </div>

      {/* Load Error Banner */}
      {loadError && (
        <div className="roster-alert error" role="alert">
          <div className="roster-alert-content">
            <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
            </svg>
            <span>Failed to load roster: {loadError}</span>
          </div>
          <button
            type="button"
            className="roster-alert-btn-retry"
            onClick={fetchRoster}
          >
            Retry
          </button>
        </div>
      )}

      {/* Save Error Banner */}
      {saveError && (
        <div className="roster-alert error" role="alert">
          <div className="roster-alert-content">
            <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
            </svg>
            <span>Failed to save roster: {saveError}</span>
          </div>
          <button
            type="button"
            className="roster-alert-btn-retry"
            onClick={handleSave}
            disabled={saving}
          >
            Retry
          </button>
        </div>
      )}

      {/* Success Banner */}
      {successMessage && (
        <div className="roster-alert success" role="status">
          <div className="roster-alert-content">
            <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span>{successMessage}</span>
          </div>
        </div>
      )}

      {/* Identity List or Empty State */}
      <div className="roster-list-container">
        {stagedIdentities.length === 0 ? (
          <div className="roster-empty-state">
            <div className="roster-empty-icon" aria-hidden="true">
              <svg fill="none" stroke="currentColor" strokeWidth="1.75" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 2.772m0 0a3 3 0 00-4.681 2.72 8.986 8.986 0 003.74.477m.94-3.197a5.971 5.971 0 00-.94 3.197M15 6.75a3 3 0 11-6 0 3 3 0 016 0zm6 3a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0zm-13.5 0a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z"
                />
              </svg>
            </div>
            <p className="roster-empty-text">No students enrolled yet.</p>
            <p className="roster-empty-subtext">
              Add CV identities below to register students for this session.
            </p>
          </div>
        ) : (
          <div className="roster-list" role="list">
            {stagedIdentities.map((identity) => (
              <div key={identity} className="roster-item" role="listitem">
                <div className="roster-item-info">
                  <span className="roster-status-dot" aria-hidden="true" />
                  <span className="roster-identity-code">{identity}</span>
                </div>
                <div className="roster-item-actions">
                  <span className="roster-badge-enrolled">Enrolled</span>
                  <button
                    type="button"
                    className="roster-btn-remove"
                    onClick={() => handleRemove(identity)}
                    disabled={saving}
                    title={`Remove ${identity}`}
                    aria-label={`Remove ${identity}`}
                  >
                    <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Add Student Section */}
      <form className="roster-add-section" onSubmit={handleAdd}>
        <label htmlFor="cv-identity-input" className="roster-field-label">
          CV Identity
        </label>
        <div className="roster-input-row">
          <input
            id="cv-identity-input"
            type="text"
            className="roster-input"
            placeholder="e.g. person_04"
            value={newIdentity}
            onChange={(e) => {
              setNewIdentity(e.target.value);
              if (inputError) setInputError(null);
            }}
            disabled={saving}
          />
          <button
            type="submit"
            className="btn-add-identity"
            disabled={saving || !newIdentity.trim()}
          >
            <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            <span>Add</span>
          </button>
        </div>
        {inputError && (
          <p className="roster-input-error" role="alert">
            {inputError}
          </p>
        )}
      </form>

      {/* Action Bar: Cancel & Save Roster */}
      <div className="roster-action-bar">
        {hasChanges && (
          <button
            type="button"
            className="btn-cancel-roster"
            onClick={handleCancel}
            disabled={saving}
          >
            Cancel
          </button>
        )}
        <button
          type="button"
          className="btn-save-roster"
          onClick={handleSave}
          disabled={saving || !hasChanges}
          title={!hasChanges ? "No changes to save" : "Save Roster Changes"}
        >
          {saving ? "Saving..." : "Save Roster"}
        </button>
      </div>
    </section>
  );
};
