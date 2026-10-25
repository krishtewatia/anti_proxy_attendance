import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../../services";
import {
  audienceFilterLabel,
  audienceFilters,
  audienceLabel,
  decodeFilter,
  encodeFilter,
  lecturesPerWeek,
  matchesAudience,
  versionInForce,
  type OrgClass,
  type OrgSlot,
  type OrgSubject,
} from "../../../utils/organisation.ts";
import { errorText } from "../adminShared.ts";
import type { AcademicSectionProps } from "../AcademicSetupTab";

// Classes: a subject taught to one section or one year-wide group. Teachers are
// assigned later (no faculty data yet), so every class shows "Not assigned".
export const ClassesSection: React.FC<AcademicSectionProps> = ({ cohort, groupSets, notify }) => {
  const [classes, setClasses] = useState<OrgClass[]>([]);
  const [subjects, setSubjects] = useState<Record<string, OrgSubject>>({});
  const [slots, setSlots] = useState<OrgSlot[]>([]);
  const [filter, setFilter] = useState("ALL");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [classList, subjectList, versions] = await Promise.all([
        api.getOrgClasses(cohort.cohort_id),
        api.getOrgSubjects(),
        api.getTimetableVersions(cohort.cohort_id),
      ]);
      setClasses(classList);
      setSubjects(Object.fromEntries(subjectList.map((s) => [s.key, s])));
      const today = new Date().toISOString().slice(0, 10);
      // Lectures a week from the version in force today, else the newest one.
      const version = versionInForce(versions, today) ?? versions[0];
      setSlots(version ? await api.getTimetableSlots(version.version_id) : []);
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to load classes: ${errorText(err)}` });
    } finally {
      setLoading(false);
    }
  }, [cohort.cohort_id, notify]);

  useEffect(() => {
    void load();
  }, [load]);

  const lectures = useMemo(() => lecturesPerWeek(slots), [slots]);
  const active = decodeFilter(filter);
  const query = search.trim().toLowerCase();
  const visible = classes.filter((c) => {
    if (!matchesAudience(c.audience, active)) return false;
    if (!query) return true;
    const subject = subjects[c.subject_key];
    return [c.label, subject?.code ?? "", subject?.name ?? ""].some((v) => v.toLowerCase().includes(query));
  });

  return (
    <div>
      <div className="erp-table-action-bar">
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          <select aria-label="Show classes of" className="erp-select-input" value={filter} onChange={(e) => setFilter(e.target.value)}>
            {audienceFilters(cohort).map((f) => (
              <option key={encodeFilter(f)} value={encodeFilter(f)}>
                {audienceFilterLabel(f)}
              </option>
            ))}
          </select>
          <input
            type="search"
            className="erp-search-input"
            placeholder="Search by subject or code"
            aria-label="Search classes"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <span style={{ fontSize: "0.875rem", color: "var(--erp-text-muted)" }}>
          {visible.length} of {classes.length} classes
        </span>
      </div>

      <div className="erp-table-container">
        <table className="erp-table">
          <thead>
            <tr>
              <th>Subject</th>
              <th>ERP code</th>
              <th>Taught to</th>
              <th>Lectures a week</th>
              <th>Teachers</th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 && (
              <tr>
                <td colSpan={5} style={{ textAlign: "center", color: "var(--erp-text-muted)" }}>
                  {loading ? "Loading..." : classes.length === 0 ? "No classes yet: import the timetable first." : "No class matches."}
                </td>
              </tr>
            )}
            {visible.map((c) => {
              const subject = subjects[c.subject_key];
              return (
                <tr key={c.class_id}>
                  <td style={{ fontWeight: 600 }}>{subject?.name ?? c.subject_key}</td>
                  <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.8125rem" }}>{subject?.code ?? "—"}</td>
                  <td>{audienceLabel(c.audience, groupSets)}</td>
                  <td>{lectures.get(c.class_id) ?? "—"}</td>
                  <td>
                    {c.teacher_ids.length ? (
                      `${c.teacher_ids.length} assigned`
                    ) : (
                      <span className="status-badge completed">Not assigned</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
