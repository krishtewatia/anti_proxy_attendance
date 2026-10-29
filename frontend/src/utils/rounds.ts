// ENTRY and EXIT rounds of a timetable session. Pure helpers only.

export type RoundName = "ENTRY" | "EXIT";
export const ROUND_NAMES: RoundName[] = ["ENTRY", "EXIT"];

export interface RoundState {
  opened_at: string | null;
  closed_at: string | null;
  times_opened: number | null;
  finalized_at?: string | null;
  editable_until?: string | null;
  may_edit?: boolean;
}

export interface RoundInfo {
  periods: number;
  open_round: RoundName | null;
  held: RoundName[];
  rounds: Record<RoundName, RoundState>;
  // Both rounds finalized: the class's attendance is final.
  complete?: boolean;
  next_step?: RoundName | "FINALIZE";
  editable_until?: string | null;
  teacher_may_edit?: boolean;
}

// "1/2" style label for a student's lectures.
export function lectureLabel(lectures: string[] | null | undefined, periods: number): string {
  const list = lectures ?? [];
  const total = list.length || periods;
  return `${list.filter((l) => l === "P").length}/${total}`;
}

// What the teacher does next (from the server, or worked out from the rounds).
export function nextStep(info: RoundInfo): RoundName | "FINALIZE" {
  if (info.next_step) return info.next_step;
  if (!info.rounds.ENTRY?.finalized_at) return "ENTRY";
  return info.rounds.EXIT?.finalized_at ? "FINALIZE" : "EXIT";
}

// The round the teacher is working on: the next one to finalize, or EXIT once both are done.
export function focusRound(info: RoundInfo): RoundName {
  return nextStep(info) === "ENTRY" ? "ENTRY" : "EXIT";
}

export type CardState = "waiting" | "not_started" | "paused" | "live" | "finalized" | "locked";

// Where a round stands, for its card on the class page.
export function roundCardState(info: RoundInfo, round: RoundName): CardState {
  const state = info.rounds[round];
  if (state?.finalized_at) return state.may_edit === false ? "locked" : "finalized";
  if (round === "EXIT" && !info.rounds.ENTRY?.finalized_at) return "waiting";
  if (info.open_round === round) return "live";
  return info.held.includes(round) ? "paused" : "not_started";
}

export interface CardAction {
  label: string;
  kind: "open" | "finalize";
  disabled: boolean;
}

// The button on a round's card. While the class is running a round is opened on
// its own camera page; once the class has ended an unfinished round can only be
// finalized (its marks are then corrected on the final attendance).
export function cardAction(info: RoundInfo, round: RoundName, running: boolean): CardAction | null {
  const state = roundCardState(info, round);
  if (state === "finalized" || state === "locked") return null;
  if (state === "waiting") return { label: `Open ${round}`, kind: "open", disabled: true };
  if (!running) return { label: `Finalize ${round}`, kind: "finalize", disabled: false };
  if (state === "live") return { label: `Return to ${round}`, kind: "open", disabled: false };
  return { label: state === "paused" ? `Resume ${round}` : `Open ${round}`, kind: "open", disabled: false };
}

// Hand changes: only on the final attendance (both rounds finalized), per round while its window lasts.
export function canEditFinal(info: RoundInfo, round: RoundName): boolean {
  return Boolean(info.complete) && info.rounds[round]?.may_edit !== false;
}

// What a teacher is told once the window has passed (the server says the same).
export const EDIT_WINDOW_CLOSED_TEXT =
  "Your time window for marking present in this session has passed. Please contact the admin.";

// The window has passed for both rounds: only an administrator can change the class now.
export function editWindowClosed(info: RoundInfo): boolean {
  return Boolean(info.complete) && ROUND_NAMES.every((r) => info.rounds[r]?.may_edit === false);
}

// One line about a round: live, waiting, or finalized and until when it may change by hand.
export function roundStatusText(info: RoundInfo, round: RoundName, formatTime: (iso: string) => string): string {
  const state = info.rounds[round];
  if (state?.finalized_at) {
    if (state.may_edit === false) return `✓ finalized ${formatTime(state.finalized_at)} · locked`;
    return state.editable_until
      ? `✓ finalized ${formatTime(state.finalized_at)} · editable by hand until ${formatTime(state.editable_until)}`
      : `✓ finalized ${formatTime(state.finalized_at)}`;
  }
  if (info.open_round === round) return "live: the camera is marking";
  if (round === "EXIT" && !info.rounds.ENTRY?.finalized_at) return "after ENTRY is finalized";
  return info.held.includes(round) ? "paused" : "not started";
}

interface MarkedStudent {
  identity: string;
  student_name?: string | null;
  roll_number?: string | null;
  rounds?: Partial<Record<RoundName, { status: string | null; at?: string | null } | undefined>> | null;
}

// Present in a round (newest mark first) and still absent (by roll number).
export function splitByRound<T extends MarkedStudent>(records: T[], round: RoundName, query = ""): { present: T[]; absent: T[] } {
  const q = query.trim().toLowerCase();
  const shown = records.filter(
    (r) => !q || (r.student_name ?? "").toLowerCase().includes(q) || (r.roll_number ?? "").toLowerCase().includes(q),
  );
  const byRoll = (a: T, b: T) => (a.roll_number ?? "").localeCompare(b.roll_number ?? "");
  const present = shown.filter((r) => r.rounds?.[round]?.status === "PRESENT");
  const absent = shown.filter((r) => r.rounds?.[round]?.status !== "PRESENT").sort(byRoll);
  present.sort((a, b) => (b.rounds?.[round]?.at ?? "").localeCompare(a.rounds?.[round]?.at ?? "") || byRoll(a, b));
  return { present, absent };
}

// A student's final result, only once both rounds are finalized.
export function finalLabel(lectures: string[] | null | undefined, info: RoundInfo): string {
  return info.complete ? lectureLabel(lectures, info.periods) : "final after EXIT";
}

// Recognition only marks while a round is open: no frames are sent otherwise.
export function shouldSendFrames(info: RoundInfo | null): boolean {
  return info === null || info.open_round !== null;
}
