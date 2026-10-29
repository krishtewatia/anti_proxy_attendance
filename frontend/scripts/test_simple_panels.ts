// Simple panels: four Academic sections with explicit Save buttons, the
// timetable's numbered steps, the student and teacher menus, and the card a
// teacher sees while waiting for approval.

import { readFileSync } from "node:fs";
import { TIMETABLE_COLUMNS, timetableSteps } from "../src/utils/organisation.ts";
import { TEACHER_PENDING_TEXT, isTeacherPendingError, registeredMessage } from "../src/utils/registration.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

function menu(role: string): string[] {
  const layout = readFileSync("src/components/layout/AppLayout.tsx", "utf-8");
  const block = layout.slice(layout.indexOf(`case "${role}":`));
  return [...block.slice(0, block.indexOf("];")).matchAll(/label: "([^"]+)"/g)].map((m) => m[1]);
}

async function run() {
  console.log("==================================================");
  console.log("   Simple Panels: Academic, Student, Teacher      ");
  console.log("==================================================");

  console.log("\n[1/4] The timetable's four steps...");
  const state = (o: Parameters<typeof timetableSteps>[0]) => timetableSteps(o).map((s) => s.state[0]).join("");
  expect(state({ checking: false, hasDraft: false, inForce: false }) === "cttt", "start: choose the CSV");
  expect(state({ checking: true, hasDraft: false, inForce: false }) === "dctt", "reviewing the check");
  expect(state({ checking: false, hasDraft: true, inForce: false }) === "dddc", "a draft waits to be activated");
  expect(state({ checking: false, hasDraft: false, inForce: true }) === "dddd", "in force: all done");
  expect(timetableSteps({ checking: false, hasDraft: false, inForce: false }).map((s) => s.label).join(" > ") === "Choose the timetable CSV > Review the check > Save as draft > Activate from a date", "step labels");

  console.log("[2/4] Academic: four sections, each change behind a button...");
  const tab = readFileSync("src/components/admin/AcademicSetupTab.tsx", "utf-8");
  const sections = [...tab.slice(0, tab.indexOf("] as const")).matchAll(/label: "([^"]+)"/g)].map((m) => m[1]);
  expect(sections.join() === "Structure,Timetable,Subjects and classes,Calendar and settings", `sections: ${sections}`);
  expect(readFileSync("src/components/admin/academic/StructureSection.tsx", "utf-8").includes("Save term dates"), "term dates have a Save button");
  expect(readFileSync("src/components/admin/academic/SettingsSection.tsx", "utf-8").includes("Save settings"), "settings have a Save button");
  const timetable = readFileSync("src/components/admin/academic/TimetableSection.tsx", "utf-8");
  expect(timetable.includes('"3. SAVE AS DRAFT"') && timetable.includes("4. Activate") && timetable.includes("1. Choose the timetable CSV"), "numbered timetable buttons");
  expect(timetable.includes("Download sample CSV") && timetable.includes("TIMETABLE_SAMPLE_PATH") && timetable.includes("TIMETABLE_COLUMNS.join"), "a sample timetable CSV and its columns next to the upload");
  const server = readFileSync("../backend/app/services/organisation_service.py", "utf-8");
  const serverColumns = [...server.slice(server.indexOf("TIMETABLE_COLUMNS = ["), server.indexOf("]", server.indexOf("TIMETABLE_COLUMNS = ["))).matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
  expect(serverColumns.join() === TIMETABLE_COLUMNS.join(), `the listed columns are the importer's: ${serverColumns}`);

  console.log("[3/4] Student and teacher menus...");
  expect(menu("STUDENT").join() === "Home,My Setup,Attendance,Profile", `student menu: ${menu("STUDENT")}`);
  expect(menu("TEACHER").join() === "Home,My Classes,Take Attendance,Sessions,Profile", `teacher menu: ${menu("TEACHER")}`);
  const student = readFileSync("src/pages/StudentDashboard.tsx", "utf-8");
  expect(student.includes("{renderAttendanceView()}") && student.includes("{renderHistoryView()}"), "attendance and history on one page");

  console.log("[4/4] A teacher waiting for approval...");
  expect(isTeacherPendingError(new Error(TEACHER_PENDING_TEXT)) && !isTeacherPendingError(new Error("Network error")), "the waiting answer is recognised");
  expect(registeredMessage("TEACHER").startsWith("Account created. Sign in now"), "teachers sign in straight away");
  const teacher = readFileSync("src/pages/TeacherAttendanceFlow.tsx", "utf-8");
  expect(teacher.includes("setWaitingForApproval(true)") && teacher.includes("{TEACHER_PENDING_TEXT}"), "one card while waiting");

  console.log("\n✅ All simple panel checks passed.");
}

run().catch((err) => {
  console.error("\n❌ Simple panel checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
