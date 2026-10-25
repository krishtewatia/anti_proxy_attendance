import React from "react";
import {
  breadcrumb,
  countLabel,
  findBranch,
  type LevelCounts,
  type NavSelection,
  type NavYear,
} from "../../utils/orgNavigator.ts";

interface OrgNavigatorProps {
  years: NavYear[];
  value: NavSelection;
  onChange: (next: NavSelection) => void;
  // Counts per cohort and section, when the screen has them.
  counts?: Record<string, { total: number; approved: number; waiting: number; sections: Record<string, LevelCounts> }>;
  // Group filters (DE-II, DE-III, DLDA) where they make sense.
  showGroups?: boolean;
}

const chip: React.CSSProperties = { padding: "0.3rem 0.7rem", fontSize: "0.8125rem" };

// Year > Branch > Section (and groups), the same on every admin screen.
export const OrgNavigator: React.FC<OrgNavigatorProps> = ({ years, value, onChange, counts, showGroups = true }) => {
  const found = findBranch(years, value.cohortId);
  if (years.length === 0) return null;
  const branchCounts = found ? counts?.[found.branch.cohortId] : undefined;
  const set = found?.branch.groupSets.find((s) => s.set_code === value.setCode);

  const button = (active: boolean, label: string, onClick: () => void, key: string) => (
    <button key={key} type="button" className={`erp-btn ${active ? "erp-btn-primary" : "erp-btn-secondary"}`} style={chip} aria-pressed={active} onClick={onClick}>
      {label}
    </button>
  );

  return (
    <div className="erp-card org-navigator" style={{ padding: "0.85rem 1rem", marginBottom: "1.25rem", display: "grid", gap: "0.6rem" }}>
      <div style={{ fontSize: "0.8rem", color: "var(--erp-text-muted)", fontWeight: 600 }} aria-live="polite">
        {breadcrumb(years, value)}
      </div>
      <div className="org-navigator-row" style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", alignItems: "center" }}>
        <span className="org-navigator-label">Year</span>
        {years.map((year) =>
          button(found?.year.year === year.year, year.label, () => onChange({ cohortId: year.branches[0].cohortId, section: "", setCode: "", group: "" }), `y${year.year}`),
        )}
      </div>
      {found && (
        <div className="org-navigator-row" style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", alignItems: "center" }}>
          <span className="org-navigator-label">Branch</span>
          {found.year.branches.map((branch) =>
            button(branch.cohortId === value.cohortId, branch.branch, () => onChange({ cohortId: branch.cohortId, section: "", setCode: "", group: "" }), branch.cohortId),
          )}
        </div>
      )}
      {found && (
        <div className="org-navigator-row" style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", alignItems: "center" }}>
          <span className="org-navigator-label">Section</span>
          {button(!value.section, branchCounts ? `All (${countLabel(branchCounts)})` : "All", () => onChange({ ...value, section: "" }), "all")}
          {found.branch.sections.map((section) =>
            button(
              value.section === section,
              branchCounts ? `${section} (${countLabel(branchCounts.sections[section])})` : `Section ${section}`,
              () => onChange({ ...value, section }),
              section,
            ),
          )}
        </div>
      )}
      {found && showGroups && found.branch.groupSets.length > 0 && (
        <div className="org-navigator-row" style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", alignItems: "center" }}>
          <span className="org-navigator-label">Groups</span>
          <select
            className="erp-select-input"
            style={{ width: "auto" }}
            aria-label="Group set"
            value={value.setCode}
            onChange={(e) => onChange({ ...value, setCode: e.target.value, group: "" })}
          >
            <option value="">Any</option>
            {found.branch.groupSets.map((s) => (
              <option key={s.set_code} value={s.set_code}>{s.set_code}</option>
            ))}
          </select>
          {set && (
            <select
              className="erp-select-input"
              style={{ width: "auto" }}
              aria-label="Group"
              value={value.group}
              onChange={(e) => onChange({ ...value, group: e.target.value })}
            >
              <option value="">Every {set.set_code} group</option>
              {set.options.flatMap((o) =>
                o.groups.map((g) => (
                  <option key={`${o.option_code}-${g}`} value={g}>
                    {o.option_code === g || o.option_code === set.set_code ? g : `${o.option_code} ${g}`}
                  </option>
                )),
              )}
            </select>
          )}
        </div>
      )}
    </div>
  );
};
