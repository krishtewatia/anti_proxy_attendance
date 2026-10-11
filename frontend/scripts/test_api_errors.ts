// A rejected form says which field is wrong and why, not "status 422".

import { readFileSync } from "node:fs";
import { validationMessage } from "../src/utils/apiErrors.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

async function run() {
  console.log("==================================================");
  console.log("   Validation Errors In Plain Words               ");
  console.log("==================================================");

  console.log("\n[1/3] Each problem names its field and the rule...");
  // What the server sends when an administrator creates a teacher with a
  // 4-character password and a 1-character department.
  const detail = [
    { type: "string_too_short", loc: ["body", "password"], msg: "String should have at least 6 characters", ctx: { min_length: 6 } },
    { type: "string_too_short", loc: ["body", "department"], msg: "String should have at least 2 characters", ctx: { min_length: 2 } },
    { type: "missing", loc: ["body", "teacher_id"], msg: "Field required" },
  ];
  const message = validationMessage(detail);
  expect(
    message === "Password must be at least 6 characters; Department must be at least 2 characters; Teacher ID is required.",
    `unexpected message: ${message}`,
  );
  expect(
    validationMessage([{ type: "string_too_long", loc: ["body", "name"], ctx: { max_length: 128 } }]) === "Name must be at most 128 characters.",
    "too long must give the limit",
  );
  expect(
    validationMessage([{ type: "string_too_short", loc: ["body", "email"], ctx: { min_length: 1 } }]) === "Email is required.",
    "an empty required text field is 'required'",
  );
  expect(
    validationMessage([{ type: "value_error", loc: ["body", "new_password"], msg: "Value error, Must differ from the current password" }]) ===
      "New password must differ from the current password.",
    "other problems use the server's own words",
  );

  console.log("[2/3] Anything that is not a list of problems is left alone...");
  expect(validationMessage("Invalid email or password") === null, "a plain text detail is not a validation list");
  expect(validationMessage({ code: "account_pending", message: "..." }) === null, "a structured error is not a validation list");
  expect(validationMessage([]) === null && validationMessage(undefined) === null, "nothing to say for an empty list");

  console.log("[3/3] The API client uses it...");
  const api = readFileSync("src/services/api.ts", "utf-8");
  expect(api.includes("validationMessage(errorBody?.detail)"), "api.ts must turn 422 bodies into a readable message");

  console.log("\n✅ All validation message checks passed.");
}

run().catch((err) => {
  console.error("\n❌ Validation message checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
