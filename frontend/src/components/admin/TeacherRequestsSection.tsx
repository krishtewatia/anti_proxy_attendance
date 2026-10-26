import React, { useCallback, useEffect, useState } from "react";
import { api } from "../../services";
import { AdminModal } from "./shared";
import { summaryLines, type SetupSubject, type WaitingTeacherRequest } from "../../utils/teacherSetup.ts";

interface TeacherRequestsSectionProps {
  onChanged: (message: string) => void;
}

// Teachers' own choice of subjects and sections, waiting for an administrator:
// approve, adjust and approve, or reject with a reason.
export const TeacherRequestsSection: React.FC<TeacherRequestsSectionProps> = ({ onChanged }) => {
  const [requests, setRequests] = useState<WaitingTeacherRequest[]>([]);
  const [subjects, setSubjects] = useState<SetupSubject[]>([]);
  const [adjusting, setAdjusting] = useState<WaitingTeacherRequest | null>(null);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRequests((await api.getTeacherRequests()).requests);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const decide = async (work: () => Promise<unknown>, message: string) => {
    setBusy(true);
    setError(null);
    try {
      await work();
      setAdjusting(null);
      await load();
      onChanged(message);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const openAdjust = async (request: WaitingTeacherRequest) => {
    try {
      const options = await api.getTeacherSetupOptionsAsAdmin();
      const cohortId = request.classes[0]?.cohort_id;
      setSubjects(options.cohorts.find((c) => c.cohort_id === cohortId)?.subjects ?? options.cohorts[0]?.subjects ?? []);
      setTicked(new Set(request.class_ids));
      setAdjusting(request);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  if (requests.length === 0 && !error) return null;
  const who = (r: WaitingTeacherRequest) => r.name || r.email || "this teacher";

  return (
    <div className="erp-card" style={{ marginBottom: "1.5rem" }}>
      <h2 className="erp-section-title">Teacher class requests ({requests.length})</h2>
      {error && (
        <div className="alert-banner error" role="alert" style={{ marginBottom: "1rem" }}>
          <span>{error}</span>
        </div>
      )}
      <div style={{ display: "grid", gap: "0.75rem" }}>
        {requests.map((request) => (
          <div key={request.request_id} className="erp-card" style={{ padding: "1rem" }}>
            <div style={{ fontWeight: 600 }}>
              {who(request)} {request.change && <span className="status-badge warning">Change</span>}
            </div>
            <div style={{ fontSize: "0.8rem", color: "var(--erp-text-muted)", overflowWrap: "anywhere" }}>{request.email}</div>
            <div style={{ margin: "0.5rem 0", fontSize: "0.875rem" }}>
              {summaryLines(request.classes).map((line) => (
                <div key={line}>{line}</div>
              ))}
            </div>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <button type="button" className="erp-btn erp-btn-primary" disabled={busy} onClick={() => void decide(() => api.approveTeacherRequest(request.request_id), `Classes of ${who(request)} approved.`)}>
                Approve
              </button>
              <button type="button" className="erp-btn erp-btn-secondary" disabled={busy} onClick={() => void openAdjust(request)}>
                Adjust and approve
              </button>
              <button
                type="button"
                className="erp-btn erp-btn-secondary"
                disabled={busy}
                onClick={() => {
                  const reason = window.prompt(`Reason for not approving ${who(request)} (they see it):`);
                  if (reason && reason.trim()) void decide(() => api.rejectTeacherRequest(request.request_id, reason.trim()), `Request of ${who(request)} rejected.`);
                }}
              >
                Reject
              </button>
            </div>
          </div>
        ))}
      </div>

      {adjusting && (
        <AdminModal
          title={`Classes of ${who(adjusting)}`}
          onClose={() => setAdjusting(null)}
          onSubmit={() => void decide(() => api.approveTeacherRequest(adjusting.request_id, [...ticked]), `Classes of ${who(adjusting)} approved (adjusted).`)}
          submitLabel="APPROVE"
          busy={busy}
        >
          <div style={{ display: "grid", gap: "0.6rem", maxHeight: "55vh", overflowY: "auto" }}>
            {subjects.map((subject) => (
              <div key={subject.subject_key}>
                <div style={{ fontWeight: 600, fontSize: "0.85rem" }}>{subject.name}</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", marginTop: "0.3rem" }}>
                  {subject.targets.map((target) => {
                    const on = ticked.has(target.class_id);
                    return (
                      <button
                        key={target.class_id}
                        type="button"
                        aria-pressed={on}
                        className={`erp-btn ${on ? "erp-btn-primary" : "erp-btn-secondary"}`}
                        style={{ padding: "0.25rem 0.6rem", fontSize: "0.78rem" }}
                        onClick={() => {
                          const next = new Set(ticked);
                          if (on) next.delete(target.class_id);
                          else next.add(target.class_id);
                          setTicked(next);
                        }}
                      >
                        {target.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </AdminModal>
      )}
    </div>
  );
};
