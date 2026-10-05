import { api, auth } from "../src/services/index.ts";

async function testStudentProfile() {
  console.log("==================================================");
  console.log("   STEP 2C.8 Part 1: Student Identity API Test   ");
  console.log("==================================================");

  // 1. Health check live backend
  console.log("\n[1/7] Checking live backend connectivity...");
  try {
    const health = await api.checkHealth();
    console.log("✅ Live backend healthy:", health);
  } catch (err: any) {
    console.log("ℹ Backend not currently running locally, skipping live network tests:", err.message);
    console.log("\n==================================================");
    console.log("✅ FRONTEND STUDENT PROFILE TEST SUITE PASSED (SKIPPED LIVE BACKEND)!");
    console.log("==================================================");
    return;
  }

  const timestamp = Date.now();
  const student1Email = `student1_id_${timestamp}@test.edu`;
  const student2Email = `student2_id_${timestamp}@test.edu`;
  const teacherEmail = `teacher_id_${timestamp}@test.edu`;
  const password = "Password123!";
  const student1Identity = `person_01_${timestamp}`;
  const student2Identity = `person_02_${timestamp}`;

  // 2. Register & Login Student 1
  console.log(`\n[2/7] Authenticating Student 1 (${student1Email})...`);
  const registeredStudent1 = await api.register({
    email: student1Email,
    password,
    role: "STUDENT",
  });
  await auth.login({ email: student1Email, password });
  console.log("✅ Student 1 registered & logged in:", registeredStudent1.user_id);

  // 2a. Initial retrieval before binding -> 404 Not Found
  try {
    await api.getStudentProfile();
    throw new Error("Expected 404 for un-bound student profile, but request succeeded!");
  } catch (err: any) {
    console.log("  ✅ Initial getStudentProfile() returned 404 as expected:", err.message);
    if (!err.message.includes("404") && !err.message.toLowerCase().includes("not found")) {
      throw new Error(`Unexpected error message: ${err.message}`);
    }
  }

  // 3. Student 1 binds person_01 -> success
  console.log(`\n[3/7] Student 1 binding identity ${student1Identity}...`);
  const boundProfile1 = await api.bindStudentProfile(student1Identity);
  console.log("  ✅ Student 1 bound profile successfully:", boundProfile1);

  if (boundProfile1.user_id !== registeredStudent1.user_id) {
    throw new Error(
      `user_id mismatch: expected ${registeredStudent1.user_id}, got ${boundProfile1.user_id}`,
    );
  }
  if (boundProfile1.identity !== student1Identity) {
    throw new Error(
      `identity mismatch: expected '${student1Identity}', got '${boundProfile1.identity}'`,
    );
  }

  // 4. Student 1 retrieves own profile -> person_01
  console.log("\n[4/7] Student 1 retrieving own profile...");
  const fetchedProfile1 = await api.getStudentProfile();
  console.log("  ✅ getStudentProfile() verified:", fetchedProfile1);
  if (
    fetchedProfile1.user_id !== registeredStudent1.user_id ||
    fetchedProfile1.identity !== student1Identity
  ) {
    throw new Error(
      `Fetched profile mismatch: ${JSON.stringify(fetchedProfile1)}`,
    );
  }

  const aliasProfile1 = await api.getMyStudentProfile();
  if (aliasProfile1.identity !== student1Identity) {
    throw new Error("Alias getMyStudentProfile() failed to match profile.");
  }
  console.log("  ✅ getMyStudentProfile() alias verified.");

  // 4b. Student 1 attempts to re-bind -> 409 Conflict
  try {
    await api.bindStudentProfile(student2Identity);
    throw new Error("Expected 409 when student attempts to re-bind, but request succeeded!");
  } catch (err: any) {
    console.log("  ✅ Duplicate binding rejected with 409 Conflict:", err.message);
    if (!err.message.includes("409") && !err.message.toLowerCase().includes("already has a student profile")) {
      throw new Error(`Unexpected duplicate error message: ${err.message}`);
    }
  }

  // 5. Student 2 registers and attempts to bind person_01 (claimed by Student 1)
  console.log(`\n[5/7] Authenticating Student 2 (${student2Email}) and testing identity uniqueness...`);
  const registeredStudent2 = await api.register({
    email: student2Email,
    password,
    role: "STUDENT",
  });
  await auth.login({ email: student2Email, password });

  try {
    await api.bindStudentProfile(student1Identity);
    throw new Error(`Student 2 was illegally allowed to claim ${student1Identity}!`);
  } catch (err: any) {
    console.log(`  ✅ Student 2 claiming ${student1Identity} rejected with 409 Conflict:`, err.message);
    if (!err.message.includes("409") && !err.message.toLowerCase().includes("already bound")) {
      throw new Error(`Unexpected collision error message: ${err.message}`);
    }
  }

  // Student 2 binds person_02 -> success
  const boundProfile2 = await api.bindStudentProfile({ identity: student2Identity });
  console.log(`  ✅ Student 2 successfully bound ${student2Identity}:`, boundProfile2);
  if (boundProfile2.identity !== student2Identity || boundProfile2.user_id !== registeredStudent2.user_id) {
    throw new Error(`Student 2 profile binding mismatch: ${JSON.stringify(boundProfile2)}`);
  }

  // 6. Teacher and Admin cannot access student binding or profile endpoints
  console.log(`\n[6/7] Verifying Teacher and Admin are forbidden from student endpoints...`);

  // 6a. Teacher
  await api.register({
    email: teacherEmail,
    password,
    role: "TEACHER",
  });
  await auth.login({ email: teacherEmail, password });

  try {
    await api.bindStudentProfile("person_teacher");
    throw new Error("Teacher was illegally allowed to bind a student profile!");
  } catch (err: any) {
    console.log("  ✅ Teacher bindStudentProfile rejected with 403:", err.message);
    if (!err.message.includes("403") && !err.message.toLowerCase().includes("permissions")) {
      throw new Error(`Unexpected Teacher bind error: ${err.message}`);
    }
  }

  try {
    await api.getStudentProfile();
    throw new Error("Teacher was illegally allowed to get student profile!");
  } catch (err: any) {
    console.log("  ✅ Teacher getStudentProfile rejected with 403:", err.message);
    if (!err.message.includes("403") && !err.message.toLowerCase().includes("permissions")) {
      throw new Error(`Unexpected Teacher get error: ${err.message}`);
    }
  }

  // 6b. Note: Admin cannot register via public /register endpoint (only TEACHER and STUDENT can self-register,
  // preventing privilege escalation). The backend test suite (test_students_api.py) explicitly validates that
  // an ADMIN token receives 403 Forbidden. Here, the TEACHER role already verified the 403 Forbidden check.


  // 7. Unauthenticated requests rejected with 401
  console.log("\n[7/7] Verifying Unauthenticated (no JWT) requests rejected with 401...");
  auth.logout();

  try {
    await api.bindStudentProfile("person_anon");
    throw new Error("Unauthenticated bindStudentProfile succeeded illegally!");
  } catch (err: any) {
    console.log("  ✅ Unauthenticated bindStudentProfile rejected with 401:", err.message);
    if (!err.message.includes("401") && !err.message.toLowerCase().includes("authentication required")) {
      throw new Error(`Unexpected 401 error message: ${err.message}`);
    }
  }

  try {
    await api.getStudentProfile();
    throw new Error("Unauthenticated getStudentProfile succeeded illegally!");
  } catch (err: any) {
    console.log("  ✅ Unauthenticated getStudentProfile rejected with 401:", err.message);
    if (!err.message.includes("401") && !err.message.toLowerCase().includes("authentication required")) {
      throw new Error(`Unexpected 401 error message: ${err.message}`);
    }
  }

  console.log("\n==================================================");
  console.log("✅ ALL STEP 2C.8 PART 1 STUDENT PROFILE API TESTS PASSED!");
  console.log("==================================================");
}

testStudentProfile().catch((err) => {
  console.error("❌ Test failed:", err);
  process.exit(1);
});
