// The admin's one way of moving through the college: Year > Branch > Section,
// with the year-wide groups (DE-II, DE-III, DLDA) under the year and branch.
// Built from the organisation model, so another year or branch needs no code.
// Pure helpers only, so they can be tested without a browser.

import type { Cohort, GroupSet, OrgStructure } from "./organisation.ts";

export interface NavBranch {
  branch: string;
  cohortId: string;
  name: string;
  sections: string[];
  groupSets: GroupSet[];
}

export interface NavYear {
  year: number;
  label: string;
  branches: NavBranch[];
}

export interface NavSelection {
  cohortId: string;
  section: string; // "" = every section
  setCode: string; // "" = no group filter
  group: string; // "" = every group of the set
}

export const EMPTY_SELECTION: NavSelection = { cohortId: "", section: "", setCode: "", group: "" };

export function yearLabel(year: number): string {
  const tens = year % 100;
  const suffix = tens >= 11 && tens <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[year % 10] ?? "th";
  return `${year}${suffix} year`;
}

// Years first (newest batch rolls out first: highest year first), then branches.
export function navYears(structure: OrgStructure | null): NavYear[] {
  const cohorts: Cohort[] = structure?.branches.flatMap((b) => b.cohorts) ?? [];
  const years = new Map<number, NavBranch[]>();
  for (const cohort of cohorts) {
    const list = years.get(cohort.year) ?? [];
    list.push({
      branch: cohort.branch,
      cohortId: cohort.cohort_id,
      name: cohort.name,
      sections: [...cohort.sections].sort(),
      groupSets: [...cohort.elective_sets, ...cohort.workshop_sets],
    });
    years.set(cohort.year, list);
  }
  return [...years.entries()]
    .sort((a, b) => b[0] - a[0])
    .map(([year, branches]) => ({ year, label: yearLabel(year), branches: branches.sort((a, b) => a.branch.localeCompare(b.branch)) }));
}

export function findBranch(years: NavYear[], cohortId: string): { year: NavYear; branch: NavBranch } | undefined {
  for (const year of years) {
    const branch = year.branches.find((b) => b.cohortId === cohortId);
    if (branch) return { year, branch };
  }
  return undefined;
}

// A stored selection that no longer fits the structure falls back to the first branch.
export function validSelection(years: NavYear[], wanted: NavSelection): NavSelection {
  const found = findBranch(years, wanted.cohortId);
  if (!found) {
    const first = years[0]?.branches[0];
    return first ? { ...EMPTY_SELECTION, cohortId: first.cohortId } : EMPTY_SELECTION;
  }
  const section = found.branch.sections.includes(wanted.section) ? wanted.section : "";
  const set = found.branch.groupSets.find((s) => s.set_code === wanted.setCode);
  const groups = set ? set.options.flatMap((o) => o.groups) : [];
  return {
    cohortId: wanted.cohortId,
    section,
    setCode: set ? set.set_code : "",
    group: set && groups.includes(wanted.group) ? wanted.group : "",
  };
}

// "3rd year › CSE-DS › Section B", the one-line breadcrumb (also the phone layout).
export function breadcrumb(years: NavYear[], selection: NavSelection): string {
  const found = findBranch(years, selection.cohortId);
  if (!found) return "—";
  const parts = [found.year.label, found.branch.branch, selection.section ? `Section ${selection.section}` : "All sections"];
  if (selection.setCode) parts.push(selection.group ? `${selection.setCode} ${selection.group}` : selection.setCode);
  return parts.join(" › ");
}

// The query a registry call needs for this selection.
export function selectionQuery(selection: NavSelection): Record<string, string> {
  const query: Record<string, string> = {};
  if (selection.cohortId) query.cohort_id = selection.cohortId;
  if (selection.section) query.section = selection.section;
  if (selection.setCode) query.set_code = selection.setCode;
  if (selection.group) query.group = selection.group;
  return query;
}

export interface LevelCounts {
  total: number;
  approved: number;
  waiting: number;
}

// "64 · 3 waiting", or just "64".
export function countLabel(counts: LevelCounts | undefined): string {
  if (!counts) return "0";
  return counts.waiting > 0 ? `${counts.total} · ${counts.waiting} waiting` : `${counts.total}`;
}

const STORAGE_KEY = "admin.navigator";

export function loadSelection(): NavSelection {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? { ...EMPTY_SELECTION, ...(JSON.parse(raw) as Partial<NavSelection>) } : EMPTY_SELECTION;
  } catch {
    return EMPTY_SELECTION;
  }
}

export function saveSelection(selection: NavSelection): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(selection));
  } catch {
    // Remembering the choice is a convenience only.
  }
}
