// Regression checks for the session page and list fixes:
// one date format, "Not taken" instead of a red 0%, no classroom in the
// interface, no leftover dark stylesheet, and the unreachable pages stay gone.

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { formatDate, formatDateTime, formatSessionTurnout, formatTime } from "../src/utils/dates.ts";
import { paginate } from "../src/utils/sessions.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

function sourceFiles(dir: string, pattern: RegExp, found: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      sourceFiles(path, pattern, found);
    } else if (pattern.test(name)) {
      found.push(path);
    }
  }
  return found;
}

async function run() {
  console.log("==================================================");
  console.log("   Session Page And List Fixes                    ");
  console.log("==================================================");

  console.log("\n[1/6] Dates read \"7 Oct 2026\", never 7/10/2026...");
  // Local-time constructor, so the check does not depend on the machine's time zone.
  const seventh = new Date(2026, 9, 7, 6, 50);
  expect(formatDate(seventh) === "7 Oct 2026", `unexpected date: ${formatDate(seventh)}`);
  expect(formatTime(seventh) === "6:50 am", `unexpected time: ${formatTime(seventh)}`);
  expect(formatTime(new Date(2026, 9, 7, 18, 5)) === "6:05 pm", "afternoon times must use pm");
  expect(formatDateTime(seventh) === "7 Oct 2026, 6:50 am", `unexpected date and time: ${formatDateTime(seventh)}`);
  expect(formatDate(null) === "—" && formatDate("not a date") === "—" && formatTime(undefined) === "—", "a missing date must be a dash");
  for (const file of sourceFiles("src", /\.tsx?$/)) {
    expect(!/toLocale(Date|Time)?String\(/.test(readFileSync(file, "utf-8")), `${file} formats a date its own way; use utils/dates.ts`);
  }

  console.log("[2/6] A session that was never taken has no turnout...");
  expect(formatSessionTurnout({ was_taken: false, attendance_percentage: 0 }) === "Not taken", "never taken must read Not taken");
  expect(formatSessionTurnout({ was_taken: true, attendance_percentage: 0 }) === "0%", "taken with nobody present is a real 0%");
  expect(formatSessionTurnout({ was_taken: true, attendance_percentage: 33.3 }) === "33.3%", "a turnout keeps one decimal");
  expect(formatSessionTurnout({ attendance_percentage: 100 }) === "100%", "older data without the flag shows its turnout");
  expect(formatSessionTurnout({ was_taken: true, attendance_percentage: null }) === "—", "no figure must be a dash");

  console.log("[3/6] No classroom is shown or asked for...");
  for (const file of sourceFiles("src", /\.tsx$/)) {
    const text = readFileSync(file, "utf-8");
    expect(!/ROOM_\d+/.test(text), `${file} still mentions a room code`);
    expect(!/classroom/i.test(text), `${file} still shows or sends a classroom`);
  }

  console.log("[4/6] The session page uses the app's styles, not its own dark stylesheet...");
  expect(!existsSync("src/pages/session-details.css"), "session-details.css must stay removed");
  expect(!existsSync("src/components/session/session-attendance.css"), "session-attendance.css must stay removed");
  for (const file of ["src/components/audit/audit-logs.css", "src/components/attendance/attendance-correction-modal.css"]) {
    const css = readFileSync(file, "utf-8");
    const light = css.match(/(^|[;{\s])color:\s*(#f9fafb|#ffffff|#fff|#f8fafc|#e2e8f0|#94a3b8|#a5b4fc|#34d399|#fda4af|#c084fc)\b[^;]*;/gi) || [];
    // White text is right only on a solid coloured button.
    const stray = light.filter((decl) => !/#fff(fff)?\b/i.test(decl));
    expect(stray.length === 0, `${file} still has light-on-dark text colours: ${stray.slice(0, 3).join(" ")}`);
    expect(!/rgba\(\s*255\s*,\s*255\s*,\s*255\s*,\s*0?\.0\d\s*\)/.test(css), `${file} still has near-transparent white panels from the dark theme`);
  }
  const base = readFileSync("src/index.css", "utf-8");
  for (const name of ["--primary-gradient", "--primary-glow", "--transition-fast", "--radius-xl"]) {
    expect(new RegExp(`\\n\\s*${name}:`).test(base), `${name} must be defined: the correction form's Save button depends on it`);
  }
  const page = readFileSync("src/pages/SessionDetails.tsx", "utf-8") + readFileSync("src/components/session/SessionAttendance.tsx", "utf-8");
  expect(page.includes("record.student_name") && page.includes("record.roll_number"), "the register must show names and roll numbers");
  expect(!/presence_(duration|percentage)|required_presence/.test(page), "doorway-only presence fields must not come back to the session page");

  console.log("[5/6] The session page highlights Sessions in the menu...");
  const app = readFileSync("src/App.tsx", "utf-8");
  const sessionRoute = app.slice(app.indexOf("if (sessionDetailsMatch)"), app.indexOf("// Route 2"));
  expect(sessionRoute.includes('activeNavId="sessions"'), "the session page must mark Sessions as the current menu item");

  console.log("[6/6] Long lists are paginated and unreachable pages stay deleted...");
  expect(paginate(Array.from({ length: 46 }, (_, i) => i), 4, 15).items.length === 1, "46 rows are 4 pages of 15");
  for (const file of ["src/pages/TeacherAttendanceFlow.tsx", "src/pages/StudentDashboard.tsx", "src/components/admin/SessionsTab.tsx"]) {
    expect(readFileSync(file, "utf-8").includes("<Pagination"), `${file} must paginate its list`);
  }
  for (const gone of [
    "src/pages/TeacherDashboard.tsx",
    "src/pages/AdminDashboardPlaceholder.tsx",
    "src/pages/StudentDashboardPlaceholder.tsx",
    "src/components/session/CreateSessionModal.tsx",
    "src/components/session/LiveAttendanceFeed.tsx",
    "src/components/session/SessionRoster.tsx",
  ]) {
    expect(!existsSync(gone), `${gone} was unreachable and must stay deleted`);
  }

  console.log("\n✅ All session page and list checks passed.");
}

run().catch((err) => {
  console.error("\n❌ Session page and list checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
