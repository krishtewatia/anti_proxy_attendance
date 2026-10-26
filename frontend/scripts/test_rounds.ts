// ENTRY and EXIT rounds on the teacher's live screen: lecture labels, the
// round bar, no frames while no round is open, and the wiring.

import { readFileSync } from "node:fs";
import { lectureLabel, roundActions, shouldSendFrames, type RoundInfo } from "../src/utils/rounds.ts";

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
  const labels = (info: RoundInfo) => roundActions(info).map((a) => a.label).join(" | ");
  expect(labels(base) === "Open ENTRY round | Open EXIT round", "nothing held");
  expect(labels({ ...base, open_round: "ENTRY", held: ["ENTRY"] }) === "Close ENTRY | Open EXIT round", "ENTRY live");
  expect(labels({ ...base, open_round: "EXIT", held: ["ENTRY", "EXIT"] }) === "Reopen ENTRY | Close EXIT", "latecomers: reopen ENTRY");
  expect(!shouldSendFrames(base) && shouldSendFrames({ ...base, open_round: "EXIT" }), "no round, no frames");
  expect(shouldSendFrames(null), "ad-hoc sessions keep sending frames");

  console.log("[3/3] Wiring...");
  const flow = readFileSync("src/pages/TeacherAttendanceFlow.tsx", "utf-8");
  expect(flow.includes("if (!shouldSendFrames(roundInfoRef.current)) return;"), "the frame loop waits for an open round");
  expect(flow.includes("<RoundControls") && flow.includes("if (on) stopCameraStream();"), "round controls and manual mode");
  const controls = readFileSync("src/components/teacher/RoundControls.tsx", "utf-8");
  expect(controls.includes("api.markRound(") && controls.includes("api.changeRound("), "marks and rounds go to the server");

  console.log("\n✅ All rounds checks passed.");
}

run().catch((err) => {
  console.error("\n❌ Rounds checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
