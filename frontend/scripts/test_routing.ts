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
  if (getDashboardPath("TEACHER") !== "/teacher/dashboard") {
    throw new Error(`Expected /teacher/dashboard, got ${getDashboardPath("TEACHER")}`);
  }
  if (getDashboardPath("STUDENT") !== "/student/dashboard") {
    throw new Error(`Expected /student/dashboard, got ${getDashboardPath("STUDENT")}`);
  }
  if (getDashboardPath("ADMIN") !== "/admin/dashboard") {
    throw new Error(`Expected /admin/dashboard, got ${getDashboardPath("ADMIN")}`);
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

  const teacherAccessTeacher = evaluateRouteAccess("/teacher/dashboard", ["TEACHER"], teacherUser, true);
  if (!teacherAccessTeacher.allowed) {
    throw new Error("Teacher was unexpectedly blocked from /teacher/dashboard");
  }

  const teacherAccessStudent = evaluateRouteAccess("/student/dashboard", ["STUDENT"], teacherUser, true);
  if (teacherAccessStudent.allowed || teacherAccessStudent.redirectPath !== "/teacher/dashboard") {
    throw new Error("Teacher accessing /student/dashboard was not redirected to /teacher/dashboard");
  }

  const teacherAccessAdmin = evaluateRouteAccess("/admin/dashboard", ["ADMIN"], teacherUser, true);
  if (teacherAccessAdmin.allowed || teacherAccessAdmin.redirectPath !== "/teacher/dashboard") {
    throw new Error("Teacher accessing /admin/dashboard was not redirected to /teacher/dashboard");
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

  const studentAccessStudent = evaluateRouteAccess("/student/dashboard", ["STUDENT"], studentUser, true);
  if (!studentAccessStudent.allowed) {
    throw new Error("Student was unexpectedly blocked from /student/dashboard");
  }

  const studentAccessTeacher = evaluateRouteAccess("/teacher/dashboard", ["TEACHER"], studentUser, true);
  if (studentAccessTeacher.allowed || studentAccessTeacher.redirectPath !== "/student/dashboard") {
    throw new Error("Student accessing /teacher/dashboard was not redirected to /student/dashboard");
  }

  const studentAccessAdmin = evaluateRouteAccess("/admin/dashboard", ["ADMIN"], studentUser, true);
  if (studentAccessAdmin.allowed || studentAccessAdmin.redirectPath !== "/student/dashboard") {
    throw new Error("Student accessing /admin/dashboard was not redirected to /student/dashboard");
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
