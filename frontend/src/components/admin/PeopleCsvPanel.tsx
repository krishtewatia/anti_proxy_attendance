import React, { useRef, useState } from "react";
import { api } from "../../services";
import { errorText, smallButton, type Banner } from "./adminShared.ts";
import { csvCheckSummary, peopleCsvName, type PeopleCsvCheck, type PeopleKind } from "../../utils/registry.ts";

interface PeopleCsvPanelProps {
  kind: PeopleKind;
  // The page's current filter (students: year, branch, section, status, search).
  query?: Record<string, string>;
  notify: (banner: Banner) => void;
  onImported: () => void;
}

// Keep the students (or teachers) on file: download them as a CSV, and load a
// downloaded file back if accounts were lost. A file is checked first; only
// missing accounts are added and nothing existing is changed.
export const PeopleCsvPanel: React.FC<PeopleCsvPanelProps> = ({ kind, query = {}, notify, onImported }) => {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [check, setCheck] = useState<PeopleCsvCheck | null>(null);
  const [busy, setBusy] = useState(false);

  const download = () => {
    const params = new URLSearchParams(query).toString();
    api
      .downloadFile(`/api/v1/admin/registry/${kind}.csv${params ? `?${params}` : ""}`, peopleCsvName(kind))
      .catch((err: unknown) => notify({ type: "error", text: `Download failed: ${errorText(err)}` }));
  };

  const choose = async (picked: File | undefined) => {
    if (!picked) return;
    setBusy(true);
    try {
      setFile(picked);
      setCheck(await api.checkPeopleCsv(kind, picked));
    } catch (err: unknown) {
      notify({ type: "error", text: `The file could not be read: ${errorText(err)}` });
      setFile(null);
      setCheck(null);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };

  const load = async () => {
    if (!file || !check) return;
    setBusy(true);
    try {
      const done = await api.checkPeopleCsv(kind, file, true);
      notify({ type: "success", text: `${done.created ?? 0} ${kind} added from ${file.name}.` });
      setFile(null);
      setCheck(null);
      onImported();
    } catch (err: unknown) {
      notify({ type: "error", text: `Import failed: ${errorText(err)}` });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button type="button" className="erp-btn erp-btn-secondary" style={smallButton} onClick={download} title="Confidential: holds password hashes; no face data">
        Download CSV
      </button>
      <button type="button" className="erp-btn erp-btn-secondary" style={smallButton} disabled={busy} onClick={() => input.current?.click()}>
        Import CSV
      </button>
      <input ref={input} type="file" accept=".csv,text/csv" hidden aria-label={`Import ${kind} CSV`} onChange={(e) => void choose(e.target.files?.[0])} />
      {check && file && (
        <div className="erp-card" style={{ flexBasis: "100%", padding: "0.85rem 1rem", display: "grid", gap: "0.5rem" }}>
          <strong style={{ fontSize: "0.9rem" }}>{file.name}</strong>
          <span style={{ fontSize: "0.85rem" }}>{csvCheckSummary(check, kind)}</span>
          {check.errors.length > 0 && (
            <ul style={{ margin: 0, paddingLeft: "1.1rem", fontSize: "0.8rem", color: "var(--erp-danger, #b91c1c)", maxHeight: "10rem", overflowY: "auto" }}>
              {check.errors.map((e) => (
                <li key={e.line}>Line {e.line}: {e.errors.join("; ")}</li>
              ))}
            </ul>
          )}
          <span style={{ fontSize: "0.8rem", color: "var(--erp-text-muted)" }}>
            {check.errors.length > 0
              ? "Fix or remove the rows with errors, then choose the file again."
              : "Accounts that already exist are never changed. Face data is not in the file: faces come back from the photo backups or a new photo."}
          </span>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button type="button" className="erp-btn erp-btn-primary" style={smallButton} disabled={busy || check.errors.length > 0 || check.to_create === 0} onClick={() => void load()}>
              Import {check.to_create}
            </button>
            <button type="button" className="erp-btn erp-btn-secondary" style={smallButton} disabled={busy} onClick={() => { setFile(null); setCheck(null); }}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </>
  );
};
