import {
  adminDeleteBlockedReason,
  isPasswordChangeRequired,
  splitList,
  studentEditChanges,
  studentIdChangeWarning,
  teacherEditChanges,
  validatePasswordChange,
  type AdminAccount,
  type StudentEditFields,
  type TeacherEditFields,
} from "../src/utils/accounts.ts";
import { auth } from "../src/services/index.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

async function runAccountTests() {
  console.log("==================================================");
  console.log("   Account Management: Screen Rules               ");
  console.log("==================================================");

  console.log("\n[1/7] A password change is checked before it is sent...");
  expect(validatePasswordChange("", "NewPassword1!", "NewPassword1!") !== null, "the current password is required");
  expect(validatePasswordChange("old", "short", "short") !== null, "a short new password must be refused");
  expect(validatePasswordChange("SamePassword1!", "SamePassword1!", "SamePassword1!") !== null, "the same password again must be refused");
  expect(validatePasswordChange("old", "NewPassword1!", "NewPassword2!") !== null, "a mismatch must be refused");
  expect(validatePasswordChange("old", "NewPassword1!", "NewPassword1!") === null, "a valid change must be accepted");

  console.log("[2/7] The forced-change answer from the API is recognized...");
  expect(isPasswordChangeRequired("You must change your password before you can continue."), "the server message must be recognized");
  expect(!isPasswordChangeRequired("Insufficient permissions"), "another 403 must not be mistaken for it");

  console.log("[3/7] The forced-change flag is stored with the session and cleared on sign-out...");
  auth.clearStoredAuth();
  expect(auth.mustChangePassword() === false, "no flag without a session");
  auth.setMustChangePassword(true);
  expect(auth.mustChangePassword() === true, "the flag must be remembered");
  auth.setMustChangePassword(false);
  expect(auth.mustChangePassword() === false, "the flag must clear after a change");
  auth.setMustChangePassword(true);
  auth.clearStoredAuth();
  expect(auth.mustChangePassword() === false, "signing out must clear the flag");

  console.log("[4/7] Comma lists are trimmed and de-duplicated...");
  expect(splitList(" Machine Learning, Deep Learning ,, Machine Learning ").join("|") === "Machine Learning|Deep Learning", "unexpected list");
  expect(splitList("  ").length === 0, "blank input must give an empty list");

  console.log("[5/7] Only the student fields that changed are sent...");
  const student: StudentEditFields = {
    name: "Asha Verma",
    email: "asha@example.test",
    student_id: "DS202610",
    roll_number: "20261010",
    branch: "Data Science",
    section: "B",
  };
  expect(Object.keys(studentEditChanges(student, { ...student })).length === 0, "nothing changed must send nothing");
  expect(Object.keys(studentEditChanges(student, { ...student, name: " Asha Verma " })).length === 0, "whitespace is not a change");
  const idOnly = studentEditChanges(student, { ...student, student_id: "DS202699" });
  expect(JSON.stringify(idOnly) === JSON.stringify({ student_id: "DS202699" }), "an ID change must send only the ID");
  const moved = studentEditChanges(student, { ...student, section: "c" });
  expect(moved.branch === "Data Science" && moved.section === "C", "a class change must send branch and section together");
  expect(moved.name === undefined && moved.email === undefined, "a class change must not resend other fields");
  expect(studentIdChangeWarning("DS202610", "DS202699").includes("DS202610") && studentIdChangeWarning("DS202610", "DS202699").includes("DS202699"), "the warning must name both IDs");

  console.log("[6/7] Only the teacher fields that changed are sent...");
  const teacher: TeacherEditFields = {
    name: "Ravi Menon",
    email: "ravi@example.test",
    teacher_id: "T010",
    department: "Data Science",
    assigned_classes: ["DS-B", "DS-C"],
    assigned_subjects: ["Machine Learning"],
  };
  expect(Object.keys(teacherEditChanges(teacher, { ...teacher, assigned_classes: ["DS-B", "DS-C"] })).length === 0, "the same classes must send nothing");
  const fewer = teacherEditChanges(teacher, { ...teacher, assigned_classes: ["DS-B"] });
  expect(JSON.stringify(fewer) === JSON.stringify({ assigned_classes: ["DS-B"] }), "removing a class must send the new class list only");
  const none = teacherEditChanges(teacher, { ...teacher, assigned_classes: [] });
  expect(Array.isArray(none.assigned_classes) && none.assigned_classes.length === 0, "removing every class must send an empty list, not nothing");
  expect(teacherEditChanges(teacher, { ...teacher, department: "Computer Science" }).department === "Computer Science", "a department change must be sent");

  console.log("[7/7] An administrator cannot delete themself or the last administrator...");
  const me: AdminAccount = { user_id: "admin_1", email: "one@example.test", name: "One", must_change_password: false };
  const other: AdminAccount = { user_id: "admin_2", email: "two@example.test", name: "Two", must_change_password: true };
  expect(adminDeleteBlockedReason(me, "admin_1", 2) !== null, "deleting yourself must be blocked");
  expect(adminDeleteBlockedReason(me, "admin_1", 1) !== null, "deleting yourself as the last admin must be blocked");
  expect(adminDeleteBlockedReason(other, "admin_1", 1) !== null, "deleting the last administrator must be blocked");
  expect(adminDeleteBlockedReason(other, "admin_1", 2) === null, "deleting another administrator must be allowed");

  console.log("\n✅ All account management checks passed.");
}

runAccountTests().catch((err) => {
  console.error("\n❌ Account management checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
