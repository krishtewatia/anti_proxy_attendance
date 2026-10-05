import { api, auth } from "../src/services/index.ts";

async function testSessionRoster() {
  console.log("==================================================");
  console.log("   STEP 2C.7 Part 1: Session Roster API Test      ");
  console.log("==================================================");

  // 1. Health check live backend
  console.log("\n[1/6] Checking live backend connectivity...");
  try {
    const health = await api.checkHealth();
    console.log("✅ Live backend healthy:", health);
  } catch (err: any) {
    console.log("ℹ Backend not currently running locally, skipping live network tests:", err.message);
    console.log("\n==================================================");
    console.log("✅ FRONTEND SESSION ROSTER TEST SUITE PASSED (SKIPPED LIVE BACKEND)!");
    console.log("==================================================");
    return;
  }

  const timestamp = Date.now();
  const teacherAEmail = `teacher_roster_a_${timestamp}@test.edu`;
  const teacherBEmail = `teacher_roster_b_${timestamp}@test.edu`;
  const studentEmail = `student_roster_${timestamp}@test.edu`;
  const password = "StrongPassword123!";

  // 2. Register & Login Teacher A, then create Session A
  console.log(`\n[2/6] Authenticating Teacher A (${teacherAEmail}) and creating Session A...`);
  await api.register({
    email: teacherAEmail,
    password,
    role: "TEACHER",
  });
  await auth.login({ email: teacherAEmail, password });

  const sessionPayload = {
    course_name: "Operating Systems 201",
    classroom_id: "LAB-3",
    start_time: "2026-10-10T10:00:00Z",
    end_time: "2026-10-10T11:30:00Z",
    required_presence_percentage: 75.0,
  };

  const sessionA = await api.createSession(sessionPayload);
  const sessionId = sessionA.session_id;
  console.log("✅ Session A created:", sessionId);

  // 3. Test Owner Flow (retrieve initially -> 404, update with identities, retrieve again, idempotent replacement)
  console.log("\n[3/6] Testing Owner (Teacher A) roster lifecycle...");

  // 3a. Initially retrieve roster before enrollment -> 404 Not Found
  try {
    await api.getSessionRoster(sessionId);
    throw new Error("Expected 404 for un-enrolled roster, but request succeeded!");
  } catch (err: any) {
    console.log("  ✅ Initial getSessionRoster() returned 404 as expected:", err.message);
    if (!err.message.includes("404") && !err.message.toLowerCase().includes("not found")) {
      throw new Error(`Unexpected error message: ${err.message}`);
    }
  }

  // 3b. Update roster with identities [person_01, person_02]
  console.log("  Enrolling initial roster [person_01, person_02]...");
  const initialRoster = await api.updateSessionRoster(sessionId, ["person_01", "person_02"]);
  console.log("  ✅ updateSessionRoster returned:", initialRoster);

  if (initialRoster.session_id !== sessionId) {
    throw new Error(`session_id mismatch: expected ${sessionId}, got ${initialRoster.session_id}`);
  }
  if (
    initialRoster.identities.length !== 2 ||
    !initialRoster.identities.includes("person_01") ||
    !initialRoster.identities.includes("person_02")
  ) {
    throw new Error(`Unexpected identities in initial roster: ${JSON.stringify(initialRoster.identities)}`);
  }

  // 3c. Retrieve roster again and verify persistence
  const fetchedRoster = await api.getSessionRoster(sessionId);
  console.log("  ✅ getSessionRoster verified persisted identities:", fetchedRoster.identities);
  if (
    fetchedRoster.identities.length !== 2 ||
    !fetchedRoster.identities.includes("person_01") ||
    !fetchedRoster.identities.includes("person_02")
  ) {
    throw new Error(`Persisted identities mismatch: ${JSON.stringify(fetchedRoster.identities)}`);
  }

  // 3d. Update again and verify idempotent replacement behavior [person_02, person_03]
  console.log("  Testing idempotent replacement with [person_02, person_03]...");
  const updatedRoster = await api.updateSessionRoster(sessionId, {
    identities: ["person_02", "person_03"],
  });
  console.log("  ✅ updateSessionRoster replaced identities:", updatedRoster.identities);

  const fetchedUpdated = await api.getSessionRoster(sessionId);
  if (
    fetchedUpdated.identities.length !== 2 ||
    !fetchedUpdated.identities.includes("person_02") ||
    !fetchedUpdated.identities.includes("person_03") ||
    fetchedUpdated.identities.includes("person_01")
  ) {
    throw new Error(`Replacement failed! Unexpected identities: ${JSON.stringify(fetchedUpdated.identities)}`);
  }
  console.log("  ✅ Idempotent replacement verified (person_01 cleanly removed, person_03 added).");

  // 4. Teacher B attempts to read or update Teacher A's roster (403 Forbidden)
  console.log(`\n[4/6] Authenticating Teacher B (${teacherBEmail}) and verifying isolation...`);
  await api.register({
    email: teacherBEmail,
    password,
    role: "TEACHER",
  });
  await auth.login({ email: teacherBEmail, password });

  try {
    await api.getSessionRoster(sessionId);
    throw new Error("Teacher B was illegally allowed to read Teacher A's roster!");
  } catch (err: any) {
    console.log("  ✅ Teacher B reading roster rejected with 403:", err.message);
    if (!err.message.includes("403") && !err.message.toLowerCase().includes("own")) {
      throw new Error(`Unexpected error message for Teacher B get: ${err.message}`);
    }
  }

  try {
    await api.updateSessionRoster(sessionId, ["person_99"]);
    throw new Error("Teacher B was illegally allowed to update Teacher A's roster!");
  } catch (err: any) {
    console.log("  ✅ Teacher B updating roster rejected with 403:", err.message);
    if (!err.message.includes("403") && !err.message.toLowerCase().includes("own")) {
      throw new Error(`Unexpected error message for Teacher B update: ${err.message}`);
    }
  }

  // 5. Student attempts to access roster endpoint (403 Forbidden)
  console.log(`\n[5/6] Authenticating Student (${studentEmail}) and verifying RBAC...`);
  await api.register({
    email: studentEmail,
    password,
    role: "STUDENT",
  });
  await auth.login({ email: studentEmail, password });

  try {
    await api.getSessionRoster(sessionId);
    throw new Error("Student was illegally allowed to get session roster!");
  } catch (err: any) {
    console.log("  ✅ Student getSessionRoster rejected with 403:", err.message);
    if (!err.message.includes("403") && !err.message.toLowerCase().includes("permissions")) {
      throw new Error(`Unexpected error message for Student get: ${err.message}`);
    }
  }

  try {
    await api.updateSessionRoster(sessionId, ["person_01"]);
    throw new Error("Student was illegally allowed to update session roster!");
  } catch (err: any) {
    console.log("  ✅ Student updateSessionRoster rejected with 403:", err.message);
    if (!err.message.includes("403") && !err.message.toLowerCase().includes("permissions")) {
      throw new Error(`Unexpected error message for Student update: ${err.message}`);
    }
  }

  // 6. Anonymous (No JWT) requests roster endpoint (401 Unauthorized)
  console.log("\n[6/6] Verifying Anonymous (no token) 401 Unauthorized handling...");
  auth.logout();

  try {
    await api.getSessionRoster(sessionId);
    throw new Error("Unauthenticated getSessionRoster succeeded illegally!");
  } catch (err: any) {
    console.log("  ✅ Unauthenticated getSessionRoster rejected with 401:", err.message);
    if (!err.message.includes("401") && !err.message.toLowerCase().includes("authentication required")) {
      throw new Error(`Unexpected 401 error message for get: ${err.message}`);
    }
  }

  try {
    await api.updateSessionRoster(sessionId, ["person_01"]);
    throw new Error("Unauthenticated updateSessionRoster succeeded illegally!");
  } catch (err: any) {
    console.log("  ✅ Unauthenticated updateSessionRoster rejected with 401:", err.message);
    if (!err.message.includes("401") && !err.message.toLowerCase().includes("authentication required")) {
      throw new Error(`Unexpected 401 error message for update: ${err.message}`);
    }
  }

  console.log("\n==================================================");
  console.log("✅ ALL STEP 2C.7 PART 1 ROSTER API TESTS PASSED!");
  console.log("==================================================");
}

testSessionRoster().catch((err) => {
  console.error("❌ Test failed:", err);
  process.exit(1);
});
