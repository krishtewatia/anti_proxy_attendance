// Reports and downloads: the percentage label, download paths for class ids
// that contain ":" and "/", safe file names, and the wiring of the new views.

import { readFileSync } from "node:fs";
import { classPath, fileName, filterStudents, percentLabel, registerPath, sessionWhen, type ClassStudentRow } from "../src/utils/classReports.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
  console.log(`  ✓ ${message}`);
}

async function run(): Promise<void> {
  console.log("Class reports checks");
  expect(percentLabel(null) === "—", "no lectures held shows a dash, not 0%");
  expect(percentLabel(72.5) === "72.5%", "a percentage is shown as sent");

  const group = "2025-ODD:CSE-DS-3:DE-II/AI/G1:BCDS501";
  const path = classPath(group, "students.csv");
  expect(path === `/api/v1/teachers/classes/${encodeURIComponent(group)}/students.csv`, "the class id is encoded in one path segment");
  expect(!path.slice("/api/v1/teachers/classes/".length).includes("/AI"), "a group's slashes cannot split the path");
  expect(registerPath("c1", "", "") === "/api/v1/teachers/classes/c1/register.csv", "no dates means no query");
  expect(registerPath("c1", "2025-11-01", "") === "/api/v1/teachers/classes/c1/register.csv?from=2025-11-01", "only the dates given are sent");
  expect(fileName("Computer Networks - Section B", "register") === "register_Computer_Networks_-_Section_B.csv", "file names are safe");


  const row = (roll: string, name: string, percentage: number | null): ClassStudentRow => ({
    identity: roll, roll_number: roll, name, email: "", section: "B", de2: "", de3: "", dlda: "",
    present: 0, absent: 0, held: percentage === null ? 0 : 4, percentage, shortage: percentage !== null && percentage < 75,
  });
  const list = [row("2402", "Riya", 50), row("2401", "Aman", 90), row("2403", "Zoya", null)];
  expect(filterStudents(list, "", false, "roll").map((r) => r.roll_number).join() === "2401,2402,2403", "sorted by roll number");
  expect(filterStudents(list, "", false, "percentage").map((r) => r.roll_number).join() === "2402,2401,2403", "lowest % first, none held last");
  expect(filterStudents(list, "riy", false, "roll").length === 1 && filterStudents(list, "2403", false, "roll").length === 1, "search by name or roll number");
  expect(filterStudents(list, "", true, "roll").map((r) => r.roll_number).join() === "2402", "below the threshold only");
  expect(list[0].roll_number === "2402", "filtering does not reorder the loaded list");
  const students = readFileSync(new URL("../src/components/teacher/ClassStudents.tsx", import.meta.url), "utf-8");
  expect(students.includes("api.markRound(") && !/method: "(DELETE|PATCH|PUT)"/.test(students), "corrections go only through the round marks");
  const api = readFileSync(new URL("../src/services/api.ts", import.meta.url), "utf-8");
  expect(api.includes("Authorization: `Bearer ${token}`") && api.includes("downloadFile"), "downloads carry the user's token");
  const flow = readFileSync(new URL("../src/pages/TeacherAttendanceFlow.tsx", import.meta.url), "utf-8");
  expect(!flow.includes(":8000"), "the session CSV no longer uses a hard-coded port");
  expect(flow.includes("<ClassDownloads />"), "teachers see Downloads in Sessions");
  const downloads = readFileSync(new URL("../src/components/teacher/ClassDownloads.tsx", import.meta.url), "utf-8");
  const buttons = [...downloads.matchAll(/<button[\s\S]*?<\/button>/g)].map((m) => m[0]);
  expect(buttons.length === 1 && buttons[0].includes("Download CSV"), "one Download CSV button in Downloads");
  expect(downloads.includes("registerPath(classId, from, to)") && !downloads.includes("students.csv") && !downloads.includes("/export"), "it downloads the register for the dates");
  expect(!students.includes("Download CSV") && students.includes("{EDIT_WINDOW_CLOSED_TEXT}"), "no second download; the window message in My Classes");
  expect(sessionWhen({ date: "2026-10-28", time: "09:10", taken_at: "14:01" }) === "28 Oct 2026, 09:10 · taken 14:01", "slot time and when it was taken");
  expect(sessionWhen({ date: "2026-10-28", time: "09:10", taken_at: "09:12" }) === "28 Oct 2026, 09:10 · taken 09:12" && sessionWhen({ date: "2026-10-28", time: "09:10", taken_at: null }) === "28 Oct 2026, 09:10", "no taken time when not taken");
  expect(readFileSync(new URL("../src/components/teacher/MyClasses.tsx", import.meta.url), "utf-8").includes("<ClassStudents />"), "teachers see their students in My Classes");
  const student = readFileSync(new URL("../src/pages/StudentDashboard.tsx", import.meta.url), "utf-8");
  expect(student.includes("<SubjectAttendance />"), "students see attendance by subject");
}

run().catch((err) => {
  console.error("\n❌ Class reports checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
