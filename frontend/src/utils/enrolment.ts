// Student self-setup (section, electives, DLDA group, photos) and its
// approval. Pure helpers only, so they can be tested without a browser.
// Groups are always chosen by code, never by teacher name.

export interface SetupClass {
  class_id: string;
  subject_key: string;
  code: string;
  name: string;
  type: string;
}

export interface SetupSection {
  code: string;
  core_classes: SetupClass[];
}

export interface SetupGroupOption {
  option_code: string;
  name: string;
  groups: string[];
}

export interface SetupGroupSet {
  set_code: string;
  kind: "ELECTIVE" | "WORKSHOP";
  name: string;
  options: SetupGroupOption[];
}

export interface SetupCohort {
  cohort_id: string;
  name: string;
  branch: string;
  year: number;
  semester: string;
  term_id: string;
  sections: SetupSection[];
  group_sets: SetupGroupSet[];
}

export interface SetupOptions {
  cohorts: SetupCohort[];
  not_counted: { code: string; name: string }[];
  consent_version: string;
  photos: { min: number; max: number };
}

export interface GroupChoice {
  option: string;
  group: string;
}

export type RequestStatus = "PENDING" | "APPROVED" | "REJECTED" | "WITHDRAWN" | "SUPERSEDED";

export interface SetupRequest {
  request_id: string;
  kind: "FIRST" | "CHANGE";
  status: RequestStatus;
  cohort_id: string;
  section: string;
  choices: Record<string, GroupChoice>;
  class_ids: string[];
  photo_count: number;
  submitted_at: string;
  decided_at?: string | null;
  reason?: string | null;
}

export interface Enrolment {
  cohort_id: string;
  section: string;
  choices: Record<string, GroupChoice>;
  class_ids: string[];
  since: string;
}

export interface MySetup {
  eligible: boolean;
  enrolment: Enrolment | null;
  latest_request: SetupRequest | null;
}

export interface PhotoCheckResult {
  ok: boolean;
  problems: string[];
  det_score: number | null;
  face_fraction: number | null;
}

export interface AdminSetupRequest extends SetupRequest {
  user_id: string;
  branch: string;
  year: number;
  name: string | null;
  roll_number: string | null;
  email: string | null;
  photo_urls: string[];
  current_photo_url: string | null;
}

export interface SetupCounts {
  branch: string;
  total: number;
  years: { cohort_id: string; year: number; total: number; sections: Record<string, number> }[];
}

export interface SetupRequestList {
  requests: AdminSetupRequest[];
  counts: SetupCounts[];
}

export interface SetupDraft {
  cohortId: string;
  section: string;
  choices: Record<string, GroupChoice>;
  photos: string[];
  consentAccepted: boolean;
}

// The wizard's steps, in order.
export const SETUP_STEPS = ["Year and section", "Core subjects", "Electives and DLDA", "Photos", "Review"] as const;

export function emptyDraft(): SetupDraft {
  return { cohortId: "", section: "", choices: {}, photos: [], consentAccepted: false };
}

// The draft for "Change my setup": the approved data, without photos.
export function draftFromEnrolment(enrolment: Enrolment | null): SetupDraft {
  if (!enrolment) return emptyDraft();
  return { cohortId: enrolment.cohort_id, section: enrolment.section, choices: { ...enrolment.choices }, photos: [], consentAccepted: false };
}

export function cohortOf(options: SetupOptions | null, cohortId: string): SetupCohort | undefined {
  return options?.cohorts.find((c) => c.cohort_id === cohortId);
}

// The section's core classes, as the student sees them pre-ticked.
export function coreClasses(options: SetupOptions | null, cohortId: string, section: string): SetupClass[] {
  return cohortOf(options, cohortId)?.sections.find((s) => s.code === section)?.core_classes ?? [];
}

export function choiceLabel(setCode: string, choice: GroupChoice | undefined): string {
  if (!choice) return `${setCode}: not chosen`;
  // "DE-II: PA G2", but "DE-III: DP" and "DLDA: DL3" where the option says nothing more.
  const plain = choice.option === choice.group || choice.option === setCode;
  return plain ? `${setCode}: ${choice.group}` : `${setCode}: ${choice.option} ${choice.group}`;
}

