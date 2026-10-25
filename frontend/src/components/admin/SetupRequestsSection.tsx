import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../services";
import { AuthenticatedImage } from "../common/AuthenticatedImage";
import { choiceLabel, selectBy, type AdminSetupRequest, type SetupRequestList } from "../../utils/enrolment.ts";

interface SetupRequestsSectionProps {
  // Called after a decision, with the message to show (the list may now be empty).
  onChanged: (message: string) => void;
}

const photoStyle: React.CSSProperties = {
  width: "96px",
  height: "96px",
  borderRadius: "8px",
  objectFit: "cover",
  border: "1px solid var(--erp-border)",
};

const placeholder = (label: string) => (
  <div style={{ ...photoStyle, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--erp-surface-subtle)", color: "var(--erp-text-muted)", fontSize: "0.7rem" }}>
    {label}
  </div>
);

// Students' setup requests: branch -> year -> section, filters by group,
// a photo grid per request, and approve or reject one by one or in bulk.
export const SetupRequestsSection: React.FC<SetupRequestsSectionProps> = ({ onChanged }) => {
  const [data, setData] = useState<SetupRequestList | null>(null);
  const [section, setSection] = useState("");
  const [setCode, setSetCode] = useState("");
  const [group, setGroup] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.getSetupRequests());
    } catch (err) {
      setBanner({ type: "error", text: err instanceof Error ? err.message : "Could not load setup requests." });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const requests = useMemo(() => data?.requests ?? [], [data]);
  const visible = useMemo(() => {
    const ids = new Set(selectBy(requests, { section: section || undefined, setCode: setCode || undefined, group: group || undefined }));
    return requests.filter((r) => ids.has(r.request_id));
  }, [requests, section, setCode, group]);

  const setCodes = useMemo(() => [...new Set(requests.flatMap((r) => Object.keys(r.choices)))].sort(), [requests]);
  const groups = useMemo(
    () => (setCode ? [...new Set(requests.map((r) => r.choices[setCode]?.group).filter(Boolean))].sort() : []),
    [requests, setCode],
  );

  if (!data || requests.length === 0) {
    return banner ? (
      <div className={`alert-banner ${banner.type}`} style={{ marginBottom: "1rem" }}><span>{banner.text}</span></div>
    ) : null;
  }

  const toggle = (id: string) => setSelected((list) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]));
  const allVisibleSelected = visible.length > 0 && visible.every((r) => selected.includes(r.request_id));

  const decide = async (action: "approve" | "reject", ids: string[]) => {
    if (ids.length === 0) return;
    let reason: string | undefined;
    if (action === "reject") {
      const answer = window.prompt(`Reason for rejecting ${ids.length} request${ids.length === 1 ? "" : "s"} (the students see it):`);
      if (!answer || !answer.trim()) return;
      reason = answer.trim();
    }
    setBusy(true);
    setBanner(null);
    try {
      const result = await api.decideSetupRequests(action, ids, reason);
      const message = `${result.done.length} setup request${result.done.length === 1 ? "" : "s"} ${action === "approve" ? "approved" : "rejected"}.`;
      setBanner({ type: "success", text: message });
      setSelected([]);
      await load();
      onChanged(message);
    } catch (err) {
      setBanner({ type: "error", text: err instanceof Error ? err.message : "The decision could not be saved." });
    } finally {
      setBusy(false);
    }
  };

  const card = (request: AdminSetupRequest) => (
    <div key={request.request_id} className="erp-card" style={{ padding: "1rem", display: "grid", gap: "0.75rem" }}>
      <label style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start", cursor: "pointer" }}>
        <input type="checkbox" checked={selected.includes(request.request_id)} onChange={() => toggle(request.request_id)} aria-label={`Select ${request.name ?? request.roll_number}`} />
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 600 }}>{request.name || "—"} <span style={{ fontFamily: "var(--font-mono)", fontWeight: 400, fontSize: "0.8rem" }}>{request.roll_number}</span></div>
          <div style={{ fontSize: "0.8rem", color: "var(--erp-text-muted)", overflowWrap: "anywhere" }}>{request.email}</div>
          <div style={{ fontSize: "0.8rem" }}>
            Section {request.section} · {Object.entries(request.choices).map(([code, choice]) => choiceLabel(code, choice)).join(" · ")}
          </div>
          {request.kind === "CHANGE" && <span className="status-badge warning">Change</span>}
        </div>
      </label>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
        {request.current_photo_url && (
          <div style={{ fontSize: "0.7rem", color: "var(--erp-text-muted)" }}>
            <AuthenticatedImage src={request.current_photo_url} alt={`Current photo of ${request.name ?? request.roll_number}`} style={photoStyle} fallback={placeholder("No photo")} />
            <div>Current</div>
          </div>
        )}
        {request.photo_urls.map((url, index) => (
          <AuthenticatedImage key={url} src={url} alt={`Photo ${index + 1} of ${request.name ?? request.roll_number}`} style={photoStyle} fallback={placeholder("Photo")} />
        ))}
        {request.photo_urls.length === 0 && <span style={{ fontSize: "0.8rem", color: "var(--erp-text-muted)" }}>No new photos: the current ones stay.</span>}
      </div>
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        <button type="button" className="erp-btn erp-btn-primary" disabled={busy} onClick={() => void decide("approve", [request.request_id])}>Approve</button>
        <button type="button" className="erp-btn erp-btn-secondary" disabled={busy} onClick={() => void decide("reject", [request.request_id])}>Reject</button>
      </div>
    </div>
  );

  return (
    <div className="erp-card" style={{ marginBottom: "1.5rem" }}>
      <h2 className="erp-section-title">Student setup requests ({requests.length})</h2>
      <p style={{ fontSize: "0.85rem", color: "var(--erp-text-muted)", marginTop: 0 }}>
        Approving puts the student on the attendance list and makes their face recognisable. Check that each photo shows only that student.
      </p>

      {banner && (
        <div className={`alert-banner ${banner.type}`} role={banner.type === "error" ? "alert" : "status"} style={{ marginBottom: "1rem" }}>
          <span>{banner.text}</span>
        </div>
      )}

      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginBottom: "1rem" }}>
        {data.counts.map((branch) =>
          branch.years.map((year) => (
            <div key={year.cohort_id} style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" }}>
              <span style={{ fontSize: "0.85rem", fontWeight: 600 }}>{branch.branch} · Year {year.year}</span>
              <button type="button" className={`erp-btn ${section === "" ? "erp-btn-primary" : "erp-btn-secondary"}`} style={{ padding: "0.3rem 0.7rem" }} onClick={() => setSection("")}>
                All ({year.total})
              </button>
              {Object.entries(year.sections).map(([code, count]) => (
                <button key={code} type="button" className={`erp-btn ${section === code ? "erp-btn-primary" : "erp-btn-secondary"}`} style={{ padding: "0.3rem 0.7rem" }} onClick={() => setSection(code)}>
                  Section {code} ({count})
                </button>
              ))}
            </div>
          )),
        )}
      </div>

      <div className="erp-table-action-bar" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
        <select className="erp-select-input" style={{ width: "auto" }} aria-label="Group set" value={setCode} onChange={(e) => { setSetCode(e.target.value); setGroup(""); }}>
          <option value="">Any group</option>
          {setCodes.map((code) => <option key={code} value={code}>{code}</option>)}
        </select>
        {setCode && (
          <select className="erp-select-input" style={{ width: "auto" }} aria-label="Group" value={group} onChange={(e) => setGroup(e.target.value)}>
            <option value="">Every {setCode} group</option>
            {groups.map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        )}
        <button type="button" className="erp-btn erp-btn-secondary" onClick={() => setSelected(allVisibleSelected ? [] : visible.map((r) => r.request_id))}>
          {allVisibleSelected ? "Clear selection" : `Select all shown (${visible.length})`}
        </button>
        <button type="button" className="erp-btn erp-btn-primary" disabled={busy || selected.length === 0} onClick={() => void decide("approve", selected)}>
          Approve selected ({selected.length})
        </button>
        <button type="button" className="erp-btn erp-btn-secondary" disabled={busy || selected.length === 0} onClick={() => void decide("reject", selected)}>
          Reject selected
        </button>
      </div>

      <div style={{ display: "grid", gap: "0.75rem", gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 320px), 1fr))" }}>
        {visible.map(card)}
      </div>
    </div>
  );
};
