// ENTRY and EXIT rounds of a timetable session. Pure helpers only.

export type RoundName = "ENTRY" | "EXIT";
export const ROUND_NAMES: RoundName[] = ["ENTRY", "EXIT"];

export interface RoundInfo {
  periods: number;
  open_round: RoundName | null;
  held: RoundName[];
  rounds: Record<RoundName, { opened_at: string | null; closed_at: string | null; times_opened: number | null }>;
  editable_until?: string | null;
  teacher_may_edit?: boolean;
}

// "1/2" style label for a student's lectures.
export function lectureLabel(lectures: string[] | null | undefined, periods: number): string {
  const list = lectures ?? [];
  const total = list.length || periods;
  return `${list.filter((l) => l === "P").length}/${total}`;
}

// What the round bar offers for each round.
export function roundActions(info: RoundInfo): { round: RoundName; label: string; action: "open" | "close" }[] {
  return ROUND_NAMES.map((round) => {
    if (info.open_round === round) return { round, label: `Close ${round}`, action: "close" as const };
    const held = info.held.includes(round);
    return { round, label: held ? `Reopen ${round}` : `Open ${round} round`, action: "open" as const };
  });
}

// Recognition only marks while a round is open: no frames are sent otherwise.
export function shouldSendFrames(info: RoundInfo | null): boolean {
  return info === null || info.open_round !== null;
}
