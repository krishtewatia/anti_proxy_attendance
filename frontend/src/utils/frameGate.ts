// Which camera frames are worth sending for recognition.
//
// Each camera keeps one frame in flight. Without this gate it sends a new frame
// as soon as the last answer is back, even when nothing changed (an empty
// doorway, a student already marked still standing there). Those frames cost
// the vision service as much as useful ones and make the other cameras wait.
// A frame is sent when the picture changed, while a face in view still needs
// recognising, or as a heartbeat; otherwise it is skipped.

import { isMarked, type OverlayFace } from "./faceOverlay.ts";

export const THUMB_WIDTH = 32;
export const THUMB_HEIGHT = 24;
// Mean difference per pixel (0-255) above which the picture "changed".
export const CHANGE_THRESHOLD = 6;
// Send at least this often, so nobody is missed if the change check is fooled.
export const HEARTBEAT_MS = 3000;

// A tiny grey copy of RGBA pixels (as read from a THUMB_WIDTH x THUMB_HEIGHT canvas).
export function greyThumbnail(rgba: ArrayLike<number>): Uint8Array {
  const out = new Uint8Array(rgba.length / 4);
  for (let i = 0; i < out.length; i++) {
    out[i] = (rgba[i * 4] * 77 + rgba[i * 4 + 1] * 150 + rgba[i * 4 + 2] * 29) >> 8;
  }
  return out;
}

// Mean absolute difference per pixel between two thumbnails (255 when there is no earlier one).
export function thumbnailDifference(a: Uint8Array | null, b: Uint8Array | null): number {
  if (!a || !b || a.length !== b.length || a.length === 0) return 255;
  let total = 0;
  for (let i = 0; i < a.length; i++) total += Math.abs(a[i] - b[i]);
  return total / a.length;
}

// True when the last answer had a face that may still be marked by another frame:
// one not recognised (a better angle may help) or recognised but not yet marked
// for a reason another frame can change.
export function faceNeedsAnotherLook(faces: OverlayFace[] | null | undefined): boolean {
  if (!Array.isArray(faces)) return false;
  return faces.some((f) => {
    if (f.status === "unknown" || f.status === "unverified") return true;
    if (f.status !== "recognized" || isMarked(f)) return false;
    // "Not in this class" does not change from frame to frame; the heartbeat retries it.
    return f.mark_reason !== "not_on_roster";
  });
}

export interface GateInput {
  difference: number;
  needsAnotherLook: boolean;
  msSinceSent: number;
}

export function shouldSend({ difference, needsAnotherLook, msSinceSent }: GateInput): boolean {
  return difference >= CHANGE_THRESHOLD || needsAnotherLook || msSinceSent >= HEARTBEAT_MS;
}
