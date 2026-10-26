// Teachers on the timetable: today's slots and their states, the week, and
// the admin's class checklist grouped by section and by group.
// Pure helpers only, so they can be tested without a browser.

import type { Audience, OrgClass } from "./organisation.ts";

export type SlotState = "UPCOMING" | "LIVE" | "DONE" | "NOT_TAKEN";

export interface TeacherSlot {
  slot_id: string;
  class_id: string;
  label: string;
  subject: string;
  code: string;
  audience: Audience;
  day: string;
  start: string;
  end: string;
  periods: number;
  room: string;
  date?: string;
  state?: SlotState;
  session_id?: string | null;
}

export interface TeacherTimetable {
  date: string;
  today: TeacherSlot[];
  week: TeacherSlot[];
  class_count: number;
}

export interface SlotSession {
  session_id: string;
  status: string;
  created: boolean;
  roster_size?: number;
}

export const SLOT_STATE: Record<SlotState, { label: string; badge: string; action: string | null }> = {
  UPCOMING: { label: "Upcoming", badge: "completed", action: "Start session" },
  LIVE: { label: "Live now", badge: "warning", action: "Open" },
  DONE: { label: "Done", badge: "present", action: null },
  NOT_TAKEN: { label: "Not taken", badge: "absent", action: "Start late" },
};

// "Section B" or "DE-II PA G2", as short as possible.
export function audienceShort(audience: Audience): string {
  if (audience.kind === "SECTION") return `Section ${audience.section}`;
  const plain = audience.option_code === audience.group_code || audience.option_code === audience.set_code;
  return `${audience.set_code} ${plain ? audience.group_code : `${audience.option_code} ${audience.group_code}`}`;
}

// The admin's checklist: Section A..D first, then each group, classes by subject.
export function classGroups(classes: OrgClass[]): { title: string; classes: OrgClass[] }[] {
  const groups = new Map<string, OrgClass[]>();
  for (const cls of classes) {
    const title = audienceShort(cls.audience);
    groups.set(title, [...(groups.get(title) ?? []), cls]);
  }
  const rank = (title: string) => (title.startsWith("Section ") ? `0${title}` : `1${title}`);
  return [...groups.entries()]
    .sort((a, b) => rank(a[0]).localeCompare(rank(b[0])))
    .map(([title, list]) => ({ title, classes: list.sort((x, y) => x.subject_key.localeCompare(y.subject_key)) }));
}
