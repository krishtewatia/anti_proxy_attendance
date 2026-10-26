import React, { useEffect, useState } from "react";
import { api } from "../../services";
import { percentLabel, type LectureItem, type SubjectReport } from "../../utils/classReports.ts";

// Subject-wise attendance in lectures: present, absent,
// not entered (not counted), total, percentage; tap a subject for its lectures.
export const SubjectAttendance: React.FC = () => {
  const [report, setReport] = useState<SubjectReport | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [lectures, setLectures] = useState<LectureItem[]>([]);

  useEffect(() => {
    let cancelled = false;
    api
      .getMySubjects()
      .then((data) => {
        if (!cancelled) setReport(data);
      })
      .catch(() => {
        // No approved setup yet: nothing to show here.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const toggle = async (subjectKey: string) => {
    if (open === subjectKey) {
      setOpen(null);
      return;
    }
    setOpen(subjectKey);
    setLectures([]);
    try {
      setLectures((await api.getMySubjectLectures(subjectKey)).lectures);
    } catch {
      setLectures([]);
    }
  };

  if (!report) return null;
  const pctCell = (value: number | null, shortage: boolean) => (
    <span className={shortage ? "text-shortage" : undefined} style={{ fontWeight: 700 }}>{percentLabel(value)}</span>
  );

  return (
    <div className="erp-card" style={{ marginBottom: "1.5rem" }}>
      <h2 className="erp-section-title">Attendance by subject</h2>
      <p style={{ margin: "0 0 0.75rem", fontSize: "0.8rem", color: "var(--erp-text-muted)" }}>
        Counted in lectures (a double period is two). "Not entered" are classes with no attendance taken yet; they are not in the percentage. Below {report.threshold}% is a shortage.
      </p>
      <div className="erp-table-container">
        <table className="erp-table">
          <thead>
            <tr>
              <th>Code</th>
              <th>Subject</th>
              <th>Teacher</th>
              <th>Present</th>
              <th>Absent</th>
              <th>Not entered</th>
              <th>Total</th>
              <th>%</th>
            </tr>
          </thead>
          <tbody>
            {report.subjects.map((row) => (
              <React.Fragment key={row.subject_key}>
                <tr style={{ cursor: "pointer" }} onClick={() => void toggle(row.subject_key)} aria-expanded={open === row.subject_key}>
                  <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.8rem" }}>{row.code}</td>
                  <td style={{ fontWeight: 600 }}>{row.name}</td>
                  <td>{row.teacher || "—"}</td>
                  <td>{row.present}</td>
                  <td>{row.absent}</td>
                  <td>{row.not_entered}</td>
                  <td>{row.held}</td>
                  <td>{pctCell(row.percentage, row.shortage)}</td>
                </tr>
                {open === row.subject_key && (
                  <tr>
                    <td colSpan={8} style={{ background: "var(--erp-surface-hover)" }}>
                      {lectures.length === 0 ? (
                        <span style={{ fontSize: "0.8rem", color: "var(--erp-text-muted)" }}>No lectures taken yet.</span>
                      ) : (
                        <div style={{ display: "grid", gap: "0.25rem", fontSize: "0.8rem" }}>
                          {lectures.map((lec) => (
                            <div key={`${lec.date}-${lec.time}-${lec.lecture}`} style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
                              <span style={{ minWidth: "6.5rem" }}>{lec.date} {lec.time}</span>
                              <span>Lecture {lec.lecture}</span>
                              <span className={`status-badge ${lec.status === "P" ? "present" : "absent"}`}>{lec.status === "P" ? "Present" : "Absent"}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
            <tr style={{ fontWeight: 700 }}>
              <td colSpan={3}>Overall</td>
              <td>{report.overall.present}</td>
              <td>{report.overall.absent}</td>
              <td>{report.overall.not_entered}</td>
              <td>{report.overall.held}</td>
              <td>{pctCell(report.overall.percentage, report.overall.shortage)}</td>
            </tr>
            {report.not_counted.map((s) => (
              <tr key={s.name} style={{ color: "var(--erp-text-muted)" }}>
                <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.8rem" }}>{s.code}</td>
                <td colSpan={7}>{s.name} · not counted here</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
