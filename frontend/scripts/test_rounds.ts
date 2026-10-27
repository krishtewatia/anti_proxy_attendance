// ENTRY and EXIT rounds on the teacher's live screen: lecture labels, the
// round bar, no frames while no round is open, and the wiring.

import { readFileSync } from "node:fs";
import { finalLabel, lectureLabel, roundStatusText, shouldSendFrames, splitByRound, stepActions, type RoundInfo } from "../src/utils/rounds.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
}

const base: RoundInfo = {
  periods: 2,
  open_round: null,
  held: [],
  rounds: { ENTRY: { opened_at: null, closed_at: null, times_opened: null }, EXIT: { opened_at: null, closed_at: null, times_opened: null } },
};

async function run() {
  console.log("==================================================");
  console.log("   Rounds: ENTRY And EXIT                         ");
  console.log("==================================================");

  console.log("\n[1/3] Lecture labels...");
  expect(lectureLabel(["P", "A"], 2) === "1/2" && lectureLabel(["P"], 1) === "1/1", "labels");
  expect(lectureLabel(null, 2) === "0/2", "nothing marked yet");

  console.log("[2/3] The round bar and frames...");
  // The steps: ENTRY (start, finalize), then EXIT, then the session.
  const labels = (info: RoundInfo) => stepActions(info).map((a) => a.label).join(" | ");
  const done = (at: string) => ({ opened_at: at, closed_at: at, times_opened: 1, finalized_at: at, may_edit: true, editable_until: "2026-11-03T10:00:00Z" });
  expect(labels({ ...base, next_step: "ENTRY" }) === "Start ENTRY | Finalize ENTRY", "first: start ENTRY");
  expect(labels({ ...base, next_step: "ENTRY", open_round: "ENTRY", held: ["ENTRY"] }) === "Finalize ENTRY | Pause camera", "ENTRY live");
  expect(labels({ ...base, next_step: "ENTRY", held: ["ENTRY"] }) === "Resume ENTRY | Finalize ENTRY", "ENTRY paused");
  const afterEntry: RoundInfo = { ...base, next_step: "EXIT", held: ["ENTRY"], rounds: { ...base.rounds, ENTRY: done("2026-11-02T10:00:00Z") } };
  expect(labels(afterEntry) === "Start EXIT | Finalize EXIT", "then EXIT");
  expect(labels({ ...afterEntry, next_step: "FINALIZE", complete: true }) === "", "both done: only the session is left");
  const time = (iso: string) => iso.slice(11, 16);
  expect(roundStatusText(afterEntry, "ENTRY", time) === "✓ finalized 10:00 · editable by hand until 10:00", "a finalized round says until when");
  expect(roundStatusText({ ...afterEntry, rounds: { ...afterEntry.rounds, ENTRY: { ...done("2026-11-02T10:00:00Z"), may_edit: false } } }, "ENTRY", time).endsWith("locked"), "then locked");
  expect(roundStatusText(base, "EXIT", time) === "after ENTRY is finalized", "EXIT waits for ENTRY");
  const people = [
    { identity: "a", student_name: "Asha", roll_number: "2", rounds: { ENTRY: { status: "PRESENT", at: "2026-11-02T10:01:00Z" } } },
    { identity: "b", student_name: "Bilal", roll_number: "1", rounds: { ENTRY: { status: "PRESENT", at: "2026-11-02T10:03:00Z" } } },
    { identity: "c", student_name: "Chen", roll_number: "3", rounds: null },
  ];
  const split = splitByRound(people, "ENTRY");
  expect(split.present.map((p) => p.identity).join() === "b,a" && split.absent.map((p) => p.identity).join() === "c", "present newest first, absent by roll");
  expect(splitByRound(people, "EXIT").absent.length === 3, "EXIT: everyone still absent");
  expect(splitByRound(people, "ENTRY", "ash").present.length === 1, "search filters both lists");
  expect(finalLabel(["P"], { ...base, complete: false }) === "final after EXIT" && finalLabel(["P"], { ...base, complete: true }) === "1/1", "final only when both are done");
  expect(!shouldSendFrames(base) && shouldSendFrames({ ...base, open_round: "EXIT" }), "no round, no frames");
  expect(shouldSendFrames(null), "ad-hoc sessions keep sending frames");

  console.log("[3/3] Wiring...");
  const flow = readFileSync("src/pages/TeacherAttendanceFlow.tsx", "utf-8");
  expect(flow.includes("if (!shouldSendFrames(roundInfoRef.current)) return;"), "the frame loop waits for an open round");
  expect(flow.includes("<RoundControls") && flow.includes("if (on) stopCameraStream();"), "round controls and manual mode");
  const controls = readFileSync("src/components/teacher/RoundControls.tsx", "utf-8");
  expect(controls.includes("api.markRound(") && controls.includes("api.changeRound(") && controls.includes("api.finalizeRound("), "marks, rounds and finalizing go to the server");
  expect(flow.includes("disabled={loading || (roundInfo !== null && !roundInfo.complete)}"), "the session is finalized only after both rounds");

  console.log("\n✅ All rounds checks passed.");
}

run().catch((err) => {
  console.error("\n❌ Rounds checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
