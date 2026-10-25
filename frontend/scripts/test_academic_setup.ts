// The admin "Academic Setup" screens: audience labels and filters, the week
// grid, lectures per week, timetable versions in force, and the wiring of the
// new menu entry. The grid is checked against slots shaped like the real
// CSE-DS 3rd-year Semester V sheet.

import { readFileSync } from "node:fs";
import {
  audienceFilters,
  audienceLabel,
  decodeFilter,
  encodeFilter,
  lecturesPerWeek,
  matchesAudience,
  openFlags,
  versionInForce,
  weekGrid,
  type Audience,
  type Cohort,
  type OrgSlot,
  type TimetableVersion,
} from "../src/utils/organisation.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

const cohort: Cohort = {
  cohort_id: "CSE-DS-Y3-2026-27-ODD",
  branch: "CSE-DS",
  year: 3,
  semester: "V",
  term_id: "2026-27-ODD",
  name: "B.Tech CSE-DS, 3rd year, Semester V",
  sections: ["A", "B", "C", "D"],
  elective_sets: [
    {
      set_code: "DE-II",
      kind: "ELECTIVE",
      name: "Department Elective II",
      options: [
        { option_code: "PA", name: "Predictive Analytics", subject_keys: ["PRED", "PRED_LAB"], groups: ["G1", "G2", "G3"] },
        { option_code: "AJ", name: "Advance Java Programming", subject_keys: ["AJAVA", "AJAVA_LAB"], groups: ["AJ"] },
      ],
    },
  ],
  workshop_sets: [
    {
      set_code: "DLDA",
      kind: "WORKSHOP",
      name: "DLDA workshop groups",
      options: [{ option_code: "DLDA", name: "Deep Learning for Data Analytics", subject_keys: ["DLDA"], groups: ["DL1", "DL2", "DL3", "DL4"] }],
    },
  ],
};

const sectionB: Audience = { kind: "SECTION", section: "B" };
const paG1: Audience = { kind: "GROUP", set_code: "DE-II", set_kind: "ELECTIVE", option_code: "PA", group_code: "G1" };
const dl2: Audience = { kind: "GROUP", set_code: "DLDA", set_kind: "WORKSHOP", option_code: "DLDA", group_code: "DL2" };

let row = 1;
function slot(day: string, start: string, end: string, periods: number, subject: string, audience: Audience, flags: OrgSlot["flags"] = []): OrgSlot {
  const minutes = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3));
  row += 1;
  return {
    slot_id: `s${row}`,
    version_id: "v1",
    row,
    class_id: `${subject}@${audience.kind === "SECTION" ? audience.section : audience.group_code}`,
    subject_key: subject,
    audience,
    day,
    start,
    end,
    start_minute: minutes(start),
    end_minute: minutes(end),
    periods,
    room: "B310",
    note: "",
    flags,
    label: `${day} ${start}-${end} ${subject}`,
  };
}

