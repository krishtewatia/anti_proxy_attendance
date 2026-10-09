import { validateSessionForm } from "../src/components/session/validation.ts";
import { api, auth } from "../src/services/index.ts";
import { requireLiveBackend } from "./live_backend.ts";

async function testCreateSession() {
  console.log("==================================================");
  console.log("   STEP 2C.5: Create Session & Validation Tests   ");
  console.log("==================================================");

  // 1. Client-Side Form Validation Unit Tests
  console.log("\n[1/6] Testing frontend form validation logic (validateSessionForm)...");

  // 1a. Valid input with default presence 75
  const validForm = validateSessionForm({
    courseName: "Data Science",
    classroomId: "Room 204",
    startTime: "2026-09-30T10:00",
    endTime: "2026-09-30T11:00",
    requiredPresence: 75,
  });
  if (!validForm.isValid || Object.keys(validForm.errors).length > 0) {
    throw new Error(`Valid form was rejected: ${JSON.stringify(validForm.errors)}`);
  }
  console.log("  ✅ Valid form accepted with 75% default presence.");

  // 1b. Empty / whitespace course name
  const emptyCourse = validateSessionForm({
    courseName: "   ",
    classroomId: "Room 204",
    startTime: "2026-09-30T10:00",
    endTime: "2026-09-30T11:00",
    requiredPresence: 75,
  });
  if (emptyCourse.isValid || emptyCourse.errors.courseName !== "Course name is required") {
    throw new Error(`Expected 'Course name is required', got: ${emptyCourse.errors.courseName}`);
  }
  console.log("  ✅ Empty/whitespace course name correctly flagged.");

  // 1c. Empty classroom
  const emptyClassroom = validateSessionForm({
    courseName: "Data Science",
    classroomId: "",
    startTime: "2026-09-30T10:00",
    endTime: "2026-09-30T11:00",
    requiredPresence: 75,
  });
  if (emptyClassroom.isValid || emptyClassroom.errors.classroomId !== "Classroom is required") {
    throw new Error(`Expected 'Classroom is required', got: ${emptyClassroom.errors.classroomId}`);
  }
  console.log("  ✅ Missing classroom correctly flagged.");

  // 1d. Missing start/end times
  const missingTimes = validateSessionForm({
    courseName: "Data Science",
    classroomId: "Room 204",
    startTime: "",
    endTime: "",
    requiredPresence: 75,
  });
  if (
    missingTimes.isValid ||
    missingTimes.errors.startTime !== "Start time is required" ||
    missingTimes.errors.endTime !== "End time is required"
  ) {
    throw new Error(`Expected missing time errors, got: ${JSON.stringify(missingTimes.errors)}`);
  }
  console.log("  ✅ Missing start and end times correctly flagged.");

  // 1e. End time before or equal to start time
  const invalidTimeOrder = validateSessionForm({
    courseName: "Data Science",
    classroomId: "Room 204",
    startTime: "2026-09-30T11:00",
    endTime: "2026-09-30T10:00",
    requiredPresence: 75,
  });
  if (
    invalidTimeOrder.isValid ||
    invalidTimeOrder.errors.endTime !== "End time must be after start time"
  ) {
    throw new Error(`Expected 'End time must be after start time', got: ${invalidTimeOrder.errors.endTime}`);
  }
  console.log("  ✅ End time preceding start time correctly rejected.");

  // 1f. Required presence out of bounds (<0 or >100)
  const invalidPresence = validateSessionForm({
    courseName: "Data Science",
    classroomId: "Room 204",
    startTime: "2026-09-30T10:00",
    endTime: "2026-09-30T11:00",
    requiredPresence: 150,
  });
  if (
    invalidPresence.isValid ||
    invalidPresence.errors.requiredPresence !== "Required presence must be between 0 and 100"
  ) {
    throw new Error(`Expected presence out of bounds error, got: ${invalidPresence.errors.requiredPresence}`);
  }
  console.log("  ✅ Out-of-bounds required presence (>100) correctly rejected.");

  // 2. Health check live backend
  console.log("\n[2/6] Checking live backend connectivity...");
  try {
    const health = await requireLiveBackend();
    console.log("✅ Live backend healthy:", health);
  } catch (err: any) {
    console.log("ℹ Backend not currently running locally, skipping live network tests:", err.message);
    console.log("\n==================================================");
    console.log("✅ FRONTEND CREATE SESSION UNIT & VALIDATION TESTS PASSED!");
    console.log("==================================================");
    return;
  }

  const timestamp = Date.now();
  const teacherEmail = `creator_${timestamp}@test.edu`;
  const studentEmail = `student_guest_${timestamp}@test.edu`;
  const password = "StrongPassword123!";

  // 3. Register & Login Teacher
  console.log(`\n[3/6] Authenticating teacher: ${teacherEmail}...`);
  const registeredTeacher = await api.register({
    email: teacherEmail,
    password,
    role: "TEACHER",
  });
  await auth.login({ email: teacherEmail, password });
  console.log("✅ Teacher authenticated:", registeredTeacher.user_id);

  // 4. Call api.createSession(...) with full payload
  console.log("\n[4/6] Testing api.createSession(...) with valid session payload...");
  const sessionPayload = {
    course_name: "Data Science",
    classroom_id: "Room 204",
    start_time: "2026-09-30T10:00:00Z",
    end_time: "2026-09-30T11:00:00Z",
    required_presence_percentage: 75.0,
  };

  const createdSession = await api.createSession(sessionPayload);
  console.log("✅ api.createSession() returned:", createdSession);

  // Assertions
  if (!createdSession.session_id.startsWith("session_")) {
    throw new Error(`Invalid session_id format: ${createdSession.session_id}`);
  }
  if (createdSession.course_name !== sessionPayload.course_name) {
    throw new Error(`course_name mismatch: expected ${sessionPayload.course_name}, got ${createdSession.course_name}`);
  }
  if (createdSession.classroom_id !== sessionPayload.classroom_id) {
    throw new Error(`classroom_id mismatch: expected ${sessionPayload.classroom_id}, got ${createdSession.classroom_id}`);
  }
  if (createdSession.required_presence_percentage !== 75.0) {
    throw new Error(`required_presence_percentage mismatch: expected 75.0, got ${createdSession.required_presence_percentage}`);
  }
  if (createdSession.status !== "SCHEDULED") {
    throw new Error(`status mismatch: expected SCHEDULED, got ${createdSession.status}`);
  }
  if (createdSession.created_by !== registeredTeacher.user_id) {
    throw new Error(`created_by mismatch: expected ${registeredTeacher.user_id}, got ${createdSession.created_by}`);
  }
  console.log("✅ All session fields correctly returned and verified.");

  // 5. Verify session appears in api.getSessions()
  console.log("\n[5/6] Verifying session appears in api.getSessions()...");
  const sessions = await api.getSessions();
  const found = sessions.find((s) => s.session_id === createdSession.session_id);
  if (!found) {
    throw new Error("Created session missing from api.getSessions() list");
  }
  console.log("✅ Created session verified in teacher sessions list.");

  // 6. Verify Student blocked from api.createSession() (403)
  console.log("\n[6/6] Verifying Student is blocked from api.createSession() (403)...");
  await api.register({
    email: studentEmail,
    password,
    role: "STUDENT",
  });
  await auth.login({ email: studentEmail, password });

  try {
    await api.createSession({
      course_name: "Unauthorized Course",
      classroom_id: "ROOM-0",
      start_time: "2026-10-01T12:00:00Z",
      end_time: "2026-10-01T13:00:00Z",
    });
    throw new Error("Student was illegally allowed to create session!");
  } catch (err: any) {
    console.log("✅ Student rejected with:", err.message);
    if (!err.message.includes("403") && !err.message.toLowerCase().includes("insufficient permissions")) {
      throw new Error(`Unexpected error message: ${err.message}`);
    }
  }

  // Clear auth on exit
  auth.logout();
  console.log("\n==================================================");
  console.log("✅ ALL STEP 2C.5 CREATE SESSION & UI TESTS PASSED!");
  console.log("==================================================");
}

testCreateSession().catch((err) => {
  console.error("❌ Test failed:", err);
  process.exit(1);
});
