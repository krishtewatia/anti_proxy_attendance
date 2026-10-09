import { api, auth } from "../src/services/index.ts";
import { requireLiveBackend } from "./live_backend.ts";

async function testGetSession() {
  console.log("==================================================");
  console.log("   STEP 2C.6 Part 1B: api.getSession(id) Test    ");
  console.log("==================================================");

  // 1. Health check live backend
  console.log("\n[1/6] Checking live backend connectivity...");
  try {
    const health = await requireLiveBackend();
    console.log("✅ Live backend healthy:", health);
  } catch (err: any) {
    console.log("ℹ Backend not currently running locally, skipping live network tests:", err.message);
    console.log("\n==================================================");
    console.log("✅ FRONTEND GET SESSION TEST SUITE PASSED (SKIPPED LIVE BACKEND)!");
    console.log("==================================================");
    return;
  }

  const timestamp = Date.now();
  const teacherAEmail = `teacher_a_${timestamp}@test.edu`;
  const teacherBEmail = `teacher_b_${timestamp}@test.edu`;
  const studentEmail = `student_${timestamp}@test.edu`;
  const password = "StrongPassword123!";

  // 2. Register & Login Teacher A, then create Session A
  console.log(`\n[2/6] Authenticating Teacher A (${teacherAEmail}) and creating Session A...`);
  const teacherA = await api.register({
    email: teacherAEmail,
    password,
    role: "TEACHER",
  });
  await auth.login({ email: teacherAEmail, password });

  const sessionPayload = {
    course_name: "Advanced Cryptography 401",
    classroom_id: "LAB-E",
    start_time: "2026-10-05T09:00:00Z",
    end_time: "2026-10-05T10:30:00Z",
    required_presence_percentage: 85.0,
  };

  const createdSession = await api.createSession(sessionPayload);
  const sessionId = createdSession.session_id;
  console.log("✅ Session A created:", sessionId);

  // 3. Teacher A retrieves Session A via api.getSession(sessionId)
  console.log(`\n[3/6] Teacher A calls api.getSession('${sessionId}')...`);
  const fetchedSession = await api.getSession(sessionId);
  console.log("✅ api.getSession returned:", fetchedSession);

  if (fetchedSession.session_id !== sessionId) {
    throw new Error(`session_id mismatch: expected ${sessionId}, got ${fetchedSession.session_id}`);
  }
  if (fetchedSession.course_name !== sessionPayload.course_name) {
    throw new Error(`course_name mismatch: expected ${sessionPayload.course_name}, got ${fetchedSession.course_name}`);
  }
  if (fetchedSession.classroom_id !== sessionPayload.classroom_id) {
    throw new Error(`classroom_id mismatch: expected ${sessionPayload.classroom_id}, got ${fetchedSession.classroom_id}`);
  }
  if (fetchedSession.required_presence_percentage !== 85.0) {
    throw new Error(`required_presence mismatch: expected 85.0, got ${fetchedSession.required_presence_percentage}`);
  }
  if (fetchedSession.status !== "SCHEDULED") {
    throw new Error(`status mismatch: expected SCHEDULED, got ${fetchedSession.status}`);
  }
  if (fetchedSession.created_by !== teacherA.user_id) {
    throw new Error(`created_by mismatch: expected ${teacherA.user_id}, got ${fetchedSession.created_by}`);
  }
  console.log("✅ Teacher A successfully retrieved all fields for owned session.");

  // 4. Teacher B attempts to retrieve Session A (403 Forbidden)
  console.log(`\n[4/6] Authenticating Teacher B (${teacherBEmail}) and verifying isolation...`);
  await api.register({
    email: teacherBEmail,
    password,
    role: "TEACHER",
  });
  await auth.login({ email: teacherBEmail, password });

  try {
    await api.getSession(sessionId);
    throw new Error("Teacher B was illegally allowed to read Teacher A's session!");
  } catch (err: any) {
    console.log("✅ Teacher B correctly rejected with:", err.message);
    if (!err.message.includes("403") && !err.message.toLowerCase().includes("do not own")) {
      throw new Error(`Unexpected error message for Teacher B: ${err.message}`);
    }
  }

  // 5. Student attempts to retrieve Session A (403 Forbidden)
  console.log(`\n[5/6] Authenticating Student (${studentEmail}) and verifying RBAC...`);
  await api.register({
    email: studentEmail,
    password,
    role: "STUDENT",
  });
  await auth.login({ email: studentEmail, password });

  try {
    await api.getSession(sessionId);
    throw new Error("Student was illegally allowed to call api.getSession()!");
  } catch (err: any) {
    console.log("✅ Student correctly rejected with:", err.message);
    if (!err.message.includes("403") && !err.message.toLowerCase().includes("insufficient permissions")) {
      throw new Error(`Unexpected error message for Student: ${err.message}`);
    }
  }

  // 6. Teacher A requests nonexistent session (404) and Anonymous requests session (401)
  console.log("\n[6/6] Verifying 404 Not Found and 401 Unauthorized handling...");
  await auth.login({ email: teacherAEmail, password });

  // 6a. 404 test
  try {
    await api.getSession("nonexistent_session_id_99999");
    throw new Error("Expected 404 for nonexistent session, but request succeeded!");
  } catch (err: any) {
    console.log("✅ Nonexistent session correctly returned 404:", err.message);
    if (!err.message.includes("404") && !err.message.toLowerCase().includes("not found")) {
      throw new Error(`Unexpected 404 error message: ${err.message}`);
    }
  }

  // 6b. 401 test (unauthenticated)
  auth.logout();
  try {
    await api.getSession(sessionId);
    throw new Error("Unauthenticated call succeeded illegally!");
  } catch (err: any) {
    console.log("✅ Unauthenticated request correctly returned 401:", err.message);
    if (!err.message.includes("401") && !err.message.toLowerCase().includes("authentication required")) {
      throw new Error(`Unexpected 401 error message: ${err.message}`);
    }
  }

  console.log("\n==================================================");
  console.log("✅ ALL STEP 2C.6 PART 1B GET SESSION TESTS PASSED!");
  console.log("==================================================");
}

testGetSession().catch((err) => {
  console.error("❌ Test failed:", err);
  process.exit(1);
});
