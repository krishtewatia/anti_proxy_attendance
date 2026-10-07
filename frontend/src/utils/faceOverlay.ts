// How one face returned by the frame endpoint is drawn on the teacher's camera view.

export interface OverlayFace {
  name?: string | null;
  status?: string;
  similarity?: number;
  confidence_percent?: number;
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
