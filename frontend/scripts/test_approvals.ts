import {
  daysUntilPurge,
  isPendingApprovalError,
  normalizeClassCodes,
  pendingBadgeText,
  registrationAge,
  validateStudentApproval,
  validateTeacherApproval,
} from "../src/utils/approvals.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

async function runApprovalTests() {
  console.log("==================================================");
  console.log("   Registration Approval: Admin Screen Rules      ");
  console.log("==================================================");

  console.log("\n[1/6] The badge shows a count only when something is waiting...");
  expect(pendingBadgeText(0) === null, "0 must show no badge");
  expect(pendingBadgeText(undefined) === null && pendingBadgeText(null) === null, "no value must show no badge");
  expect(pendingBadgeText(-3) === null, "a negative count must show no badge");
  expect(pendingBadgeText(1) === "1" && pendingBadgeText(42) === "42", "counts must be shown as they are");
  expect(pendingBadgeText(99) === "99" && pendingBadgeText(100) === "99+", "more than 99 must show 99+");

  console.log("[2/6] Class codes are trimmed, upper-cased and de-duplicated...");
  expect(normalizeClassCodes([" ds-b ", "DS-B", "cs-a", "", "  "]).join(",") === "DS-B,CS-A", "unexpected normalization");

  console.log("[3/6] A teacher cannot be approved without a class, or with an unknown one...");
  const available = ["DS-A", "DS-B", "CS-A"];
  expect(validateTeacherApproval([], available) !== null, "no class must be refused");
  expect(validateTeacherApproval(["  "], available) !== null, "a blank class must be refused");
  expect((validateTeacherApproval(["DS-B", "XX-Z"], available) || "").includes("XX-Z"), "an unknown class must be named");
  expect(validateTeacherApproval(["ds-b"], available) === null, "a known class in any case must be accepted");
  expect(validateTeacherApproval(["DS-A", "CS-A"], available) === null, "several known classes must be accepted");

  console.log("[4/6] A student needs both branch and section...");
  expect(validateStudentApproval("Data Science", "B") === null, "a full class must be accepted");
  expect(validateStudentApproval("Data Science", "") !== null, "a missing section must be refused");
  expect(validateStudentApproval(" ", "B") !== null, "a missing branch must be refused");

  console.log("[5/6] Registration age and the days left before automatic removal...");
  const now = new Date("2026-10-20T12:00:00Z");
  expect(registrationAge("2026-10-20T09:00:00Z", now) === "today", "same day must read today");
  expect(registrationAge("2026-10-19T09:00:00Z", now) === "1 day ago", "one day");
  expect(registrationAge("2026-10-10T12:00:00Z", now) === "10 days ago", "ten days");
  expect(registrationAge(null, now) === "" && registrationAge("not a date", now) === "", "no date gives no text");
  expect(daysUntilPurge("2026-10-20T12:00:00Z", now) === 14, "a new registration has 14 days");
  expect(daysUntilPurge("2026-10-08T12:00:00Z", now) === 2, "12 days old leaves 2");
  expect(daysUntilPurge("2026-09-01T12:00:00Z", now) === 0, "an overdue registration never goes negative");
  expect(daysUntilPurge(undefined, now) === null, "no date gives null");

  console.log("[6/6] The login form recognizes the awaiting-approval answer...");
  expect(
    isPendingApprovalError("Your registration is awaiting admin approval. You can log in once it has been approved."),
    "the server message must be recognized",
  );
  expect(!isPendingApprovalError("Invalid email or password"), "a wrong password is not a pending account");
  expect(!isPendingApprovalError("Request failed with status 403"), "a bare 403 is not a pending account");

  console.log("\nAll registration approval tests passed.");
}

runApprovalTests().catch((error) => {
  console.error("Registration approval tests failed:", error);
  process.exit(1);
});
