import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../services";
import { formatDateTime } from "../../utils/dates";
import {
  classPath,
  fileName,
  filterStudents,
  percentLabel,
  type ClassOverview,
  type ClassSessionItem,
  type SessionSheet,
  type StudentSort,
  type TeacherClassItem,
} from "../../utils/classReports.ts";

type Tab = "students" | "date";
type Round = "ENTRY" | "EXIT";

const errorText = (err: unknown) => (err instanceof Error ? err.message : String(err));

// The teacher's classes: each student's attendance in the class, and one
// date's session where ENTRY / EXIT can be corrected (within the edit window).
export const ClassStudents: React.FC = () => {
  const [classes, setClasses] = useState<TeacherClassItem[]>([]);
  const [classId, setClassId] = useState("");
  const [tab, setTab] = useState<Tab>("students");
  const [overview, setOverview] = useState<ClassOverview | null>(null);
  const [sessions, setSessions] = useState<ClassSessionItem[]>([]);
  const [sessionId, setSessionId] = useState("");
  const [sheet, setSheet] = useState<SessionSheet | null>(null);
  const [query, setQuery] = useState("");
  const [belowOnly, setBelowOnly] = useState(false);
  const [sort, setSort] = useState<StudentSort>("roll");
  const [saving, setSaving] = useState<string | null>(null);
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
        // No timetable classes yet: nothing to show here.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const loadOverview = useCallback(async (id: string) => {
    try {
      setOverview(await api.getClassOverview(id));
    } catch (err) {
      setError(errorText(err));
    }
  }, []);

  useEffect(() => {
    if (!classId) return;
    let cancelled = false;
    Promise.all([api.getClassOverview(classId), api.getClassSessions(classId)])
      .then(([data, list]) => {
        if (cancelled) return;
        setOverview(data);
        setSessions(list);
        setSessionId(list[0]?.session_id || "");
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errorText(err));
      });
    return () => {
      cancelled = true;
    };
  }, [classId]);

  useEffect(() => {
    if (!classId || !sessionId || tab !== "date") return;
    let cancelled = false;
    api
      .getClassSessionSheet(classId, sessionId)
      .then((data) => {
        if (!cancelled) setSheet(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errorText(err));
      });
    return () => {
      cancelled = true;
    };
  }, [classId, sessionId, tab]);

  const rows = useMemo(() => filterStudents(overview?.students ?? [], query, belowOnly, sort), [overview, query, belowOnly, sort]);

  if (classes.length === 0) return null;
  const current = classes.find((c) => c.class_id === classId);
  const label = current?.label || current?.subject || "class";
  const isGroup = current?.audience?.kind === "GROUP";

  const mark = async (identity: string, round: Round, status: "PRESENT" | "ABSENT") => {
    if (!sheet) return;
    setSaving(`${identity}:${round}`);
    setError(null);
    try {
      await api.markRound(sheet.session_id, round, identity, status);
      const [fresh] = await Promise.all([api.getClassSessionSheet(classId, sheet.session_id), loadOverview(classId)]);
      setSheet(fresh);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSaving(null);
    }
  };

  const tabButton = (id: Tab, text: string) => (
    <button type="button" className={`erp-btn ${tab === id ? "erp-btn-primary" : "erp-btn-secondary"}`} onClick={() => setTab(id)} aria-pressed={tab === id}>
      {text}
    </button>
  );

  const roundToggle = (row: SessionSheet["students"][number], round: Round) => {
    const value = round === "ENTRY" ? row.entry : row.exit;
    const disabled = !sheet?.teacher_may_edit || !row.on_roster || saving !== null;
    return (
      <select
        className="erp-select-input"
        aria-label={`${round} for ${row.name}`}
        value={value}
        disabled={disabled}
        onChange={(e) => void mark(row.identity, round, e.target.value as "PRESENT" | "ABSENT")}
        style={{ padding: "0.2rem 0.4rem", fontSize: "0.8rem" }}
      >
        <option value="PRESENT">Present</option>
        <option value="ABSENT">Absent</option>
      </select>
    );
  };

  return (
    <div className="erp-card" style={{ padding: "1.25rem 1.5rem", marginTop: "1.5rem", display: "grid", gap: "0.85rem" }}>
      <h2 className="erp-section-title" style={{ margin: 0 }}>Students and attendance</h2>
      {error && (
        <div className="alert-banner error" role="alert">
          <span>{error}</span>
        </div>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" }}>
        <select className="erp-select-input" aria-label="Class" value={classId} onChange={(e) => { setError(null); setClassId(e.target.value); }}>
          {classes.map((c) => (
            <option key={c.class_id} value={c.class_id}>{c.label || c.subject}</option>
          ))}
        </select>
        {tabButton("students", "Students")}
        {tabButton("date", "By date")}
      </div>

      {tab === "students" && overview && (
        <>
          <div style={{ fontSize: "0.85rem", color: "var(--erp-text-muted)" }}>
            {overview.summary.students} students · {overview.summary.lectures_held} lectures held · class average {percentLabel(overview.summary.average)} ·{" "}
            <span className={overview.summary.below_threshold ? "text-shortage" : undefined}>{overview.summary.below_threshold} below {overview.threshold}%</span>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" }}>
            <input className="auth-input" style={{ maxWidth: "16rem" }} placeholder="Search name or roll no" aria-label="Search students" value={query} onChange={(e) => setQuery(e.target.value)} />
            <label style={{ display: "flex", gap: "0.35rem", alignItems: "center", fontSize: "0.85rem" }}>
              <input type="checkbox" checked={belowOnly} onChange={(e) => setBelowOnly(e.target.checked)} />
              Below {overview.threshold}% only
            </label>
            <select className="erp-select-input" aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value as StudentSort)}>
              <option value="roll">Sort by roll no</option>
              <option value="percentage">Sort by % (lowest first)</option>
            </select>
            <button
              type="button"
              className="erp-btn erp-btn-secondary"
              style={{ marginLeft: "auto" }}
              onClick={() => api.downloadFile(classPath(classId, "students.csv"), fileName(label, "class_list")).catch((err: unknown) => setError(errorText(err)))}
            >
              Download CSV
            </button>
          </div>
          <div className="erp-table-container">
            <table className="erp-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Roll No</th>
                  <th>Name</th>
                  <th>Section</th>
                  {isGroup && <th>DE-II</th>}
                  {isGroup && <th>DE-III</th>}
                  {isGroup && <th>DLDA</th>}
                  <th>Present</th>
                  <th>Absent</th>
                  <th>Held</th>
                  <th>%</th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={isGroup ? 11 : 8} style={{ color: "var(--erp-text-muted)" }}>No students to show.</td>
                  </tr>
                ) : (
                  rows.map((r, i) => (
                    <tr key={r.identity}>
                      <td>{i + 1}</td>
                      <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.8rem" }}>{r.roll_number}</td>
                      <td style={{ fontWeight: 600 }}>{r.name}</td>
                      <td>{r.section}</td>
                      {isGroup && <td>{r.de2}</td>}
                      {isGroup && <td>{r.de3}</td>}
                      {isGroup && <td>{r.dlda}</td>}
                      <td>{r.present}</td>
                      <td>{r.absent}</td>
                      <td>{r.held}</td>
                      <td>
                        <span className={r.shortage ? "text-shortage" : undefined} style={{ fontWeight: 700 }}>{percentLabel(r.percentage)}</span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      {tab === "date" && (
        <>
          {sessions.length === 0 ? (
            <span style={{ fontSize: "0.85rem", color: "var(--erp-text-muted)" }}>No sessions for this class yet.</span>
          ) : (
            <select className="erp-select-input" aria-label="Session" value={sessionId} onChange={(e) => setSessionId(e.target.value)}>
              {sessions.map((s) => (
                <option key={s.session_id} value={s.session_id}>{s.date} {s.time} · {s.status}</option>
              ))}
            </select>
          )}
          {sheet && sheet.session_id === sessionId && (
            <>
              <div style={{ fontSize: "0.85rem", color: "var(--erp-text-muted)" }}>
                {sheet.periods === 1 ? "Single period: Present needs both ENTRY and EXIT." : `${sheet.periods} periods: ENTRY gives the first lecture, EXIT the second.`}
                {sheet.teacher_may_edit
                  ? sheet.editable_until
                    ? ` You can correct this class until ${formatDateTime(sheet.editable_until)}.`
                    : ""
                  : " Locked: past the 48 h window — ask an administrator to unlock."}
              </div>
              <div className="erp-table-container">
                <table className="erp-table">
                  <thead>
                    <tr>
                      <th>Roll No</th>
                      <th>Name</th>
                      <th>ENTRY</th>
                      <th>EXIT</th>
                      <th>Lectures</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sheet.students.map((r) => (
                      <tr key={r.identity}>
                        <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.8rem" }}>{r.roll_number}</td>
                        <td style={{ fontWeight: 600 }}>
                          {r.name}
                          {r.by_hand && <span className="status-badge warning" style={{ marginLeft: "0.4rem" }}>corrected by hand</span>}
                          {!r.on_roster && <span style={{ marginLeft: "0.4rem", fontSize: "0.75rem", color: "var(--erp-text-muted)" }}>(joined after this class)</span>}
                        </td>
                        <td>{roundToggle(r, "ENTRY")}</td>
                        <td>{roundToggle(r, "EXIT")}</td>
                        <td>{r.lectures.length ? r.lectures.join(" ") : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
};
