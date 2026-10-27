// Students and teachers kept on file as CSV: the check summary, the file name,
// and the wiring on both admin pages.

import { readFileSync } from "node:fs";
import { csvCheckSummary, peopleCsvName } from "../src/utils/registry.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
  console.log(`  ✓ ${message}`);
}

async function run(): Promise<void> {
  console.log("People CSV checks");
  const clean = { to_create: 2, existing: 1, errors: [], rows: [] };
  expect(csvCheckSummary(clean, "students") === "2 students to add · 1 already here (kept as they are)", "a clean file in one line");
  const bad = { to_create: 1, existing: 0, errors: [{ line: 3, errors: ["email is not an email address"] }], rows: [] };
  expect(csvCheckSummary(bad, "teachers") === "1 teacher to add · 0 already here (kept as they are) · 1 row with errors", "errors are counted");
  expect(peopleCsvName("teachers", new Date("2026-10-27T10:00:00Z")) === "teachers_20261027_CONFIDENTIAL.csv", "the file name is dated and marked confidential");

  const panel = readFileSync(new URL("../src/components/admin/PeopleCsvPanel.tsx", import.meta.url), "utf-8");
  expect(panel.includes("checkPeopleCsv(kind, picked)") && panel.includes("checkPeopleCsv(kind, file, true)"), "a file is checked before it is loaded");
  expect(panel.includes("check.errors.length > 0 || check.to_create === 0"), "a file with errors cannot be loaded");
  for (const page of ["StudentRegistryTab", "TeacherRegistryTab"]) {
    const text = readFileSync(new URL(`../src/components/admin/${page}.tsx`, import.meta.url), "utf-8");
    expect(text.includes("<PeopleCsvPanel"), `${page} has Download and Import CSV`);
  }
}

run().catch((err) => {
  console.error("\n❌ People CSV checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
