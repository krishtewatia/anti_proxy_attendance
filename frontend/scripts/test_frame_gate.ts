// The frame gate: which camera frames are worth sending for recognition.

import { readFileSync } from "node:fs";
import {
  CHANGE_THRESHOLD,
  faceNeedsAnotherLook,
  greyThumbnail,
  HEARTBEAT_MS,
  shouldSend,
  thumbnailDifference,
} from "../src/utils/frameGate.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
  console.log(`  ✓ ${message}`);
}

function rgba(value: (i: number) => number, pixels = 32 * 24): Uint8Array {
  const out = new Uint8Array(pixels * 4);
  for (let i = 0; i < pixels; i++) out.set([value(i), value(i), value(i), 255], i * 4);
  return out;
}

async function run(): Promise<void> {
  console.log("Frame gate checks");
  // The same cases are checked by the load test's Python copy of the rule.
  const vectors = JSON.parse(readFileSync(new URL("./frame_gate_vectors.json", import.meta.url), "utf-8"));
  for (const v of vectors) {
    expect(shouldSend(v) === v.send, `${v.case}: ${v.send ? "sent" : "skipped"}`);
  }

  const grey = greyThumbnail(rgba(() => 100));
  expect(grey.length === 32 * 24 && grey.every((p) => Math.abs(p - 100) <= 1), "a grey copy of the pixels");
  const same = greyThumbnail(rgba(() => 101));
  const person = greyThumbnail(rgba((i) => (i % 32 > 10 && i % 32 < 20 ? 30 : 100)));
  expect(thumbnailDifference(grey, same) < CHANGE_THRESHOLD, "a tiny light change is not a change");
  expect(thumbnailDifference(grey, person) >= CHANGE_THRESHOLD, "someone in the doorway is a change");
  expect(thumbnailDifference(null, grey) === 255, "the first frame always counts as changed");

  expect(faceNeedsAnotherLook([{ status: "unknown" }]), "an unrecognised face needs another look");
  expect(!faceNeedsAnotherLook([{ status: "recognized", name: "A", mark_status: "marked" }]), "a marked face does not");
  expect(!faceNeedsAnotherLook([{ status: "recognized", name: "A", mark_status: "rejected", mark_reason: "not_on_roster" }]), "not in this class waits for the heartbeat");
  expect(faceNeedsAnotherLook([{ status: "recognized", name: "A", mark_status: "rejected", mark_reason: "no_round_open" }]), "no round open keeps trying");
  expect(!faceNeedsAnotherLook(null) && !faceNeedsAnotherLook([]), "no faces, nothing to look at");
  expect(HEARTBEAT_MS === 3000, "a heartbeat every 3 s");

  const flow = readFileSync(new URL("../src/pages/TeacherAttendanceFlow.tsx", import.meta.url), "utf-8");
  const gate = flow.indexOf("const send = shouldSend(");
  expect(gate > 0 && gate < flow.indexOf("canvas.toBlob("), "the gate runs before a frame is encoded and sent");
}

run().catch((err) => {
  console.error("\n❌ Frame gate checks failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
