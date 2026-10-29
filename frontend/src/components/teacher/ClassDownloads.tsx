import React, { useEffect, useState } from "react";
import { api } from "../../services";
import { sessionStatusBadgeClass, sessionStatusLabel } from "../../utils/sessions.ts";
import { fileName, registerPath, sessionWhen, type ClassSessionItem, type TeacherClassItem } from "../../utils/classReports.ts";

// Downloads for one of the teacher's classes: one "Download CSV", the register
// for a date range (every student, one column per lecture, totals), and the
// class's sessions with when they were taken. Files are fetched with the
// teacher's token.
export const ClassDownloads: React.FC = () => {
  const [classes, setClasses] = useState<TeacherClassItem[]>([]);
  const [classId, setClassId] = useState("");
  const [sessions, setSessions] = useState<ClassSessionItem[]>([]);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getMyTeachingClasses()
      .then((list) => {
        if (cancelled) return;
        setClasses(list);
        setClassId((current) => current || list[0]?.class_id || "");
      })
      .catch(() => {
        // No timetable classes: nothing to download here.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!classId) return;
    let cancelled = false;
    api
      .getClassSessions(classId)
      .then((list) => {
        if (!cancelled) setSessions(list);
      })
      .catch(() => {
        if (!cancelled) setSessions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [classId]);

  if (classes.length === 0) return null;
  const current = classes.find((c) => c.class_id === classId);
  const label = current?.label || current?.subject || "class";

  const download = () => {
    setError(null);
    api
      .downloadFile(registerPath(classId, from, to), fileName(label, "attendance"))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  };

  return (
    <div className="erp-card" style={{ padding: "1.25rem 1.5rem", marginBottom: "1.5rem", display: "grid", gap: "0.85rem" }}>
      <h2 className="erp-section-title" style={{ margin: 0 }}>Downloads</h2>
      {error && (
        <div className="alert-banner error" role="alert">
          <span>{error}</span>
        </div>
      )}
      <select className="erp-select-input" aria-label="Class" value={classId} onChange={(e) => setClassId(e.target.value)}>
        {classes.map((c) => (
          <option key={c.class_id} value={c.class_id}>{c.label || c.subject}</option>
        ))}
      </select>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "flex-end" }}>
        <label className="form-group" style={{ margin: 0 }}>
          <span className="form-label">From</span>
          <input type="date" className="auth-input" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="form-group" style={{ margin: 0 }}>
          <span className="form-label">To</span>
          <input type="date" className="auth-input" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
        <button type="button" className="erp-btn erp-btn-primary" onClick={download}>
          Download CSV
        </button>
      </div>
      <div style={{ fontSize: "0.8rem", color: "var(--erp-text-muted)" }}>
        Every student of the class with one column per lecture and their totals. Leave the dates empty for the whole term so far.
      </div>
      <div style={{ fontSize: "0.85rem" }}>
        {sessions.length === 0 ? (
          <span style={{ color: "var(--erp-text-muted)" }}>No sessions for this class yet.</span>
        ) : (
          sessions.map((s) => (
            <div key={s.session_id} style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "center", padding: "0.3rem 0", borderBottom: "1px solid var(--erp-border)" }}>
              <span>{sessionWhen(s)}</span>
              <span className={`status-badge ${sessionStatusBadgeClass(s.status)}`}>{sessionStatusLabel(s.status)}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
