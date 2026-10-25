import React, { useEffect, useState } from "react";
import { api } from "../../services";
import type { NavYear } from "../../utils/orgNavigator.ts";
import type { StudentRegistry } from "../../utils/registry.ts";

// Students per year > branch > section: approved, waiting, and those who
// signed up without sending their setup yet.
export const SectionOverview: React.FC<{ years: NavYear[] }> = ({ years }) => {
  const [counts, setCounts] = useState<StudentRegistry["counts"] | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getStudentRegistry()
      .then((data) => {
        if (!cancelled) setCounts(data.counts);
      })
      .catch(() => {
        // The rest of the overview still shows.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (years.length === 0) return null;

  return (
    <div className="erp-card" style={{ marginBottom: "1.5rem" }}>
      <h2 className="erp-section-title">Students by year, branch and section</h2>
      <div className="erp-table-container">
        <table className="erp-table">
          <thead>
            <tr>
              <th>Year</th>
              <th>Branch</th>
              <th>Section</th>
              <th>Students</th>
              <th>Approved</th>
              <th>Waiting</th>
            </tr>
          </thead>
          <tbody>
            {years.flatMap((year) =>
              year.branches.flatMap((branch) =>
                branch.sections.map((section) => {
                  const level = counts?.cohorts[branch.cohortId]?.sections[section];
                  return (
                    <tr key={`${branch.cohortId}-${section}`}>
                      <td>{year.label}</td>
                      <td>{branch.branch}</td>
                      <td>Section {section}</td>
                      <td>{level?.total ?? 0}</td>
                      <td>{level?.approved ?? 0}</td>
                      <td>{level?.waiting ? <span className="status-badge warning">{level.waiting}</span> : 0}</td>
                    </tr>
                  );
                }),
              ),
            )}
          </tbody>
        </table>
      </div>
      <p style={{ margin: "0.75rem 0 0", fontSize: "0.85rem", color: "var(--erp-text-muted)" }}>
        Signed up without sending their setup: {counts?.no_setup ?? 0}.
      </p>
    </div>
  );
};
