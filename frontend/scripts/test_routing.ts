import { getDashboardPath, isValidRole, ROLE_DASHBOARD_MAP } from "../src/utils/auth.ts";
import type { UserResponse, UserRole } from "../src/types/index.ts";

// Helper function modeling the route decision logic implemented in ProtectedRoute
function evaluateRouteAccess(
  requestedPath: string,
  allowedRoles: UserRole[],
  currentUser: UserResponse | null,
  isAuthenticated: boolean
): { allowed: boolean; redirectPath?: string } {
  // 1. Authentication check
  if (!isAuthenticated || !currentUser) {
    return { allowed: false, redirectPath: "/" };
  }

  // 2. Role authorization check
  if (allowedRoles.length > 0 && !allowedRoles.includes(currentUser.role)) {
    return { allowed: false, redirectPath: getDashboardPath(currentUser.role) };
  }

  return { allowed: true };
}

async function runRoutingTests() {
  console.log("==================================================");
  console.log("   STEP 2C.3: Protected Routing Unit Tests        ");
  console.log("==================================================");

  // 1. Role to Dashboard Mappings
  console.log("\n[1/5] Testing role -> dashboard mappings...");
  if (getDashboardPath("TEACHER") !== "/dashboard/teacher") {
    throw new Error(`Expected /dashboard/teacher, got ${getDashboardPath("TEACHER")}`);
  }
  if (getDashboardPath("STUDENT") !== "/dashboard/student") {
    throw new Error(`Expected /dashboard/student, got ${getDashboardPath("STUDENT")}`);
  }
  if (getDashboardPath("ADMIN") !== "/dashboard/admin") {
    throw new Error(`Expected /dashboard/admin, got ${getDashboardPath("ADMIN")}`);
  }
  if (getDashboardPath(null) !== "/") {
    throw new Error(`Expected / for null role, got ${getDashboardPath(null)}`);
  }
  console.log("✅ All role -> dashboard mappings verified:", ROLE_DASHBOARD_MAP);

  // 2. Role Validator Type Guard
  console.log("\n[2/5] Testing isValidRole type guard...");
  if (!isValidRole("TEACHER") || !isValidRole("STUDENT") || !isValidRole("ADMIN")) {
    throw new Error("Valid roles failed type guard validation");
  }
  if (isValidRole("SUPERUSER") || isValidRole("GUEST") || isValidRole("")) {
    throw new Error("Invalid roles unexpectedly passed type guard validation");
  }
  console.log("✅ Role validator type guard verified.");

  // 3. Test 1: Teacher trying to access Student / Admin dashboards
  console.log("\n[3/5] Testing Teacher routing & boundary enforcement...");
  const teacherUser: UserResponse = {
    user_id: "teacher_01",
    email: "teacher@test.edu",
    role: "TEACHER",
    is_active: true,
  };

  const teacherAccessTeacher = evaluateRouteAccess("/dashboard/teacher", ["TEACHER"], teacherUser, true);
  if (!teacherAccessTeacher.allowed) {
    throw new Error("Teacher was unexpectedly blocked from /dashboard/teacher");
  }

  const teacherAccessStudent = evaluateRouteAccess("/dashboard/student", ["STUDENT"], teacherUser, true);
  if (teacherAccessStudent.allowed || teacherAccessStudent.redirectPath !== "/dashboard/teacher") {
    throw new Error("Teacher accessing /dashboard/student was not redirected to /dashboard/teacher");
  }

  const teacherAccessAdmin = evaluateRouteAccess("/dashboard/admin", ["ADMIN"], teacherUser, true);
  if (teacherAccessAdmin.allowed || teacherAccessAdmin.redirectPath !== "/dashboard/teacher") {
    throw new Error("Teacher accessing /dashboard/admin was not redirected to /dashboard/teacher");
  }
  console.log("✅ Teacher allowed on teacher dashboard, redirected from student/admin dashboards.");

  // 4. Test 2: Student trying to access Teacher / Admin dashboards
  console.log("\n[4/5] Testing Student routing & boundary enforcement...");
  const studentUser: UserResponse = {
    user_id: "student_01",
    email: "student@test.edu",
    role: "STUDENT",
    is_active: true,
  };

  const studentAccessStudent = evaluateRouteAccess("/dashboard/student", ["STUDENT"], studentUser, true);
  if (!studentAccessStudent.allowed) {
    throw new Error("Student was unexpectedly blocked from /dashboard/student");
  }

  const studentAccessTeacher = evaluateRouteAccess("/dashboard/teacher", ["TEACHER"], studentUser, true);
  if (studentAccessTeacher.allowed || studentAccessTeacher.redirectPath !== "/dashboard/student") {
    throw new Error("Student accessing /dashboard/teacher was not redirected to /dashboard/student");
  }

  const studentAccessAdmin = evaluateRouteAccess("/dashboard/admin", ["ADMIN"], studentUser, true);
  if (studentAccessAdmin.allowed || studentAccessAdmin.redirectPath !== "/dashboard/student") {
    throw new Error("Student accessing /dashboard/admin was not redirected to /dashboard/student");
  }
  console.log("✅ Student allowed on student dashboard, redirected from teacher/admin dashboards.");

  // 5. Test 3 & 4: Unauthenticated or Corrupted Session Access
  console.log("\n[5/5] Testing unauthenticated & corrupt session access...");
  const unauthTeacher = evaluateRouteAccess("/dashboard/teacher", ["TEACHER"], null, false);
  if (unauthTeacher.allowed || unauthTeacher.redirectPath !== "/") {
    throw new Error("Unauthenticated user accessing /dashboard/teacher was not redirected to /");
  }

  const unauthStudent = evaluateRouteAccess("/dashboard/student", ["STUDENT"], null, false);
  if (unauthStudent.allowed || unauthStudent.redirectPath !== "/") {
    throw new Error("Unauthenticated user accessing /dashboard/student was not redirected to /");
  }

  const corruptAuth = evaluateRouteAccess("/dashboard/teacher", ["TEACHER"], null, true); // true auth flag but missing user object
  if (corruptAuth.allowed || corruptAuth.redirectPath !== "/") {
    throw new Error("Corrupted auth accessing /dashboard/teacher was not redirected to /");
  }
  console.log("✅ Unauthenticated and corrupted sessions strictly redirected to root /.");

  console.log("\n==================================================");
  console.log("✅ ALL STEP 2C.3 ROUTING TESTS PASSED!");
  console.log("==================================================");
}

runRoutingTests().catch((err) => {
  console.error("❌ Routing tests failed:", err);
  process.exit(1);
});
