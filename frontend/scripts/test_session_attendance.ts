import {
  formatPresenceDuration,
  formatPresencePercentage,
} from "../src/components/session/attendance-helpers.ts";
import { api, auth } from "../src/services/index.ts";

function testFormattingHelpers() {
  console.log("--------------------------------------------------");
  console.log("1. Testing Attendance Formatting Helpers");
  console.log("--------------------------------------------------");

  // Duration formatting tests
  const d3000 = formatPresenceDuration(3000);
  console.log(`3000s duration: expected '50 min', got '${d3000}'`);
  if (d3000 !== "50 min") throw new Error(`Duration mismatch: ${d3000}`);

  const d2700 = formatPresenceDuration(2700);
  console.log(`2700s duration: expected '45 min', got '${d2700}'`);
  if (d2700 !== "45 min") throw new Error(`Duration mismatch: ${d2700}`);

  const d0 = formatPresenceDuration(0);
  console.log(`0s duration: expected '0 min', got '${d0}'`);
  if (d0 !== "0 min") throw new Error(`Duration mismatch: ${d0}`);

  const dSubMinute = formatPresenceDuration(30);
  console.log(`30s duration: expected '< 1 min', got '${dSubMinute}'`);
  if (dSubMinute !== "< 1 min") throw new Error(`Duration mismatch: ${dSubMinute}`);

  const dHour = formatPresenceDuration(3600);
  console.log(`3600s duration: expected '1h', got '${dHour}'`);
  if (dHour !== "1h") throw new Error(`Duration mismatch: ${dHour}`);

  // Percentage formatting tests
  const p83 = formatPresencePercentage(83.33333);
  console.log(`83.33333% percentage: expected '83.33%', got '${p83}'`);
  if (p83 !== "83.33%") throw new Error(`Percentage mismatch: ${p83}`);

  const p75 = formatPresencePercentage(75.0);
  console.log(`75.0% percentage: expected '75.00%', got '${p75}'`);
  if (p75 !== "75.00%") throw new Error(`Percentage mismatch: ${p75}`);

  const p0 = formatPresencePercentage(0);
  console.log(`0% percentage: expected '0%', got '${p0}'`);
  if (p0 !== "0%") throw new Error(`Percentage mismatch: ${p0}`);

  console.log("✅ All formatting helper unit tests passed successfully!\n");
}

async function testLiveAttendanceApi() {
  console.log("--------------------------------------------------");
  console.log("2. Testing Live api.getAttendance Integration");
  console.log("--------------------------------------------------");

  try {
    const health = await api.checkHealth();
    console.log("Live backend healthy:", health);
  } catch (err: any) {
    console.log("ℹ Backend not currently running locally, skipping live network test:", err.message);
    return;
  }

  const timestamp = Date.now();
  const teacherEmail = `teacher_att_${timestamp}@test.edu`;
  const password = "StrongPassword123!";

  console.log(`Registering and logging in teacher: ${teacherEmail}...`);
  await api.register({
    email: teacherEmail,
    password,
    role: "TEACHER",
  });
  await auth.login({ email: teacherEmail, password });

  // Create session
  console.log("Creating test session...");
  const session = await api.createSession({
    course_name: "CV Attendance 101",
    classroom_id: "ROOM_A",
    start_time: "2026-10-20T10:00:00Z",
    end_time: "2026-10-20T11:00:00Z",
    required_presence_percentage: 70.0,
  });
  console.log("Created session:", session.session_id);

  // Enroll roster
  console.log("Enrolling roster: person_01, person_02, person_04...");
  await api.updateSessionRoster(session.session_id, [
    "person_01",
    "person_02",
    "person_04",
  ]);

  // Check initial attendance before finalization (empty records)
  console.log("Fetching attendance before session finalization...");
  const initialAtt = await api.getAttendance(session.session_id);
  console.log("Initial attendance records:", initialAtt);
  if (!Array.isArray(initialAtt.records) || initialAtt.records.length !== 0) {
    throw new Error(`Expected 0 attendance records before finalization, got: ${initialAtt.records.length}`);
  }
  console.log("✅ Empty attendance before finalization verified!");

  // Finalize session
  console.log("Finalizing session...");
  const finalized = await api.finalizeSession(session.session_id);
  console.log(`Session finalized. Records generated: ${finalized.records.length}`);

  // Fetch attendance after finalization
  console.log("Fetching attendance after finalization via api.getAttendance()...");
  const finalizedAtt = await api.getAttendance(session.session_id);
  console.log("Attendance records:", finalizedAtt.records);

  if (finalizedAtt.records.length !== 3) {
    throw new Error(`Expected 3 attendance records, got ${finalizedAtt.records.length}`);
  }

  // All 3 students should be ABSENT since no events occurred in this quick test
  for (const rec of finalizedAtt.records) {
    console.log(`  Student: ${rec.identity}, Duration: ${formatPresenceDuration(rec.presence_duration_seconds)}, %: ${formatPresencePercentage(rec.presence_percentage)}, Status: ${rec.status}`);
  }

  console.log("✅ api.getAttendance() integration verified successfully!");
}

async function run() {
  testFormattingHelpers();
  await testLiveAttendanceApi();
}

run().catch((err) => {
  console.error("❌ Attendance test failed:", err);
  process.exit(1);
});
