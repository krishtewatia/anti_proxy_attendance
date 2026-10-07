import {
  getFaceOverlayStyle,
  hasSpoof,
  LIVENESS_UNAVAILABLE_LABEL,
  SPOOF_LABEL,
} from "../src/utils/faceOverlay.ts";

function expect(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

async function runFaceOverlayTests() {
  console.log("==================================================");
  console.log("   Camera Overlay: Recognized / Unknown / Spoof   ");
  console.log("==================================================");

  console.log("\n[1/5] A spoof is labelled 'Spoof detected', in red, without the student's name...");
  const spoof = getFaceOverlayStyle({
    status: "spoof",
    name: "Asha Verma",
    similarity: 0.93,
    confidence_percent: 93.0,
  });
  expect(spoof.kind === "spoof", `expected kind spoof, got ${spoof.kind}`);
  expect(spoof.label === SPOOF_LABEL && spoof.label === "Spoof detected", `unexpected label ${spoof.label}`);
  expect(!spoof.label.includes("Asha"), "a spoof must not be shown under the student's name");
  expect(!spoof.label.includes("93"), "a spoof must not show a match percentage");
  expect(spoof.strokeColor === "#dc2626", `expected a red box, got ${spoof.strokeColor}`);

  console.log("[2/5] A face whose liveness could not be checked is not shown as a student...");
  const unavailable = getFaceOverlayStyle({ status: "liveness_unavailable", name: "Asha Verma" });
  expect(unavailable.kind === "liveness_unavailable", `unexpected kind ${unavailable.kind}`);
  expect(unavailable.label === LIVENESS_UNAVAILABLE_LABEL, `unexpected label ${unavailable.label}`);
  expect(!unavailable.label.includes("Asha"), "must not be shown under the student's name");

  console.log("[3/5] A recognized student keeps the green box with name and percentage...");
  const recognized = getFaceOverlayStyle({ status: "recognized", name: "Asha Verma", confidence_percent: 91.24 });
  expect(recognized.kind === "recognized", `unexpected kind ${recognized.kind}`);
  expect(recognized.label === "Asha Verma (91.2%)", `unexpected label '${recognized.label}'`);
  expect(recognized.strokeColor === "#10b981", `expected green, got ${recognized.strokeColor}`);
  const fromSimilarity = getFaceOverlayStyle({ status: "recognized", name: "Asha Verma", similarity: 0.875 });
  expect(fromSimilarity.label === "Asha Verma (87.5%)", `unexpected label '${fromSimilarity.label}'`);

  console.log("[4/5] Unknown and unverified faces stay amber and are labelled UNKNOWN...");
  for (const face of [
    { status: "unknown", name: "UNKNOWN", similarity: 0.2 },
    { status: "unverified", name: "UNKNOWN" },
    { status: "recognized", name: null },
    { status: "recognized", name: "UNKNOWN" },
  ]) {
    const style = getFaceOverlayStyle(face);
    expect(style.kind === "unknown", `expected unknown for ${JSON.stringify(face)}, got ${style.kind}`);
    expect(style.label.startsWith("UNKNOWN"), `unexpected label '${style.label}'`);
    expect(style.strokeColor === "#f59e0b", `expected amber, got ${style.strokeColor}`);
  }

  console.log("[5/5] hasSpoof is true only when a face was blocked as a spoof...");
  expect(hasSpoof([{ status: "recognized", name: "A" }, { status: "spoof", name: "B" }]), "expected true");
  expect(!hasSpoof([{ status: "recognized", name: "A" }, { status: "unknown" }]), "expected false");
  expect(!hasSpoof([{ status: "liveness_unavailable" }]), "unavailable is not a spoof");
  expect(!hasSpoof([]) && !hasSpoof(undefined) && !hasSpoof(null), "expected false for no faces");

  console.log("\nAll camera overlay tests passed.");
}

runFaceOverlayTests().catch((error) => {
  console.error("Camera overlay tests failed:", error);
  process.exit(1);
});
