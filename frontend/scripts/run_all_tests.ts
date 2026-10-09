import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

interface TestSuite {
  name: string;
  file: string;
  category: "Unit" | "Contract" | "E2E Integration";
}

const testSuites: TestSuite[] = [
  { name: "Auth Client State & Storage", file: "test_auth_client.ts", category: "Unit" },
  { name: "Protected Routing & RBAC Guards", file: "test_routing.ts", category: "Unit" },
  { name: "Attendance Formatting & Calculation Helpers", file: "test_session_attendance.ts", category: "Unit" },
  { name: "Camera Overlay: Recognized / Unknown / Spoof", file: "test_face_overlay.ts", category: "Unit" },
  { name: "Protected Images: Token, Object URLs, Cleanup", file: "test_authenticated_image.ts", category: "Unit" },
  { name: "Registration Approval: Admin Screen Rules", file: "test_approvals.ts", category: "Unit" },
  { name: "Create Session Form Validation & Lifecycle", file: "test_create_session.ts", category: "Unit" },
  { name: "Attendance Correction Validation & Audit History", file: "test_attendance_correction.ts", category: "Unit" },
  { name: "Audit Trail Contracts & Verification", file: "test_audit_logs.ts", category: "Contract" },
  { name: "Live Session Snapshot Contracts", file: "test_live_session_feed.ts", category: "Contract" },
  { name: "Get Session Details & Ownership", file: "test_get_session.ts", category: "Contract" },
  { name: "Session Roster Management", file: "test_session_roster.ts", category: "Contract" },
  { name: "Student Profile Binding & Verification", file: "test_student_profile.ts", category: "Contract" },
  { name: "API Client Integration & Error Handling", file: "test_api_integration.ts", category: "E2E Integration" },
  { name: "Live Multi-User Auth Lifecycle", file: "test_live_auth_flow.ts", category: "E2E Integration" },
];

console.log("================================================================================");
console.log("             RUNNING FRONTEND TEST CONSOLIDATION SUITE (15 MODULES)             ");
console.log("================================================================================");

let passed = 0;
let failed = 0;
const results: Array<{ name: string; category: string; passed: boolean; durationMs: number }> = [];

const startTimeTotal = Date.now();

for (const suite of testSuites) {
  const filePath = resolve("scripts", suite.file);
  const start = Date.now();

  process.stdout.write(`\n▶ [${suite.category}] ${suite.name} (${suite.file})...\n`);

  const result = spawnSync("node", ["--experimental-strip-types", filePath], {
    stdio: "inherit",
    env: process.env,
  });

  const durationMs = Date.now() - start;

  if (result.status === 0) {
    passed++;
    results.push({ name: suite.name, category: suite.category, passed: true, durationMs });
  } else {
    failed++;
    results.push({ name: suite.name, category: suite.category, passed: false, durationMs });
  }
}

const totalTimeMs = Date.now() - startTimeTotal;

console.log("\n================================================================================");
console.log("                       FRONTEND TEST EXECUTION SUMMARY                          ");
console.log("================================================================================");

for (const res of results) {
  const icon = res.passed ? "✅ PASS" : "❌ FAIL";
  console.log(`  ${icon} [${res.category.padEnd(15)}] ${res.name.padEnd(45)} (${res.durationMs}ms)`);
}

console.log("--------------------------------------------------------------------------------");
console.log(`Total Suites: ${testSuites.length} | Passed: ${passed} | Failed: ${failed} | Duration: ${(totalTimeMs / 1000).toFixed(2)}s`);
console.log("================================================================================");

if (failed > 0) {
  console.error(`❌ ${failed} test suite(s) failed.`);
  process.exit(1);
} else {
  console.log("🎉 ALL FRONTEND TEST SUITES COMPLETED SUCCESSFULLY!");
  process.exit(0);
}
