// Teachers on the timetable: the admin's class checklist grouped by section
// and group, today's slot states, and the wiring of Start from the timetable.

import { readFileSync } from "node:fs";
import { SLOT_STATE, audienceShort, classGroups } from "../src/utils/teaching.ts";
import type { OrgClass } from "../src/utils/organisation.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
}

function cls(id: string, subject: string, audience: OrgClass["audience"]): OrgClass {
  return { class_id: id, term_id: "t", cohort_id: "c", subject_key: subject, audience, label: `${subject} ${id}`, teacher_ids: [], status: "ACTIVE" };
}

async function run() {
  console.log("==================================================");
  console.log("   Teachers On The Timetable                      ");
  console.log("==================================================");

  console.log("\n[1/3] The class checklist: sections first, then groups...");
  const groups = classGroups([
    cls("1", "PRED", { kind: "GROUP", set_code: "DE-II", set_kind: "ELECTIVE", option_code: "PA", group_code: "G2" }),
    cls("2", "DCC", { kind: "SECTION", section: "B" }),
    cls("3", "CN", { kind: "SECTION", section: "B" }),
    cls("4", "CN", { kind: "SECTION", section: "A" }),
    cls("5", "DLDA", { kind: "GROUP", set_code: "DLDA", set_kind: "WORKSHOP", option_code: "DLDA", group_code: "DL3" }),
  ]);
  expect(groups.map((g) => g.title).join() === "Section A,Section B,DE-II PA G2,DLDA DL3", `groups: ${groups.map((g) => g.title)}`);
  expect(groups[1].classes.map((c) => c.subject_key).join() === "CN,DCC", "classes by subject");
  expect(audienceShort({ kind: "GROUP", set_code: "DE-III", set_kind: "ELECTIVE", option_code: "DP", group_code: "DP" }) === "DE-III DP", "short group label");

  console.log("[2/3] Today's slot states...");
  expect(SLOT_STATE.UPCOMING.action === "Start session" && SLOT_STATE.LIVE.action === "Open" && SLOT_STATE.DONE.action === null, "actions");
  expect(SLOT_STATE.NOT_TAKEN.action === "Start late", "a missed slot can still be taken");

  console.log("[3/3] Wiring...");
  const today = readFileSync("src/components/teacher/TodayTimetable.tsx", "utf-8");
  expect(today.includes("api.startFromSlot(") && today.includes('session.status === "SCHEDULED"'), "start from a slot, then start the session");
  const flow = readFileSync("src/pages/TeacherAttendanceFlow.tsx", "utf-8");
  expect(flow.includes("<TodayTimetable onOpenSession={handleOpenSlotSession} />"), "Today on the teacher's Home");
  const registry = readFileSync("src/components/admin/TeacherRegistryTab.tsx", "utf-8");
  expect(registry.includes("api.setTeacherClasses(") && registry.includes("Assign classes"), "admin assigns classes");
  expect(registry.includes("Classes in other years and branches stay as they are"), "other cohorts are kept");

  console.log("\n✅ All teaching checks passed.");
}

run().catch((err) => {
  console.error("\n❌ Teaching checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
