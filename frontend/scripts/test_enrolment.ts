// Student self-setup: step checks, the section's core classes, group choices
// by code only, photos and the notice, the dashboard status card, the
// blur score, and the admin's "select all in this section / group".

import { readFileSync } from "node:fs";
import {
  SETUP_STEPS,
  choiceLabel,
  coreClasses,
  draftFromEnrolment,
  emptyDraft,
  requestBody,
  selectBy,
  setupStatusCard,
  sharpness,
  stepProblem,
  type AdminSetupRequest,
  type SetupOptions,
} from "../src/utils/enrolment.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

const options: SetupOptions = {
  cohorts: [
    {
      cohort_id: "CSE-DS-Y3-2026-27-ODD",
      name: "B.Tech CSE-DS, 3rd year, Semester V",
      branch: "CSE-DS",
      year: 3,
      semester: "V",
      term_id: "2026-27-ODD",
      sections: ["A", "B", "C", "D"].map((code) => ({
        code,
        core_classes: [{ class_id: `t:c:${code}:CN`, subject_key: "CN", code: "BCSE0502A", name: "Computer Networks", type: "THEORY" }],
      })),
      group_sets: [
        { set_code: "DE-II", kind: "ELECTIVE", name: "Department Elective II", options: [{ option_code: "PA", name: "Predictive Analytics", groups: ["G1", "G2", "G3"] }, { option_code: "AJ", name: "Advance Java", groups: ["AJ"] }] },
        { set_code: "DE-III", kind: "ELECTIVE", name: "Department Elective III", options: [{ option_code: "PROD", name: "Product Analytics", groups: ["G1", "G2", "G3"] }, { option_code: "DP", name: "Design Pattern", groups: ["DP"] }] },
        { set_code: "DLDA", kind: "WORKSHOP", name: "DLDA workshop groups", options: [{ option_code: "DLDA", name: "Deep Learning for Data Analytics", groups: ["DL1", "DL2", "DL3", "DL4"] }] },
      ],
    },
  ],
  not_counted: [{ code: "BVAC0551", name: "Professional Practice and Employability-I" }],
  consent_version: "pilot-2026-10",
  photos: { min: 2, max: 3 },
};

const complete = {
  cohortId: "CSE-DS-Y3-2026-27-ODD",
  section: "B",
  choices: { "DE-II": { option: "PA", group: "G2" }, "DE-III": { option: "DP", group: "DP" }, DLDA: { option: "DLDA", group: "DL3" } },
  photos: ["a", "b"],
  consentAccepted: true,
};

function request(id: string, section: string, de2: string, status: AdminSetupRequest["status"] = "PENDING"): AdminSetupRequest {
  return {
    request_id: id, kind: "FIRST", status, cohort_id: "c", section, class_ids: [], photo_count: 2, submitted_at: "",
    choices: { "DE-II": { option: "PA", group: de2 }, "DE-III": { option: "PROD", group: "G1" } },
    user_id: id, branch: "CSE-DS", year: 3, name: id, roll_number: "2401331540142", email: `${id}@niet.co.in`, photo_urls: [], current_photo_url: null,
  };
}