async function run() {
  console.log("==================================================");
  console.log("   Academic Setup: Structure, Classes, Timetable  ");
  console.log("==================================================");

  console.log("\n[1/5] Audiences read the way the college says them...");
  expect(audienceLabel(sectionB) === "Section B", `section label: ${audienceLabel(sectionB)}`);
  const groupSets = [...cohort.elective_sets, ...cohort.workshop_sets];
  expect(audienceLabel(paG1, groupSets) === "DE-II · Predictive Analytics · G1", `group label: ${audienceLabel(paG1, groupSets)}`);
  expect(audienceLabel(dl2, groupSets) === "DLDA · Deep Learning for Data Analytics · DL2", "workshop label");

  console.log("[2/5] Filters: each section, then elective sets, then workshop sets...");
  const filters = audienceFilters(cohort).map(encodeFilter);
  expect(
    filters.join(",") === "ALL,SECTION:A,SECTION:B,SECTION:C,SECTION:D,SET:DE-II,SET:DLDA",
    `unexpected filters: ${filters.join(",")}`,
  );
  for (const value of filters) expect(encodeFilter(decodeFilter(value)) === value, `filter ${value} does not round-trip`);
  expect(matchesAudience(sectionB, decodeFilter("SECTION:B")) && !matchesAudience(sectionB, decodeFilter("SECTION:A")), "section filter");
  // A year-wide group never shows up as a section's class, and the two kinds of sets stay apart.
  expect(!matchesAudience(paG1, decodeFilter("SECTION:B")), "a group class is not a section class");
  expect(matchesAudience(paG1, decodeFilter("SET:DE-II")) && !matchesAudience(paG1, decodeFilter("SET:DLDA")), "elective vs workshop sets");

  console.log("[3/5] The week grid: one row per time range, double periods counted twice...");
  const slots = [
    slot("MON", "10:00", "10:50", 1, "CN", sectionB),
    slot("MON", "13:30", "15:20", 2, "DCC", sectionB),
    slot("TUE", "09:10", "10:00", 1, "DCC_LAB", sectionB),
    slot("WED", "10:00", "10:50", 1, "DCC_LAB", sectionB),
    slot("FRI", "10:50", "11:40", 1, "CN", sectionB, [{ kind: "CONFIRM", text: "confirm single or double" }]),
    slot("FRI", "11:40", "12:30", 1, "CN", sectionB, [{ kind: "CONFIRM", text: "confirm single or double", resolved: true }]),
  ];
  const grid = weekGrid(slots);
  expect(grid.days.join(",") === "MON,TUE,WED,THU,FRI", `days: ${grid.days.join(",")} (no Saturday without Saturday slots)`);
  expect(grid.rows.map((r) => r.start).join(",") === "09:10,10:00,10:50,11:40,13:30", `rows: ${grid.rows.map((r) => r.start).join(",")}`);
  const ten = grid.rows.find((r) => r.start === "10:00")!;
  expect(ten.cells.MON.length === 1 && ten.cells.WED.length === 1 && ten.cells.TUE.length === 0, "10:00 row cells");
  const weekly = lecturesPerWeek(slots);
  expect(weekly.get("CN@B") === 3 && weekly.get("DCC@B") === 2 && weekly.get("DCC_LAB@B") === 2, `lectures a week: ${JSON.stringify([...weekly])}`);
  expect(openFlags(slots[4]).length === 1 && openFlags(slots[5]).length === 0, "a checked flag is no longer open");

  console.log("[4/5] The version in force on a day...");
  const version = (id: string, status: "DRAFT" | "ACTIVE", from: string | null): TimetableVersion => ({
    version_id: id,
    cohort_id: cohort.cohort_id,
    status,
    effective_from: from,
    source_name: `${id}.csv`,
    rows: 92,
    slots: 92,
    flagged_slots: 32,
    created_at: "2026-10-25T10:00:00Z",
  });
  const versions = [version("v1", "ACTIVE", "2026-11-02"), version("v2", "ACTIVE", "2026-12-01"), version("v3", "DRAFT", null)];
  expect(versionInForce(versions, "2026-11-01") === undefined, "nothing before the first effective date");
  expect(versionInForce(versions, "2026-11-30")?.version_id === "v1", "v1 until v2 starts");
  expect(versionInForce(versions, "2026-12-01")?.version_id === "v2", "v2 from its date");
  expect(versionInForce([version("v3", "DRAFT", null)], "2027-01-01") === undefined, "a draft is never in force");

  console.log("[5/5] The menu entry and the screens are wired, in the existing style...");
  const layout = readFileSync("src/components/layout/AppLayout.tsx", "utf-8");
  expect(layout.includes('id: "academic"') && layout.includes('label: "Academic Setup"'), "the admin menu must have Academic Setup");
  const dashboard = readFileSync("src/pages/AdminDashboard.tsx", "utf-8");
  expect(dashboard.includes('activeTab === "academic" && <AcademicSetupTab'), "the admin page must show the Academic Setup tab");
  const tab = readFileSync("src/components/admin/AcademicSetupTab.tsx", "utf-8");
  for (const name of ["Structure", "Subjects", "Classes", "Timetable", "Calendar", "Settings"]) {
    expect(tab.includes(`label: "${name}"`), `Academic Setup must have a ${name} section`);
  }
  for (const file of ["StructureSection", "SubjectsSection", "ClassesSection", "TimetableSection", "CalendarSection", "SettingsSection"]) {
    const source = readFileSync(`src/components/admin/academic/${file}.tsx`, "utf-8");
    expect(!/#[0-9a-fA-F]{3,6}\b/.test(source), `${file} must use the existing colour tokens, not its own colours`);
  }
  const timetable = readFileSync("src/components/admin/academic/TimetableSection.tsx", "utf-8");
  expect(timetable.includes("importTimetable(cohort.cohort_id, text, file.name, true)"), "a sheet is always checked (dry run) before it is stored");

  console.log("\n✅ All Academic Setup checks passed.");
}

run().catch((err) => {
  console.error("\n❌ Academic Setup checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