// The first thing missing for a step, in the words shown to the student, or null.
export function stepProblem(step: number, draft: SetupDraft, options: SetupOptions | null, isChange: boolean): string | null {
  const cohort = cohortOf(options, draft.cohortId);
  if (step >= 0) {
    if (!cohort) return "Choose your year.";
    if (!cohort.sections.some((s) => s.code === draft.section)) return "Choose your section.";
  }
  if (step >= 2 && cohort) {
    for (const set of cohort.group_sets) {
      const choice = draft.choices[set.set_code];
      const option = set.options.find((o) => o.option_code === choice?.option);
      if (!choice || !option || !option.groups.includes(choice.group)) return `Choose your ${set.set_code} option and group.`;
    }
  }
  if (step >= 3) {
    const { min, max } = options?.photos ?? { min: 2, max: 3 };
    const needed = !isChange || draft.photos.length > 0;
    if (needed && (draft.photos.length < min || draft.photos.length > max)) return `Add ${min} or ${max} photos of your face.`;
    if (draft.photos.length > 0 && !draft.consentAccepted) return "Read the notice about your photos and tick that you accept it.";
  }
  return null;
}

export function requestBody(draft: SetupDraft, consentVersion: string) {
  return {
    cohort_id: draft.cohortId,
    section: draft.section,
    choices: draft.choices,
    photos: draft.photos,
    ...(draft.photos.length > 0 ? { consent_version: consentVersion } : {}),
  };
}

export interface StatusCard {
  tone: "info" | "warning" | "success" | "error";
  title: string;
  text: string;
  action: "start" | "change" | "withdraw" | null;
}

// What the dashboard says about the student's setup.
export function setupStatusCard(status: MySetup | null): StatusCard {
  const latest = status?.latest_request ?? null;
  if (latest?.status === "PENDING") {
    return {
      tone: "warning",
      title: "Waiting for approval",
      text: latest.kind === "CHANGE"
        ? "Your change was sent. Your approved setup stays in use until an administrator approves the change."
        : "Your setup was sent. You will be on the attendance list once an administrator approves it.",
      action: "withdraw",
    };
  }
  if (status?.eligible && status.enrolment) {
    const rejected = latest?.status === "REJECTED" ? ` Your last change was not approved: ${latest.reason ?? ""}` : "";
    return { tone: "success", title: "Approved: you are on the attendance list", text: `Section ${status.enrolment.section}.${rejected}`, action: "change" };
  }
  if (latest?.status === "REJECTED") {
    return { tone: "error", title: "Your setup was not approved", text: `Reason: ${latest.reason ?? "—"}. Correct it and send it again.`, action: "start" };
  }
  return {
    tone: "info",
    title: "Set up your classes and photos",
    text: "Choose your section, electives and DLDA group, and add 2 or 3 photos of your face. You are not on the attendance list until an administrator approves it.",
    action: "start",
  };
}

// A sharpness score for a greyscale image: the variance of its Laplacian.
// Low means blurry. Advice only; the server decides what is accepted.
export function sharpness(gray: ArrayLike<number>, width: number, height: number): number {
  if (width < 3 || height < 3) return 0;
  let sum = 0;
  let sumSq = 0;
  let n = 0;
  for (let y = 1; y < height - 1; y++) {
    for (let x = 1; x < width - 1; x++) {
      const i = y * width + x;
      const lap = gray[i - width] + gray[i + width] + gray[i - 1] + gray[i + 1] - 4 * gray[i];
      sum += lap;
      sumSq += lap * lap;
      n += 1;
    }
  }
  const mean = sum / n;
  return sumSq / n - mean * mean;
}

export const BLURRY_BELOW = 60;

// Requests the admin selects with "all in this section" or "all in this group".
export function selectBy(requests: AdminSetupRequest[], filter: { section?: string; setCode?: string; group?: string }): string[] {
  return requests
    .filter((r) => r.status === "PENDING")
    .filter((r) => !filter.section || r.section === filter.section)
    .filter((r) => !filter.setCode || (r.choices[filter.setCode] && (!filter.group || r.choices[filter.setCode].group === filter.group)))
    .map((r) => r.request_id);
}
