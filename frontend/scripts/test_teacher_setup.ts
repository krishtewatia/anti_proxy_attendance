// Teachers choose their own subjects and sections: the choice, its checks,
// the status card, the summary lines, and the wiring.

import { readFileSync } from "node:fs";
import { choiceFromClassIds, choiceProblem, classIdsOf, summaryLines, teacherStatusCard, type SetupSubject } from "../src/utils/teacherSetup.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
}

const subjects: SetupSubject[] = [
  { subject_key: "CN", code: "BCSE0502A", name: "Computer Networks", type: "THEORY", targets: ["A", "B"].map((s) => ({ kind: "SECTION" as const, code: s, label: `Section ${s}`, class_id: `cn_${s}` })) },
  { subject_key: "PRED", code: "BCSDS0516", name: "Predictive Analytics", type: "THEORY", targets: [{ kind: "GROUP", code: "DE-II/PA/G1", label: "DE-II PA G1", class_id: "pred_g1" }] },
];

async function run() {
  console.log("==================================================");
  console.log("   Teachers Choose Their Classes                  ");
  console.log("==================================================");

  console.log("\n[1/3] The choice...");
  const choice = choiceFromClassIds(subjects, ["cn_B", "pred_g1"]);
  expect(JSON.stringify(choice) === JSON.stringify({ CN: ["cn_B"], PRED: ["pred_g1"] }), "pre-filled from approved classes");
  expect(classIdsOf(choice).join() === "cn_B,pred_g1", "class ids");
  expect(choiceProblem({}) === "Choose at least one subject.", "a subject is needed");
  expect(choiceProblem({ CN: [] })?.startsWith("For each subject") === true, "sections or groups for each subject");
  expect(choiceProblem(choice) === null, "a complete choice");

  console.log("[2/3] Status and summary...");
  expect(teacherStatusCard(null).title === "Choose your subjects", "start");
  expect(teacherStatusCard({ approved: false, classes: [], latest_request: { request_id: "r", status: "PENDING", class_ids: [] } }).title === "Waiting for approval", "waiting");
  expect(teacherStatusCard({ approved: false, classes: [], latest_request: { request_id: "r", status: "REJECTED", class_ids: [], reason: "Wrong section" } }).text.includes("Wrong section"), "the reason is shown");
  const lines = summaryLines([
    { class_id: "a", cohort_id: "c", subject: "Computer Networks", code: "", target: "Section A" },
    { class_id: "b", cohort_id: "c", subject: "Computer Networks", code: "", target: "Section B" },
  ]);
  expect(lines.join() === "Computer Networks: Section A, Section B", "one line per subject");

  console.log("[3/3] Wiring...");
  const flow = readFileSync("src/pages/TeacherAttendanceFlow.tsx", "utf-8");
  expect(flow.includes('activeNavId === "myclasses" && <MyClasses />') && (flow.match(/<MyClasses \/>/g) ?? []).length === 2, "My Classes, also while waiting");
  const approvals = readFileSync("src/components/admin/ApprovalsTab.tsx", "utf-8");
  expect(approvals.includes("<TeacherRequestsSection"), "teacher requests on the approvals page");

  console.log("\n✅ All teacher setup checks passed.");
}

run().catch((err) => {
  console.error("\n❌ Teacher setup checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
