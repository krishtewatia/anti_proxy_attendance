// A session that was never taken is "Not taken" everywhere: never an absence,
// never part of a percentage, and never the cause of a shortage alert.

import { readFileSync } from "node:fs";
import { historyStatusBadge, isAttendanceShortage, nothingTaken } from "../src/utils/attendanceStatus.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

async function run() {
  console.log("==================================================");
  console.log("   Untaken Sessions Are Not Counted               ");
  console.log("==================================================");

  console.log("\n[1/4] No shortage alert when nothing was taken...");
  expect(!isAttendanceShortage(null, 0), "no percentage and no sessions is not a shortage");
  expect(!isAttendanceShortage(0, 0), "0% of nothing is not a shortage");
  expect(!isAttendanceShortage(undefined, 3), "a missing percentage is not a shortage");
  expect(nothingTaken(null, 0) && nothingTaken(0, 0) && !nothingTaken(0, 2), "nothing taken means no percentage to show");

  console.log("[2/4] The alert still works for sessions that were taken...");
  expect(isAttendanceShortage(74.9, 8), "below 75% of taken sessions is a shortage");
  expect(isAttendanceShortage(0, 2), "absent from every taken session is a shortage");
  expect(!isAttendanceShortage(75, 4), "exactly 75% meets the minimum");
  expect(!isAttendanceShortage(100, 1), "100% is not a shortage");

  console.log("[3/4] A history row that was never taken is not shown as absent...");
  const notTaken = historyStatusBadge("NOT_TAKEN");
  expect(notTaken.label === "Not taken", `unexpected label: ${notTaken.label}`);
  expect(notTaken.className !== "absent" && notTaken.className !== "present", "Not taken must be neither red nor green");
  expect(historyStatusBadge("ABSENT").className === "absent" && historyStatusBadge("PRESENT").className === "present", "real marks keep their colours");

  console.log("[4/4] Every screen that lists attendance uses the flag...");
  const student = readFileSync("src/pages/StudentDashboard.tsx", "utf-8");
  expect(student.includes("isAttendanceShortage(") && student.includes("historyStatusBadge("), "the student dashboard must use the shared rules");
  expect(!/overallPct >= 75/.test(student), "the student dashboard must not decide a shortage from the bare percentage");
  const register = readFileSync("src/components/session/SessionAttendance.tsx", "utf-8");
  expect(register.includes("data.was_taken") && register.includes('"Not taken"'), "the session register must show Not taken");
  const teacher = readFileSync("src/pages/TeacherAttendanceFlow.tsx", "utf-8");
  expect(teacher.includes("attData.was_taken === false") && teacher.includes('"Not taken"'), "the teacher's past-session view must show Not taken");
  const reports = readFileSync("src/components/admin/ReportsTab.tsx", "utf-8");
  expect(reports.includes("sessions_not_taken"), "the report must say how many sessions were not taken");

  console.log("\n✅ All untaken-session checks passed.");
}

run().catch((err) => {
  console.error("\n❌ Untaken-session checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
