import { api, auth } from "../src/services/index.ts";

async function testLiveAuthFlow() {
  console.log("==================================================");
  console.log("   STEP 2C.4 Part 2: Frontend Session API Test    ");
  console.log("==================================================");

  // 1. Health check live backend
  console.log("\n[1/9] Testing live backend connectivity...");
  const health = await api.checkHealth();
  console.log("✅ Live backend healthy:", health);

  // Unique timestamped emails to prevent conflict with repeated runs
  const timestamp = Date.now();
  const teacherAEmail = `teacher_a_${timestamp}@test.edu`;
  const teacherBEmail = `teacher_b_${timestamp}@test.edu`;
  const studentEmail = `student_${timestamp}@test.edu`;
  const password = "StrongPassword123!";

  // 2. Register & Login Teacher A
  console.log(`\n[2/9] Registering & logging in Teacher A: ${teacherAEmail}...`);
  const registeredTeacherA = await api.register({
    email: teacherAEmail,
    password,
    role: "TEACHER",
  });
  await auth.login({ email: teacherAEmail, password });
  console.log("✅ Teacher A logged in:", registeredTeacherA.user_id);

  // 3. Teacher A creates a session
  console.log("\n[3/9] Teacher A creates a session...");
  const sessionA = await api.createSession({
    course_name: "Cybersecurity 401",
    classroom_id: "LAB-202",
    start_time: "2026-09-30T14:00:00Z",
    end_time: "2026-09-30T15:00:00Z",
    required_presence_percentage: 80.0,
  });
  console.log("✅ Session A created:", sessionA.session_id, "Owner:", sessionA.created_by);

  // 4. Test api.getSessions() for Teacher A
  console.log("\n[4/9] Testing api.getSessions() for Teacher A...");
  const teacherASessions = await api.getSessions();
  console.log(`✅ Teacher A received ${teacherASessions.length} sessions.`);
  if (!teacherASessions.some((s) => s.session_id === sessionA.session_id)) {
    throw new Error("Teacher A sessions list missing sessionA");
  }
  if (!teacherASessions.every((s) => s.created_by === registeredTeacherA.user_id)) {
    throw new Error("Teacher A received a session owned by someone else!");
  }

  // 5. Register & Login Teacher B (Isolation check)
  console.log(`\n[5/9] Registering & logging in Teacher B: ${teacherBEmail}...`);
  const registeredTeacherB = await api.register({
    email: teacherBEmail,
    password,
    role: "TEACHER",
  });
  await auth.login({ email: teacherBEmail, password });

  // 6. Teacher B calls api.getSessions() -> Must be empty
  console.log("\n[6/9] Verifying Teacher B cannot see Teacher A's sessions via api.getSessions()...");
  const teacherBSessionsEmpty = await api.getSessions();
  if (teacherBSessionsEmpty.some((s) => s.session_id === sessionA.session_id)) {
    throw new Error("LEAK: Teacher B was able to view Teacher A's session!");
  }
  console.log("✅ Teacher B sees 0 sessions initially (correctly isolated).");

  // 7. Teacher B creates session B and checks list
  console.log("\n[7/9] Teacher B creates Session B and queries api.getSessions()...");
  const sessionB = await api.createSession({
    course_name: "Algorithms 101",
    classroom_id: "AUD-1",
    start_time: "2026-09-30T16:00:00Z",
    end_time: "2026-09-30T17:00:00Z",
  });
  const teacherBSessions = await api.getSessions();
  if (!teacherBSessions.some((s) => s.session_id === sessionB.session_id)) {
    throw new Error("Teacher B missing sessionB in their list");
  }
  if (teacherBSessions.some((s) => s.session_id === sessionA.session_id)) {
    throw new Error("LEAK: Teacher B list includes session A!");
  }
  console.log("✅ Teacher B sees only Session B.");

  // 8. Register & Login Student
  console.log(`\n[8/9] Logging in as student: ${studentEmail}...`);
  await api.register({
    email: studentEmail,
    password,
    role: "STUDENT",
  });
  await auth.login({ email: studentEmail, password });

  // 9. Verify Student blocked from api.getSessions() (RBAC 403)
  console.log("\n[9/9] Verifying Student is blocked from api.getSessions() (403)...");
  try {
    await api.getSessions();
    throw new Error("Student was illegally allowed to query getSessions()!");
  } catch (err: any) {
    console.log("✅ Student getSessions() correctly rejected by backend RBAC:", err.message);
    if (!err.message.includes("403") && !err.message.toLowerCase().includes("insufficient permissions")) {
      throw new Error(`Unexpected error message: ${err.message}`);
    }
  }

  // Clear auth on exit
  auth.logout();
  console.log("\n==================================================");
  console.log("✅ ALL STEP 2C.4 PART 2 GET SESSIONS TESTS PASSED!");
  console.log("==================================================");
}

testLiveAuthFlow().catch((err) => {
  console.error("❌ Live test failed:", err);
  process.exit(1);
});
