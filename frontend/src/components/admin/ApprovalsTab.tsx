import React, { useCallback, useEffect, useState } from "react";
import { api } from "../../services";
import { AuthenticatedImage } from "../common/AuthenticatedImage";
import {
  daysUntilPurge,
  normalizeClassCodes,
  registrationAge,
  validateStudentApproval,
  validateTeacherApproval,
  type PendingApprovals,
  type PendingStudent,
  type PendingTeacher,
} from "../../utils/approvals.ts";

interface ApprovalsTabProps {
  // Class codes an administrator can assign (active classes).
  classCodes: string[];
  branches: Array<{ name: string; sections: string[] }>;
  onCountChange?: (total: number) => void;
}

const photoStyle: React.CSSProperties = {
  width: "72px",
  height: "72px",
  borderRadius: "8px",
  objectFit: "cover",
  border: "1px solid var(--erp-border)",
};

const PhotoPlaceholder: React.FC<{ label: string }> = ({ label }) => (
  <div
    style={{
      ...photoStyle,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: "#e2e8f0",
      color: "#475569",
      fontSize: "0.7rem",
      textAlign: "center",
    }}
  >
    {label}
  </div>
);

export const ApprovalsTab: React.FC<ApprovalsTabProps> = ({ classCodes, branches, onCountChange }) => {
  const [pending, setPending] = useState<PendingApprovals | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // What the administrator has chosen for each row before approving.
  const [teacherClasses, setTeacherClasses] = useState<Record<string, string[]>>({});
  const [studentClass, setStudentClass] = useState<Record<string, { branch: string; section: string }>>({});

  const load = useCallback(async () => {
    try {
      const data = await api.getPendingApprovals();
      setPending(data);
      onCountChange?.(data.counts.total);
    } catch (err) {
      setBanner({ type: "error", text: err instanceof Error ? err.message : "Could not load pending approvals." });
    } finally {
      setLoading(false);
    }
  }, [onCountChange]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (id: string, action: () => Promise<unknown>, done: string) => {
    setBusyId(id);
    setBanner(null);
    try {
      await action();
      setBanner({ type: "success", text: done });
      await load();
    } catch (err) {
      setBanner({ type: "error", text: err instanceof Error ? err.message : "The action failed." });
    } finally {
      setBusyId(null);
    }
  };

  const chosenClasses = (teacher: PendingTeacher): string[] =>
    teacherClasses[teacher.user_id] ??
    normalizeClassCodes(teacher.requested_classes || []).filter((code) => classCodes.includes(code));

  const chosenStudentClass = (student: PendingStudent) =>
    studentClass[student.user_id] ?? { branch: student.branch || "", section: student.section || "" };

  const toggleClass = (teacher: PendingTeacher, code: string) => {
    const current = chosenClasses(teacher);
    const next = current.includes(code) ? current.filter((c) => c !== code) : [...current, code];
    setTeacherClasses((prev) => ({ ...prev, [teacher.user_id]: next }));
  };

  const approveTeacher = (teacher: PendingTeacher) => {
    const classes = chosenClasses(teacher);
    const problem = validateTeacherApproval(classes, classCodes);
    if (problem) {
      setBanner({ type: "error", text: problem });
      return;
    }
    void run(
      teacher.user_id,
      () =>
        api.approveRegistration(teacher.user_id, {
          assigned_classes: classes,
          assigned_subjects: teacher.requested_subjects || [],
        }),
      `${teacher.name || teacher.email} approved and assigned ${classes.join(", ")}.`,
    );
  };

  const approveStudent = (student: PendingStudent) => {
    const { branch, section } = chosenStudentClass(student);
    const problem = validateStudentApproval(branch, section);
    if (problem) {
      setBanner({ type: "error", text: problem });
      return;
    }
    void run(
      student.user_id,
      () => api.approveRegistration(student.user_id, { branch, section }),
      `${student.name || student.email} approved.`,
    );
  };

  const reject = (userId: string, label: string) => {
    if (!window.confirm(`Reject ${label}? Everything they submitted, including any photo, is deleted. This cannot be undone.`)) {
      return;
    }
    void run(userId, () => api.rejectRegistration(userId), `${label} rejected and removed.`);
  };

  const ageLine = (registeredAt?: string | null) => {
    const age = registrationAge(registeredAt);
    const left = daysUntilPurge(registeredAt);
    if (!age) return null;
    return (
      <div style={{ fontSize: "0.75rem", color: "var(--erp-text-muted)" }}>
        Registered {age}
        {left !== null && left <= 3 ? ` · removed automatically in ${left} day${left === 1 ? "" : "s"}` : ""}
      </div>
    );
  };

  if (loading) {
    return <div className="erp-card" style={{ padding: "2rem" }}>Loading pending approvals…</div>;
  }

  const counts = pending?.counts;
  const nothing = !counts || counts.total === 0;

  return (
    <div>
      <div className="erp-page-header">
        <h1 className="erp-page-title">Pending Approvals</h1>
        <p className="erp-page-subtitle">
          New registrations cannot log in, and a new student's face is not recognized, until approved here.
          Registrations left untouched for 14 days are removed automatically.
        </p>
      </div>

      {banner && (
        <div className={`alert-banner ${banner.type}`} role={banner.type === "error" ? "alert" : "status"} style={{ marginBottom: "1rem" }}>
          <span>{banner.text}</span>
        </div>
      )}

      {nothing && (
        <div className="erp-card" style={{ padding: "2rem", textAlign: "center", color: "var(--erp-text-muted)" }}>
          Nothing is waiting for approval.
        </div>
      )}

      {pending && pending.students.length > 0 && (
        <div className="erp-card" style={{ marginBottom: "1.5rem" }}>
          <h2 className="erp-section-title">Students ({pending.students.length})</h2>
          <div className="erp-table-container">
            <table className="erp-table">
              <thead>
                <tr>
                  <th>Photo</th>
                  <th>Student</th>
                  <th>Class to approve into</th>
                  <th style={{ textAlign: "right" }}>Decision</th>
                </tr>
              </thead>
              <tbody>
                {pending.students.map((student) => {
                  const chosen = chosenStudentClass(student);
                  const sections = branches.find((b) => b.name === chosen.branch)?.sections || [];
                  return (
                    <tr key={student.user_id}>
                      <td>
                        <AuthenticatedImage
                          src={student.has_photo ? student.photo_url : null}
                          alt={`Photo submitted by ${student.name || student.email}`}
                          style={photoStyle}
                          fallback={<PhotoPlaceholder label={student.has_photo ? "Loading" : "No photo"} />}
                        />
                      </td>
                      <td>
                        <div style={{ fontWeight: 600 }}>{student.name || "(no name)"}</div>
                        <div style={{ fontSize: "0.8rem" }}>{student.student_id} · Roll {student.roll_number || "—"}</div>
                        <div style={{ fontSize: "0.8rem", color: "var(--erp-text-muted)" }}>{student.email}</div>
                        {ageLine(student.registered_at)}
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                          <select
                            aria-label={`Branch for ${student.name || student.email}`}
                            value={chosen.branch}
                            onChange={(e) =>
                              setStudentClass((prev) => ({
                                ...prev,
                                [student.user_id]: { branch: e.target.value, section: "" },
                              }))
                            }
                          >
                            <option value="">Branch…</option>
                            {branches.map((b) => (
                              <option key={b.name} value={b.name}>{b.name}</option>
                            ))}
                          </select>
                          <select
                            aria-label={`Section for ${student.name || student.email}`}
                            value={chosen.section}
                            onChange={(e) =>
                              setStudentClass((prev) => ({
                                ...prev,
                                [student.user_id]: { branch: chosen.branch, section: e.target.value },
                              }))
                            }
                          >
                            <option value="">Section…</option>
                            {sections.map((s) => (
                              <option key={s} value={s}>{s}</option>
                            ))}
                          </select>
                        </div>
                        <div style={{ fontSize: "0.75rem", color: "var(--erp-text-muted)", marginTop: "0.25rem" }}>
                          Registered for {student.class_code || "no class"}
                        </div>
                      </td>
                      <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                        <button
                          type="button"
                          className="erp-btn erp-btn-primary"
                          disabled={busyId === student.user_id}
                          onClick={() => approveStudent(student)}
                        >
                          Approve
                        </button>{" "}
                        <button
                          type="button"
                          className="erp-btn erp-btn-danger"
                          disabled={busyId === student.user_id}
                          onClick={() => reject(student.user_id, student.name || student.email)}
                        >
                          Reject
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {pending && pending.teachers.length > 0 && (
        <div className="erp-card" style={{ marginBottom: "1.5rem" }}>
          <h2 className="erp-section-title">Teachers ({pending.teachers.length})</h2>
          <div className="erp-table-container">
            <table className="erp-table">
              <thead>
                <tr>
                  <th>Teacher</th>
                  <th>Classes to assign</th>
                  <th style={{ textAlign: "right" }}>Decision</th>
                </tr>
              </thead>
              <tbody>
                {pending.teachers.map((teacher) => {
                  const chosen = chosenClasses(teacher);
                  return (
                    <tr key={teacher.user_id}>
                      <td>
                        <div style={{ fontWeight: 600 }}>{teacher.name || "(no name)"}</div>
                        <div style={{ fontSize: "0.8rem" }}>{teacher.teacher_id} · {teacher.department || "—"}</div>
                        <div style={{ fontSize: "0.8rem", color: "var(--erp-text-muted)" }}>{teacher.email}</div>
                        {ageLine(teacher.registered_at)}
                      </td>
                      <td>
                        <div role="group" aria-label={`Classes for ${teacher.name || teacher.email}`} style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                          {classCodes.map((code) => (
                            <label key={code} style={{ display: "inline-flex", alignItems: "center", gap: "0.25rem", fontSize: "0.85rem" }}>
                              <input
                                type="checkbox"
                                checked={chosen.includes(code)}
                                onChange={() => toggleClass(teacher, code)}
                              />
                              {code}
                            </label>
                          ))}
                        </div>
                        <div style={{ fontSize: "0.75rem", color: "var(--erp-text-muted)", marginTop: "0.25rem" }}>
                          Asked for: {(teacher.requested_classes || []).join(", ") || "none"}
                        </div>
                      </td>
                      <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                        <button
                          type="button"
                          className="erp-btn erp-btn-primary"
                          disabled={busyId === teacher.user_id}
                          onClick={() => approveTeacher(teacher)}
                        >
                          Approve
                        </button>{" "}
                        <button
                          type="button"
                          className="erp-btn erp-btn-danger"
                          disabled={busyId === teacher.user_id}
                          onClick={() => reject(teacher.user_id, teacher.name || teacher.email)}
                        >
                          Reject
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {pending && pending.accounts.length > 0 && (
        <div className="erp-card" style={{ marginBottom: "1.5rem" }}>
          <h2 className="erp-section-title">Accounts without a profile ({pending.accounts.length})</h2>
          <p style={{ fontSize: "0.85rem", color: "var(--erp-text-muted)" }}>
            These were registered without the student or teacher form, so there is nothing to review. Reject them unless you know who they are.
          </p>
          <div className="erp-table-container">
            <table className="erp-table">
              <tbody>
                {pending.accounts.map((account) => (
                  <tr key={account.user_id}>
                    <td>
                      {account.email} · {account.role}
                      {ageLine(account.registered_at)}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <button
                        type="button"
                        className="erp-btn erp-btn-danger"
                        disabled={busyId === account.user_id}
                        onClick={() => reject(account.user_id, account.email)}
                      >
                        Reject
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {pending && pending.photo_changes.length > 0 && (
        <div className="erp-card">
          <h2 className="erp-section-title">Photo changes ({pending.photo_changes.length})</h2>
          <p style={{ fontSize: "0.85rem", color: "var(--erp-text-muted)" }}>
            The current photo stays in use until you approve the new one. Approve only if both show the same person.
          </p>
          <div className="erp-table-container">
            <table className="erp-table">
              <thead>
                <tr>
                  <th>Student</th>
                  <th>Current</th>
                  <th>New</th>
                  <th style={{ textAlign: "right" }}>Decision</th>
                </tr>
              </thead>
              <tbody>
                {pending.photo_changes.map((change) => (
                  <tr key={change.identity}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{change.name || change.student_id}</div>
                      <div style={{ fontSize: "0.8rem" }}>{change.student_id} · {change.class_code || "—"}</div>
                    </td>
                    <td>
                      <AuthenticatedImage
                        src={change.current_photo_url}
                        alt={`Current photo of ${change.name || change.student_id}`}
                        style={photoStyle}
                        fallback={<PhotoPlaceholder label="None" />}
                      />
                    </td>
                    <td>
                      <AuthenticatedImage
                        src={change.new_photo_url}
                        alt={`New photo submitted by ${change.name || change.student_id}`}
                        style={photoStyle}
                        fallback={<PhotoPlaceholder label="Loading" />}
                      />
                    </td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      <button
                        type="button"
                        className="erp-btn erp-btn-primary"
                        disabled={busyId === change.identity}
                        onClick={() =>
                          void run(
                            change.identity,
                            () => api.approvePhotoChange(change.identity),
                            `New photo for ${change.name || change.student_id} approved.`,
                          )
                        }
                      >
                        Approve
                      </button>{" "}
                      <button
                        type="button"
                        className="erp-btn erp-btn-danger"
                        disabled={busyId === change.identity}
                        onClick={() =>
                          void run(
                            change.identity,
                            () => api.rejectPhotoChange(change.identity),
                            `New photo for ${change.name || change.student_id} rejected.`,
                          )
                        }
                      >
                        Reject
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