async function run() {
  console.log("==================================================");
  console.log("   Student Setup: Section, Groups, Photos, Review ");
  console.log("==================================================");

  console.log("\n[1/5] Steps, in order, each checked before the next...");
  expect(SETUP_STEPS.join(" > ") === "Year and section > Core subjects > Electives and DLDA > Photos > Review", "step order");
  expect(stepProblem(0, emptyDraft(), options, false) === "Choose your year.", "year first");
  expect(stepProblem(0, { ...complete, section: "Z" }, options, false) === "Choose your section.", "a listed section");
  expect(stepProblem(2, { ...complete, choices: { ...complete.choices, "DE-II": { option: "AJ", group: "G1" } } }, options, false) === "Choose your DE-II option and group.", "only listed option + group pairs");
  expect(stepProblem(2, { ...complete, choices: { "DE-II": complete.choices["DE-II"], "DE-III": complete.choices["DE-III"] } }, options, false) === "Choose your DLDA option and group.", "DLDA is required too");
  expect(stepProblem(4, complete, options, false) === null, "a complete setup passes");

  console.log("[2/5] Photos: 2 or 3, after the notice; optional for a change...");
  expect(stepProblem(3, { ...complete, photos: ["a"] }, options, false) === "Add 2 or 3 photos of your face.", "at least 2");
  expect(stepProblem(3, { ...complete, photos: ["a", "b", "c", "d"] }, options, false) === "Add 2 or 3 photos of your face.", "at most 3");
  expect(stepProblem(3, { ...complete, consentAccepted: false }, options, false)?.includes("notice") === true, "the notice first");
  expect(stepProblem(3, { ...complete, photos: [], consentAccepted: false }, options, true) === null, "a change may keep the photos");
  const body = requestBody(complete, "pilot-2026-10");
  expect(body.consent_version === "pilot-2026-10" && body.photos.length === 2, "the notice version goes with photos");
  expect(!("consent_version" in requestBody({ ...complete, photos: [] }, "v")), "no notice version without photos");

  console.log("[3/5] Core classes come from the section; a change starts from the approved setup...");
  expect(coreClasses(options, complete.cohortId, "C")[0].class_id === "t:c:C:CN", "the section's own classes");
  const draft = draftFromEnrolment({ cohort_id: "x", section: "D", choices: complete.choices, class_ids: [], since: "" });
  expect(draft.section === "D" && draft.photos.length === 0 && !draft.consentAccepted, "change draft");

  console.log("[4/5] The dashboard card, and the blur score...");
  expect(setupStatusCard(null).action === "start", "not set up yet");
  const waiting = setupStatusCard({ eligible: false, enrolment: null, latest_request: { ...request("r", "B", "G1"), kind: "FIRST" } });
  expect(waiting.title === "Waiting for approval" && waiting.action === "withdraw", "waiting");
  const rejected = setupStatusCard({ eligible: false, enrolment: null, latest_request: { ...request("r", "B", "G1", "REJECTED"), reason: "Blurry photos" } });
  expect(rejected.tone === "error" && rejected.text.includes("Blurry photos"), "the reason is shown");
  const approved = setupStatusCard({ eligible: true, enrolment: { cohort_id: "x", section: "B", choices: {}, class_ids: [], since: "" }, latest_request: null });
  expect(approved.action === "change" && approved.tone === "success", "approved");
  const flat = new Array(100).fill(128);
  const checker = Array.from({ length: 100 }, (_, i) => ((i % 10) + Math.floor(i / 10)) % 2 ? 255 : 0);
  expect(sharpness(flat, 10, 10) === 0 && sharpness(checker, 10, 10) > 1000, "a flat image is blurry, a sharp pattern is not");

  console.log("[5/5] Admin: select by section or group, and the wiring...");
  const list = [request("a", "A", "G1"), request("b", "A", "G2"), request("c", "C", "G1"), request("d", "A", "G1", "APPROVED")];
  expect(choiceLabel("DE-II", { option: "PA", group: "G2" }) === "DE-II: PA G2", "option and group");
  expect(choiceLabel("DE-III", { option: "DP", group: "DP" }) === "DE-III: DP" && choiceLabel("DLDA", { option: "DLDA", group: "DL3" }) === "DLDA: DL3", "no repeated codes");
  expect(selectBy(list, { section: "A" }).join() === "a,b", "by section, waiting only");
  expect(selectBy(list, { setCode: "DE-II", group: "G1" }).join() === "a,c", "by group");
  expect(selectBy(list, { setCode: "DE-III", group: "G1" }).join() === "a,b,c", "the same group code in another set is separate");
  const wizard = readFileSync("src/components/student/SetupWizard.tsx", "utf-8");
  expect(wizard.includes("<ConsentNotice") && wizard.includes("disabled={!draft.consentAccepted}"), "photos only after the notice");
  expect(!/teacher/i.test(wizard), "groups by code only, never by teacher");
  const dashboard = readFileSync("src/pages/StudentDashboard.tsx", "utf-8");
  expect(dashboard.includes('activeNavId === "setup" && renderSetupView()'), "My Setup view");
  const layout = readFileSync("src/components/layout/AppLayout.tsx", "utf-8");
  expect(layout.includes('label: "My Setup"'), "My Setup in the student menu");
  const approvals = readFileSync("src/components/admin/ApprovalsTab.tsx", "utf-8");
  expect(approvals.includes("<SetupRequestsSection"), "setup requests on the approvals page");

  console.log("\n✅ All student setup checks passed.");
}

run().catch((err) => {
  console.error("\n❌ Student setup checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
