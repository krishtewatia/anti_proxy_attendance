// Pilot sign-up: college email domain, roll number instead of a student ID,
// no teacher ID, the photo notice before a photo, and no "forgot password"
// (an administrator resets passwords).

import { readFileSync } from "node:fs";
import {
  emailAllowed,
  duplicateRegistrationMessage,
  emailHint,
  emailPlaceholder,
  FORGOT_PASSWORD_HINT,
  registeredMessage,
  registrationProblem,
  type RegistrationFields,
} from "../src/utils/registration.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

const student: RegistrationFields = {
  role: "STUDENT",
  name: "Pilot Student",
  email: "any.name@niet.co.in",
  password: "secret123",
  confirmPassword: "secret123",
  rollNumber: "2401331540142",
  hasPhoto: false,
  consentAccepted: false,
};

async function run() {
  console.log("==================================================");
  console.log("   Sign-up: College Email, Roll No, Photo Notice  ");
  console.log("==================================================");

  console.log("\n[1/4] The college email domain, once it applies...");
  expect(emailAllowed("A.Teacher@NIET.co.in", "niet.co.in"), "the domain is not case-sensitive");
  expect(!emailAllowed("someone@gmail.com", "niet.co.in"), "another domain is refused");
  expect(!emailAllowed("x@niet.co.in.evil.test", "niet.co.in"), "the domain must end the address");
  expect(emailAllowed("someone@gmail.com", null), "any address while no structure exists");
  expect(emailPlaceholder("niet.co.in", "STUDENT") === "STUDENT_ERP@niet.co.in", "student placeholder is the ERP ID");
  expect(emailHint("niet.co.in", "STUDENT") === "Use your college email (your ERP ID @niet.co.in).", "student email hint");
  expect(duplicateRegistrationMessage("Roll number 2401331540142 is already registered.").startsWith("This roll number is already registered."), "says the roll number is taken");
  expect(duplicateRegistrationMessage("A user with email 'a@niet.co.in' already exists").startsWith("An account with this email already exists."), "says the email is taken");
  expect(duplicateRegistrationMessage("409").includes("Ask an administrator"), "points to an administrator");
  expect(emailPlaceholder("niet.co.in", "TEACHER") === "name@niet.co.in", "teacher placeholder");

  console.log("[2/4] What the form refuses before it sends anything...");
  expect(registrationProblem(student, "niet.co.in") === null, "a complete student form is fine");
  expect(
    registrationProblem({ ...student, email: "me@gmail.com" }, "niet.co.in") === "Use your college email address (ending in @niet.co.in).",
    "outside the domain",
  );
  expect(registrationProblem({ ...student, rollNumber: " " }, null) === "Please enter your roll number.", "roll number required");
  for (const bad of ["../x", "0241CSDS030", "2401-3315", "1234567", "1".repeat(21)]) {
    expect(registrationProblem({ ...student, rollNumber: bad }, null)?.startsWith("Your roll number is digits only") === true, `roll number ${bad} must be refused`);
  }
  expect(registrationProblem({ ...student, rollNumber: " 2401331540142 " }, null) === null, "spaces around the roll number are fine");
  expect(registrationProblem({ ...student, rollNumber: "12345678" }, null) === null, "8 digits is fine");
  expect(registrationProblem({ ...student, confirmPassword: "other" }, null) === "Passwords do not match.", "passwords match");
  const teacher: RegistrationFields = { ...student, role: "TEACHER", email: "a.teacher@niet.co.in", rollNumber: "" };
  expect(registrationProblem(teacher, "niet.co.in") === null, "a teacher needs no roll number and no teacher ID");

  console.log("[3/4] A photo needs the notice accepted...");
  expect(
    registrationProblem({ ...student, hasPhoto: true }, null) === "Read the notice about your photo and tick that you accept it.",
    "photo without the notice",
  );
  expect(registrationProblem({ ...student, hasPhoto: true, consentAccepted: true }, null) === null, "photo with the notice");

  console.log("[4/4] The forms: no Student ID or Teacher ID, the notice, no forgot-password link...");
  const register = readFileSync("src/components/auth/RegisterForm.tsx", "utf-8");
  expect(!register.includes("Student ID") && !register.includes("Teacher ID"), "the sign-up form must not ask for IDs");
  expect(!register.includes("student_id:") && !register.includes("teacher_id:"), "the sign-up form must not send IDs");
  expect(register.includes(">Roll No<"), "the sign-up form asks for the roll number");
  expect(register.includes("<ConsentNotice") && register.includes("consent_version:"), "the photo notice is shown and its version sent");
  const login = readFileSync("src/components/auth/LoginForm.tsx", "utf-8");
  expect(login.includes("{FORGOT_PASSWORD_HINT}") && !/reset link|forgot-password/i.test(login), "sign-in points to the administrator");
  expect(FORGOT_PASSWORD_HINT.includes("administrator"), "the hint names the administrator");
  expect(registeredMessage("STUDENT").startsWith("Account created. Sign in now"), "a student signs in at once");
  expect(registeredMessage("TEACHER").includes("once an administrator approves you and assigns your classes"), "a teacher signs in, and takes attendance after approval");
  for (const file of ["src/components/admin/StudentsTab.tsx", "src/components/admin/TeachersTab.tsx"]) {
    const source = readFileSync(file, "utf-8");
    expect(!source.includes(">Student ID<") && !source.includes(">Teacher ID<"), `${file} must not ask for or show an ID`);
  }

  console.log("\n✅ All sign-up checks passed.");
}

run().catch((err) => {
  console.error("\n❌ Sign-up checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
