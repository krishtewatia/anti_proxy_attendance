// Reports and downloads: the percentage label, download paths for class ids
// that contain ":" and "/", safe file names, and the wiring of the new views.

import { readFileSync } from "node:fs";
import { classPath, fileName, percentLabel, registerPath } from "../src/utils/classReports.ts";

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

  const api = readFileSync(new URL("../src/services/api.ts", import.meta.url), "utf-8");
  expect(api.includes("Authorization: `Bearer ${token}`") && api.includes("downloadFile"), "downloads carry the user's token");
  const flow = readFileSync(new URL("../src/pages/TeacherAttendanceFlow.tsx", import.meta.url), "utf-8");
  expect(!flow.includes(":8000"), "the session CSV no longer uses a hard-coded port");
  expect(flow.includes("<ClassDownloads />"), "teachers see Downloads in Sessions");
  const student = readFileSync(new URL("../src/pages/StudentDashboard.tsx", import.meta.url), "utf-8");
  expect(student.includes("<SubjectAttendance />"), "students see attendance by subject");
}

run().catch((err) => {
  console.error("\n❌ Class reports checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
