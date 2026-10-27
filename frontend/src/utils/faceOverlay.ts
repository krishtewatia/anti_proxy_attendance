// How one face returned by the frame endpoint is drawn on the teacher's camera view.

export interface OverlayFace {
  name?: string | null;
  status?: string;
  similarity?: number;
  confidence_percent?: number;
  // What the server did with a recognised face (absent on older responses).
  mark_status?: string;
  mark_reason?: string;
}

// Why a recognised face was not marked, in the teacher's words; null when it was.
export function notMarkedReason(face: OverlayFace): string | null {
  if (face.status !== "recognized" || face.mark_status !== "rejected") return null;
  if (face.mark_reason === "not_on_roster") return "not in this class";
  if (face.mark_reason === "no_round_open") return "open ENTRY or EXIT first";
  return "not marked";
}

// True when the server marked (or had already marked) this face present.
export function isMarked(face: OverlayFace): boolean {
  return (
    face.status === "recognized" &&
    !!face.name &&
    face.name !== "UNKNOWN" &&
    (face.mark_status === undefined || face.mark_status === "marked" || face.mark_status === "already_present")
  );
}

// Recognised faces that are not on this class's list.
export function countNotInClass(faces: OverlayFace[] | undefined | null): number {
  return Array.isArray(faces) ? faces.filter((f) => notMarkedReason(f) === "not in this class").length : 0;
}

export interface FaceOverlayStyle {
  kind: "recognized" | "spoof" | "liveness_unavailable" | "unknown";
  label: string;
  strokeColor: string;
  bgColor: string;
}

export const SPOOF_LABEL = "Spoof detected";
export const LIVENESS_UNAVAILABLE_LABEL = "Liveness check unavailable";

export function getFaceOverlayStyle(face: OverlayFace): FaceOverlayStyle {
  // A face the vision service refused to sign is never shown as a student,
  // even though the response says whose face was presented.
  if (face.status === "spoof") {
    return {
      kind: "spoof",
      label: SPOOF_LABEL,
      strokeColor: "#dc2626",
      bgColor: "rgba(220, 38, 38, 0.94)",
    };
  }
  if (face.status === "liveness_unavailable") {
    return {
      kind: "liveness_unavailable",
      label: LIVENESS_UNAVAILABLE_LABEL,
      strokeColor: "#dc2626",
      bgColor: "rgba(220, 38, 38, 0.94)",
    };
  }

  const isRecognized = face.status === "recognized" && !!face.name && face.name !== "UNKNOWN";
  const pct =
    face.confidence_percent != null
      ? `${face.confidence_percent.toFixed(1)}%`
      : face.similarity != null
      ? `${(face.similarity * 100).toFixed(1)}%`
      : "";
  const name = isRecognized ? face.name! : "UNKNOWN";
  const reason = notMarkedReason(face);
  if (isRecognized && reason) {
    // Recognised, but nobody was marked: amber, with the reason.
    return {
      kind: "unknown",
      label: `${name} · ${reason}`,
      strokeColor: "#f59e0b",
      bgColor: "rgba(245, 158, 11, 0.92)",
    };
  }

  return {
    kind: isRecognized ? "recognized" : "unknown",
    label: `${name} ${pct ? `(${pct})` : ""}`,
    strokeColor: isRecognized ? "#10b981" : "#f59e0b",
    bgColor: isRecognized ? "rgba(16, 185, 129, 0.92)" : "rgba(245, 158, 11, 0.92)",
  };
}

// True when at least one face in the frame was blocked as a spoof.
export function hasSpoof(faces: OverlayFace[] | undefined | null): boolean {
  return Array.isArray(faces) && faces.some((f) => f.status === "spoof");
}
