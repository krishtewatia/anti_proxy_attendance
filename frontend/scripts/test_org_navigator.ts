// The organised admin panel: Year > Branch > Section navigator, the
// registries' helpers, the 7-entry admin menu with the account menu, and the
// older flat screens only on a database without the pilot structure.

import { readFileSync } from "node:fs";
import { breadcrumb, countLabel, navYears, selectionQuery, validSelection, yearLabel } from "../src/utils/orgNavigator.ts";
import { classLabel, shortChoice, teachersFor, type RegistryTeacher } from "../src/utils/registry.ts";
import type { Cohort, OrgStructure } from "../src/utils/organisation.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

function cohort(id: string, branch: string, year: number, sections: string[]): Cohort {
  return {
    cohort_id: id,
    branch,
    year,
    semester: year === 3 ? "V" : "III",
    term_id: "2026-27-ODD",
    name: `${branch} ${year}`,
    sections,
    elective_sets: year === 3 ? [{ set_code: "DE-II", kind: "ELECTIVE", name: "DE-II", options: [{ option_code: "PA", name: "Predictive Analytics", subject_keys: [], groups: ["G1", "G2", "G3"] }, { option_code: "AJ", name: "Advance Java", subject_keys: [], groups: ["AJ"] }] }] : [],
    workshop_sets: [],
  };
}

const structure: OrgStructure = {
  terms: [],
  branches: [
    { code: "CSE-DS", name: "CSE-DS", department: "CSE", cohorts: [cohort("ds3", "CSE-DS", 3, ["D", "A", "C", "B"]), cohort("ds2", "CSE-DS", 2, ["A", "B"])] },
    { code: "CSE-AI", name: "CSE-AI", department: "CSE", cohorts: [cohort("ai3", "CSE-AI", 3, ["A"])] },
  ],
};

async function run() {
  console.log("==================================================");
  console.log("   Organised Admin Panel: Year > Branch > Section ");
  console.log("==================================================");

  console.log("\n[1/4] Years first, then branches, then sections...");
  const years = navYears(structure);
  expect(years.map((y) => y.label).join() === "3rd year,2nd year", `years: ${years.map((y) => y.label)}`);
  expect(years[0].branches.map((b) => b.branch).join() === "CSE-AI,CSE-DS", "branches in a year");
  expect(years[0].branches[1].sections.join("") === "ABCD", "sections in order");
  expect(yearLabel(1) === "1st year" && yearLabel(2) === "2nd year" && yearLabel(4) === "4th year" && yearLabel(11) === "11th year", "year labels");
  expect(navYears(null).length === 0, "no structure, no navigator");

  console.log("[2/4] A choice stays valid, reads as one line, and becomes a query...");
  expect(validSelection(years, { cohortId: "gone", section: "B", setCode: "", group: "" }).cohortId === "ai3", "unknown branch falls back to the first");
  const chosen = validSelection(years, { cohortId: "ds3", section: "B", setCode: "DE-II", group: "AJ" });
  expect(chosen.section === "B" && chosen.group === "AJ", "a valid choice is kept");
  expect(validSelection(years, { cohortId: "ds3", section: "Z", setCode: "DE-II", group: "G9" }).section === "", "an unknown section is cleared");
  expect(breadcrumb(years, chosen) === "3rd year › CSE-DS › Section B › DE-II AJ", `breadcrumb: ${breadcrumb(years, chosen)}`);
  expect(JSON.stringify(selectionQuery(chosen)) === JSON.stringify({ cohort_id: "ds3", section: "B", set_code: "DE-II", group: "AJ" }), "query");
  expect(countLabel({ total: 64, approved: 61, waiting: 3 }) === "64 · 3 waiting" && countLabel({ total: 5, approved: 5, waiting: 0 }) === "5", "counts");

  console.log("[3/4] Registry helpers...");
  expect(shortChoice("DE-II", { option: "PA", group: "G2" }) === "PA G2" && shortChoice("DE-III", { option: "DP", group: "DP" }) === "DP", "short choices");
  const teacher = (id: string, cohorts: string[]): RegistryTeacher => ({
    user_id: id, name: id, email: `${id}@niet.co.in`, department: null, approved: true,
    classes: cohorts.map((c) => ({ class_id: `${c}:B:CN`, cohort_id: c, subject_key: "CN", subject: "Computer Networks", code: "BCSE0502A", audience: { kind: "SECTION" as const, section: "B" } })),
    cohorts: cohorts.map((c) => ({ cohort_id: c, year: 3, branch: "CSE-DS" })),
  });
  const split = teachersFor([teacher("a", ["ds3"]), teacher("b", ["ds2"]), teacher("c", [])], "ds3");
  expect(split.assigned.map((t) => t.user_id).join() === "a" && split.unassigned.map((t) => t.user_id).join() === "c", "teachers per year and branch");
  expect(classLabel(teacher("a", ["ds3"]).classes[0]) === "Section B · Computer Networks", "class label");

  console.log("[4/4] Menus and wiring...");
  const layout = readFileSync("src/components/layout/AppLayout.tsx", "utf-8");
  const admin = layout.slice(layout.indexOf('case "ADMIN":'));
  const ids = [...admin.slice(0, admin.indexOf("];")).matchAll(/id: "(\w+)"/g)].map((m) => m[1]);
  expect(ids.join() === "dashboard,approvals,students,teachers,academic,sessions,reports", `admin menu: ${ids}`);
  expect(layout.includes('{ id: "admins", label: "Administrators" }') && layout.includes('{ id: "profile", label: "My profile" }'), "account menu");
  const dashboard = readFileSync("src/pages/AdminDashboard.tsx", "utf-8");
  expect(dashboard.includes("org.pilot ? (") && dashboard.includes("<StudentRegistryTab") && dashboard.includes("<TeacherRegistryTab"), "registries when the structure exists");
  expect(dashboard.includes('legacyAcademic === "classes" && <ClassesTab'), "flat classes only without the structure");
  const approvals = readFileSync("src/components/admin/SetupRequestsSection.tsx", "utf-8");
  expect(approvals.includes("<OrgNavigator"), "approvals use the navigator");

  console.log("\n✅ All organised admin panel checks passed.");
}

run().catch((err) => {
  console.error("\n❌ Organised admin panel checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
