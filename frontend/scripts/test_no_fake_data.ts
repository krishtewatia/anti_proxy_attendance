// The interface shows counted values or an honest empty state, never a
// placeholder that looks like data. These checks keep the made-up values that
// were removed from coming back.

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { formatCount, formatTurnout } from "../src/utils/reports.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

function sourceFiles(dir: string, found: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      sourceFiles(path, found);
    } else if (/\.tsx$/.test(name)) {
      found.push(path);
    }
  }
  return found;
}

// Each pattern is something that was shown as if it were real.
const MADE_UP: Array<[RegExp, string]> = [
  [/\|\|\s*(4|8)\b/, "a number used when the real count is missing"],
  [/:\s*4\)/, "a number used when the real count is missing"],
  [/84\.5%/, "a hard-coded turnout percentage"],
  [/class_code\s*\|\|\s*"[A-Z]+-[A-Z]"/, "a class shown when the session has none"],
  [/useState<string\[\]>\(\[\s*"/, "a list that starts with invented entries"],
  [/useState<string>\("(DS-B|Machine Learning)"\)/, "an invented default selection"],
  [/Department of Data Science/, "a hard-coded department"],
  [/>T001</, "a hard-coded teacher ID"],
  [/\d+ Students Registered/, "a hard-coded student count"],
  [/Academic (Session|Year) 20\d\d/, "a hard-coded academic year"],
  [/UGC|AICTE/, "a compliance claim nothing checks"],
  [/FPS: \d+|DOOR SENSOR|CAM_ROOM_101_DOOR/, "camera telemetry that is not measured"],
  [/student_alice|person_01/, "invented students"],
  [/Active Faculty|System Status/, "a status badge nothing computes"],
];

async function run() {
  console.log("==================================================");
  console.log("   No Made-Up Data In The Interface               ");
  console.log("==================================================");

  console.log("\n[1/2] A missing figure is shown as a dash, not as a number...");
  expect(formatTurnout(null) === "—" && formatTurnout(undefined) === "—", "no turnout must be a dash");
  expect(formatTurnout(Number.NaN) === "—", "an unusable turnout must be a dash");
  expect(formatTurnout(60) === "60%" && formatTurnout(84.5) === "84.5%" && formatTurnout(0) === "0%", "a real turnout must be shown, including zero");
  expect(formatCount(null) === "—" && formatCount(undefined) === "—", "a missing count must be a dash");
  expect(formatCount(0) === "0" && formatCount(12) === "12", "a real count must be shown, including zero");

  console.log("[2/2] No screen contains the made-up values that were removed...");
  const files = sourceFiles("src");
  expect(files.length > 20, "the source files were not found");
  for (const file of files) {
    const lines = readFileSync(file, "utf-8").split("\n");
    lines.forEach((line, index) => {
      for (const [pattern, what] of MADE_UP) {
        expect(!pattern.test(line), `${file}:${index + 1} has ${what}: ${line.trim().slice(0, 80)}`);
      }
    });
  }

  console.log("\n✅ No made-up data found.");
}

run().catch((err) => {
  console.error("\n❌ Made-up data check failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
