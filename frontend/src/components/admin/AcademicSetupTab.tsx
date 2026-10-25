import React, { useCallback, useEffect, useState } from "react";
import { api } from "../../services";
import type { Cohort, GroupSet, OrgStructure } from "../../utils/organisation.ts";
import { errorText, smallButton, type Banner } from "./adminShared.ts";
import { StructureSection } from "./academic/StructureSection";
import { SubjectsSection } from "./academic/SubjectsSection";
import { ClassesSection } from "./academic/ClassesSection";
import { TimetableSection } from "./academic/TimetableSection";
import { CalendarSection } from "./academic/CalendarSection";
import { SettingsSection } from "./academic/SettingsSection";
import { SectionListsSection } from "./academic/SectionListsSection";

const SECTIONS = [
  { id: "structure", label: "Structure" },
  { id: "subjects", label: "Subjects" },
  { id: "classes", label: "Classes" },
  { id: "timetable", label: "Timetable" },
  { id: "sectionLists", label: "Section lists" },
  { id: "calendar", label: "Calendar" },
  { id: "settings", label: "Settings" },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

export interface AcademicSectionProps {
  cohort: Cohort;
  groupSets: GroupSet[];
  notify: (banner: Banner) => void;
  refreshStructure: () => Promise<void>;
}

// The pilot's academic setup: branch -> year/semester -> sections and the
// year-wide groups, the subject catalog, classes, timetable versions, holidays
// and settings. One cohort for now (CSE-DS, 3rd year, Semester V); the screens
// read the structure from the server, so another year or branch needs no change here.
export const AcademicSetupTab: React.FC<{ notify: (banner: Banner) => void }> = ({ notify }) => {
  const [structure, setStructure] = useState<OrgStructure | null>(null);
  const [loading, setLoading] = useState(true);
  const [cohortId, setCohortId] = useState<string>("");
  const [section, setSection] = useState<SectionId>("structure");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.getOrgStructure();
      setStructure(data);
      const first = data.branches.flatMap((b) => b.cohorts)[0];
      setCohortId((current) => current || first?.cohort_id || "");
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to load the academic setup: ${errorText(err)}` });
    } finally {
      setLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    void load();
  }, [load]);

  const seed = async () => {
    setBusy(true);
    try {
      await api.seedPilotStructure();
      notify({ type: "success", text: "The CSE-DS 3rd-year Semester V structure and subjects were created." });
      await load();
    } catch (err: unknown) {
      notify({ type: "error", text: `Failed to create the structure: ${errorText(err)}` });
    } finally {
      setBusy(false);
    }
  };

  const cohorts = structure?.branches.flatMap((b) => b.cohorts) ?? [];
  const cohort = cohorts.find((c) => c.cohort_id === cohortId);

  return (
    <div>
      <div className="erp-page-header">
        <h1 className="erp-page-title">Academic Setup</h1>
        <p className="erp-page-subtitle">
          Branch → year and semester → sections, year-wide groups, subjects, classes and timetable
        </p>
      </div>

      {loading && <div className="erp-empty-box">Loading...</div>}

      {!loading && structure && cohorts.length === 0 && (
        <div className="erp-card" style={{ padding: "1.5rem" }}>
          <p style={{ marginTop: 0 }}>
            Nothing has been set up yet. This creates the term, branch CSE-DS, the 3rd-year Semester V cohort with
            sections A to D, the elective and workshop groups, and the subject catalog. No teachers are assigned and
            no students are affected.
          </p>
          <button type="button" className="erp-btn erp-btn-primary" disabled={busy} onClick={() => void seed()}>
            {busy ? "Creating..." : "Create the pilot structure"}
          </button>
        </div>
      )}

      {!loading && cohort && (
        <>
          <div
            style={{ display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap", marginBottom: "1.25rem" }}
          >
            {cohorts.length > 1 ? (
              <select
                aria-label="Year and semester"
                className="erp-select-input"
                value={cohortId}
                onChange={(e) => setCohortId(e.target.value)}
              >
                {cohorts.map((c) => (
                  <option key={c.cohort_id} value={c.cohort_id}>
                    {c.name}
                  </option>
                ))}
              </select>
            ) : (
              <strong>{cohort.name}</strong>
            )}
            <span style={{ color: "var(--erp-text-muted)", fontSize: "0.875rem" }}>Term {cohort.term_id}</span>
          </div>

          <div role="tablist" aria-label="Academic setup" style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "1.5rem" }}>
            {SECTIONS.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={section === item.id}
                className={`erp-btn ${section === item.id ? "erp-btn-primary" : "erp-btn-secondary"}`}
                style={smallButton}
                onClick={() => setSection(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>

          {(() => {
            const props: AcademicSectionProps = {
              cohort,
              groupSets: [...cohort.elective_sets, ...cohort.workshop_sets],
              notify,
              refreshStructure: load,
            };
            switch (section) {
              case "structure":
                return <StructureSection {...props} terms={structure?.terms ?? []} />;
              case "subjects":
                return <SubjectsSection {...props} />;
              case "classes":
                return <ClassesSection {...props} />;
              case "timetable":
                return <TimetableSection {...props} />;
              case "sectionLists":
                return <SectionListsSection {...props} />;
              case "calendar":
                return <CalendarSection {...props} />;
              case "settings":
                return <SettingsSection {...props} />;
            }
          })()}
        </>
      )}
    </div>
  );
};
