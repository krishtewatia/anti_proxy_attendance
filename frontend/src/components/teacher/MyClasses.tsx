import React, { useCallback, useEffect, useState } from "react";
import { api } from "../../services";
import { ClassStudents } from "./ClassStudents";
import {
  choiceFromClassIds,
  choiceProblem,
  classIdsOf,
  summaryLines,
  teacherStatusCard,
  type MyTeacherSetup,
  type SubjectChoice,
  type TeacherSetupOptions,
} from "../../utils/teacherSetup.ts";

// The teacher's own subjects and, for each, the sections or groups they
// teach: year and branch, subjects, sections/groups, then send for approval.
export const MyClasses: React.FC = () => {
  const [options, setOptions] = useState<TeacherSetupOptions | null>(null);
  const [status, setStatus] = useState<MyTeacherSetup | null>(null);
  const [cohortId, setCohortId] = useState("");
  const [choice, setChoice] = useState<SubjectChoice>({});
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const [opts, mine] = await Promise.all([api.getTeacherSetupOptions(), api.getMyTeacherSetup()]);
      setOptions(opts);
      setStatus(mine);
      setCohortId((current) => current || opts.cohorts[0]?.cohort_id || "");
    } catch (err: unknown) {
      setMessage({ type: "error", text: err instanceof Error ? err.message : String(err) });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const cohort = options?.cohorts.find((c) => c.cohort_id === cohortId);
  const pending = status?.latest_request?.status === "PENDING";
  const card = teacherStatusCard(status);

  const startEditing = () => {
    const current = status?.classes.map((c) => c.class_id) ?? [];
    setChoice(cohort ? choiceFromClassIds(cohort.subjects, current) : {});
    setEditing(true);
    setMessage(null);
  };

  const toggleSubject = (key: string, on: boolean) => {
    const next = { ...choice };
    if (on) next[key] = [];
    else delete next[key];
    setChoice(next);
  };

  const toggleTarget = (key: string, classId: string, on: boolean) => {
    const list = choice[key] ?? [];
    setChoice({ ...choice, [key]: on ? [...list, classId] : list.filter((id) => id !== classId) });
  };

  const send = async () => {
    const problem = choiceProblem(choice);
    if (problem) {
      setMessage({ type: "error", text: problem });
      return;
    }
    setBusy(true);
    try {
      await api.submitTeacherSetup(classIdsOf(choice));
      setMessage({ type: "success", text: "Sent for approval." });
      setEditing(false);
      await load();
    } catch (err: unknown) {
      setMessage({ type: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  };

  const withdraw = async () => {
    setBusy(true);
    try {
      await api.withdrawTeacherSetup();
      setMessage({ type: "success", text: "Request withdrawn." });
      await load();
    } catch (err: unknown) {
      setMessage({ type: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ maxWidth: "760px", display: "grid", gap: "1rem", gridTemplateColumns: "minmax(0, 1fr)" }}>
      <div className="erp-page-header" style={{ marginBottom: 0 }}>
        <h1 className="erp-page-title">My Classes</h1>
        <p className="erp-page-subtitle">The subjects you teach and, for each, the sections or groups</p>
      </div>
      {message && (
        <div className={`alert-banner ${message.type}`} role={message.type === "error" ? "alert" : "status"}>
          <span>{message.text}</span>
        </div>
      )}

      <div className={`alert-banner ${card.tone}`} style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "center" }}>
        <div style={{ flex: "1 1 16rem" }}>
          <strong>{card.title}</strong>
          <div style={{ fontSize: "0.875rem" }}>{card.text}</div>
        </div>
        {pending ? (
          <button type="button" className="erp-btn erp-btn-secondary" disabled={busy} onClick={() => void withdraw()}>Withdraw request</button>
        ) : (
          !editing && (
            <button type="button" className="erp-btn erp-btn-primary" onClick={startEditing} disabled={!options}>
              {status?.classes.length ? "Change my classes" : "Choose my subjects"}
            </button>
          )
        )}
      </div>

      {status && status.classes.length > 0 && !editing && (
        <div className="erp-card" style={{ padding: "1rem 1.25rem" }}>
          {summaryLines(status.classes).map((line) => (
            <div key={line} style={{ fontSize: "0.875rem", padding: "0.2rem 0" }}>{line}</div>
          ))}
        </div>
      )}

      {editing && options && (
        <div className="erp-card" style={{ padding: "1.25rem 1.5rem", display: "grid", gap: "1rem" }}>
          <div className="form-group">
            <label className="form-label" htmlFor="teacher-cohort">1. Year and branch</label>
            <select
              id="teacher-cohort"
              className="erp-select-input"
              value={cohortId}
              onChange={(e) => {
                setCohortId(e.target.value);
                setChoice({});
              }}
            >
              {options.cohorts.map((c) => (
                <option key={c.cohort_id} value={c.cohort_id}>{c.name}</option>
              ))}
            </select>
          </div>

          {cohort && (
            <div>
              <div className="form-label">2. Your subjects, and 3. where you teach each one</div>
              <div style={{ display: "grid", gap: "0.6rem" }}>
                {cohort.subjects.map((subject) => {
                  const on = subject.subject_key in choice;
                  return (
                    <div key={subject.subject_key} style={{ borderBottom: "1px solid var(--erp-border)", paddingBottom: "0.5rem" }}>
                      <label style={{ display: "flex", gap: "0.5rem", alignItems: "center", fontWeight: 600, fontSize: "0.9rem" }}>
                        <input type="checkbox" checked={on} onChange={(e) => toggleSubject(subject.subject_key, e.target.checked)} />
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.8rem", color: "var(--erp-text-muted)" }}>{subject.code}</span>
                        {subject.name}
                      </label>
                      {on && (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", margin: "0.4rem 0 0 1.6rem" }}>
                          {subject.targets.map((target) => {
                            const ticked = (choice[subject.subject_key] ?? []).includes(target.class_id);
                            return (
                              <button
                                key={target.class_id}
                                type="button"
                                aria-pressed={ticked}
                                className={`erp-btn ${ticked ? "erp-btn-primary" : "erp-btn-secondary"}`}
                                style={{ padding: "0.3rem 0.7rem", fontSize: "0.8rem" }}
                                onClick={() => toggleTarget(subject.subject_key, target.class_id, !ticked)}
                              >
                                {target.label}
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem" }}>
            <button type="button" className="erp-btn erp-btn-secondary" onClick={() => setEditing(false)} disabled={busy}>Cancel</button>
            <button type="button" className="erp-btn erp-btn-primary" onClick={() => void send()} disabled={busy}>
              {busy ? "Sending..." : `Send for approval (${classIdsOf(choice).length} classes)`}
            </button>
          </div>
        </div>
      )}
      <ClassStudents />
    </div>
  );
};
