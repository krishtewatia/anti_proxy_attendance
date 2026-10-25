// The official section list: category labels, which requests can be approved
// together, the badge on a setup request, filtering, and the wiring.

import { readFileSync } from "node:fs";
import {
  CATEGORY_BADGE,
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  TEMPLATE_HEADER,
  listBadge,
  matchingRequestIds,
  rowsIn,
  type MatchReport,
  type ReportRow,
} from "../src/utils/sectionList.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

const choices = { "DE-II": { option: "PA", group: "G2" } };

function row(roll: string, category: ReportRow["category"], section: string, requestId?: string, differences: string[] = []): ReportRow {
  return {
    roll_no: roll,
    category,
    list: { name: "Student", email: `${roll}@niet.co.in`, section, choices },
    student: requestId ? { user_id: `u${roll}`, name: "Student", email: `${roll}@niet.co.in` } : null,
    request: requestId ? { request_id: requestId, kind: "FIRST", section, choices } : null,
    differences,
    warnings: [],
  };
}

const report: MatchReport = {
  cohort_id: "c",
  source_name: "ds3.csv",
  uploaded_at: null,
  counts: { MATCH: 2, DIFFERENT: 1, EMAIL_DIFFERS: 0, NOT_ON_LIST: 0, NO_REQUEST: 0, NOT_REGISTERED: 1, APPROVED_AGREES: 0, APPROVED_DIFFERS: 0 },
  rows: [
    row("2401331540001", "MATCH", "B", "r1"),
    row("2401331540002", "MATCH", "C", "r2"),
    row("2401331540003", "DIFFERENT", "B", "r3", ["DE-II: list PA G2, student PA G1"]),
    row("2401331540004", "NOT_REGISTERED", "B"),
  ],
};

async function run() {
  console.log("==================================================");
  console.log("   Section List: Matching And Bulk Approval       ");
  console.log("==================================================");

  console.log("\n[1/3] Every category has a label and an existing badge...");
  for (const category of CATEGORY_ORDER) {
    expect(Boolean(CATEGORY_LABELS[category]), `label for ${category}`);
    expect(["present", "warning", "absent", "completed"].includes(CATEGORY_BADGE[category]), `badge for ${category}`);
  }
  expect(TEMPLATE_HEADER === "roll_no,name,email,section,de2,de3,dlda", "template columns");

  console.log("[2/3] Only matching waiting requests can be approved together...");
  expect(matchingRequestIds(report).join() === "r1,r2", "all matching");
  expect(matchingRequestIds(report, "B").join() === "r1", "matching in one section");
  expect(matchingRequestIds(null).length === 0, "no list, nothing");
  const differs = listBadge(report, "r3");
  expect(differs?.label === "Differs from the list" && differs.detail.includes("PA G1"), "the difference is shown on the card");
  expect(listBadge(report, "r1")?.badge === "present", "a match is green");
  expect(listBadge(report, "unknown") === null, "a request the list does not cover gets no badge");
  expect(rowsIn(report, "ALL", "B").length === 3 && rowsIn(report, "MATCH").length === 2, "filters");

  console.log("[3/3] The screens are wired...");
  const tab = readFileSync("src/components/admin/ApprovalsTab.tsx", "utf-8");
  expect(tab.includes("Official section list") && tab.includes("<SectionListsSection"), "the section list is under Approvals, where it is used");
  const lists = readFileSync("src/components/admin/academic/SectionListsSection.tsx", "utf-8");
  expect(lists.includes("uploadSectionList(cohort.cohort_id, text, file.name, true)"), "a list is always checked first");
  const requests = readFileSync("src/components/admin/SetupRequestsSection.tsx", "utf-8");
  expect(requests.includes("api.approveMatching(") && requests.includes("Matching the list only"), "approve-matching on the approvals page");
  expect(requests.includes("setMatchingOnly(true)") && requests.includes("window.confirm"), "the matching photos are shown and confirmed before approving");

  console.log("\n✅ All section list checks passed.");
}

run().catch((err) => {
  console.error("\n❌ Section list checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
