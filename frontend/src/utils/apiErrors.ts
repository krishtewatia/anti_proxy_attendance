// Turns the server's validation errors (HTTP 422) into a sentence a person
// can act on, instead of "Request failed with status 422".

interface ValidationIssue {
  loc?: unknown[];
  msg?: string;
  type?: string;
  ctx?: Record<string, unknown>;
}

const FIELD_LABELS: Record<string, string> = {
  teacher_id: "Teacher ID",
  student_id: "Student ID",
  roll_number: "Roll number",
  class_code: "Class code",
  new_password: "New password",
  current_password: "Current password",
  photo_base64: "Photo",
};

function fieldLabel(loc: unknown[] | undefined): string {
  const names = (loc || []).filter((part) => typeof part === "string" && part !== "body" && part !== "query") as string[];
  const name = names[names.length - 1];
  if (!name) return "";
  if (FIELD_LABELS[name]) return FIELD_LABELS[name];
  const words = name.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function describe(issue: ValidationIssue): string {
  const label = fieldLabel(issue.loc);
  const ctx = issue.ctx || {};
  let problem: string;
  switch (issue.type) {
    case "missing":
      problem = "is required";
      break;
    case "string_too_short":
      problem = Number(ctx.min_length) <= 1 ? "is required" : `must be at least ${ctx.min_length} characters`;
      break;
    case "string_too_long":
      problem = `must be at most ${ctx.max_length} characters`;
      break;
    case "too_short":
      problem = "needs at least one entry";
      break;
    default:
      problem = (issue.msg || "is not valid").replace(/^Value error, /, "");
      problem = problem.charAt(0).toLowerCase() + problem.slice(1);
  }
  return label ? `${label} ${problem}` : problem.charAt(0).toUpperCase() + problem.slice(1);
}

// The message for a 422 body, or null when the body is not a list of
// validation issues.
export function validationMessage(detail: unknown): string | null {
  if (!Array.isArray(detail) || detail.length === 0) return null;
  const parts = detail
    .filter((issue): issue is ValidationIssue => typeof issue === "object" && issue !== null)
    .map(describe);
  return parts.length ? `${parts.join("; ")}.` : null;
}
