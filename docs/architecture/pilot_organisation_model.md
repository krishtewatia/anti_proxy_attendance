# Pilot organisation model (NIET CSE-DS, 3rd year, Semester V)

The model the NIET pilot runs on. The full design, with the phases and the open
questions, is the Notion page "NIET pilot (CSE-DS, 3rd year) — design proposal".
This page describes what is built so far.

## Concepts

| Concept | Collection | What it is |
|---|---|---|
| Term | `org_terms` | An academic term, e.g. `2026-27-ODD`. The next semester rolls over by adding a term. |
| Branch | `org_branches` | e.g. `CSE-DS`. |
| Cohort | `org_cohorts` | One year of a branch in a term: CSE-DS, 3rd year, Semester V, 2026-27 Odd. |
| Section | `org_sections` | A, B, C, D of a cohort. |
| Group set | `org_group_sets` | Year-wide groups of a cohort, of two independent kinds (below). |
| Subject | `catalog_subjects` | Catalog entry: stable key, official ERP code, name, type, tracked or not, code status. |
| Class | `org_classes` | A subject taught to one audience in a term: one section, or one group of a group set. Teachers, timetable slots and attendance attach to classes. |
| Timetable version | `timetable_versions` | One imported sheet; DRAFT until activated from a date. |
| Timetable slot | `timetable_slots` | Day, time, periods, room and flags of one class in one version. |

### Two kinds of year-wide groups

Year-wide groups belong to the cohort, not to a section, because they mix
students of all four sections.

- **Elective sets**, `kind = ELECTIVE`: DE-II = Predictive Analytics (groups
  G1, G2, G3) or Advance Java (group AJ); DE-III = Product Analytics (G1, G2,
  G3) or Design Pattern (DP). The lab of an option is taught to the same group.
- **Workshop sets**, `kind = WORKSHOP`: DLDA groups DL1 to DL4.

A student chooses one option and one group in each set. Only the option and
group pairs a set lists are valid, and the sets are independent: Predictive
Analytics G1 and Product Analytics G1 are different groups of students.

### Subjects

The ERP (Juno) codes are the official ones. Codes known only in part are
`INCOMPLETE`; a code that differs from the timetable sheet is `MISMATCH`
(Computer Networks Lab: ERP `BCSE0552A`, sheet `BCSE0552B`). Subjects outside
this system (BVAC0551, MOOCs) are in the catalog with `tracked = false`: never
counted, never given slots. Research Methodology's lab slots (`RM_LAB` in the
sheet) belong to BCSCC0552.

No teacher is assigned anywhere; class `teacher_ids` start empty and faculty
data is added later.

## Timetable import

Columns: `scope, group, day, start, end, periods, subject_short, subject_name,
room, note`. `scope = ALL` rows are year-wide group classes (the `group` column
names the group); other rows name a section.

The import first checks the whole sheet. Errors stop it and store nothing:
unknown day, subject, section or group; a group that is not a group of that
subject's option; a section row with a group, or a group subject on a section
row; an untracked subject; invalid times or periods; two slots for the same
audience at overlapping times. Flags are stored with the slot and shown to
the administrator:

| Flag | Meaning |
|---|---|
| `CONFIRM` | The sheet's note asks for confirmation. |
| `INCOMPLETE_CODE` / `CODE_MISMATCH` | From the subject's code status. |
| `NO_ROOM` | The sheet gives no room. |
| `CLASH` | A section slot at the same time as a year-wide group slot, or groups of different sets at the same time. |
| `PERIODS_CHECK` | The duration does not fit the number of periods. |

A stored import is a DRAFT version. Activating it from a date puts it in force
from that day; the timetable for any day is the active version with the latest
effective date not after it, so a change in the middle of the semester never
alters earlier lectures. Classes belong to the term, not to a version, so a new
version keeps their teachers and attendance.

## How to use it

```bash
python -m app.tools.seed_pilot --timetable                 # check only
python -m app.tools.seed_pilot --timetable --apply         # store as a draft
python -m app.tools.seed_pilot --timetable --apply --activate 2026-11-02
```

Or, as an administrator, through `/api/v1/admin/org/*`: `seed-pilot`,
`structure`, `subjects`, `classes`, `timetable/import` (CSV as the request
body, `dry_run=true` by default), `timetable/versions`,
`timetable/versions/{id}/slots`, `timetable/versions/{id}/activate`.

The older flat class and subject model still drives today's screens; later
pilot PRs move them onto this model.

## Student setup and approval (enrolment)

A student signs up with name, roll number (digits only), college email and
password, and can sign in at once. Under **My Setup** they choose, in one
request:

1. year (cohort) and section; the section's core classes follow from its
   timetable and are shown pre-ticked;
2. one option + group in each elective set (DE-II, DE-III), by code only;
3. the DLDA workshop group;
4. 2 or 3 face photos, after accepting the photo notice.

| Collection | Holds |
| --- | --- |
| `enrolment_requests` | One per submission: section, choices, class ids, photo count, the face template (until decided), kind (FIRST or CHANGE), status (PENDING, APPROVED, REJECTED, WITHDRAWN, SUPERSEDED), reason. Photos wait under `uploads/enrolment_requests/<request_id>/`. |
| `enrolments` | The approved setup in force, one per student and term: section, choices, class ids. |

**Eligibility.** The account status stays the eligibility flag: a student
whose status is PENDING can sign in and use their own dashboard and setup, but
is on no roster and class list, and their face is not in the gallery. A
pending teacher still cannot sign in.

**Photo checks** use the vision service unchanged: a face is found, the
detector's confidence is at least 0.6, the face's shorter side is at least
25% of the image's shorter side (image size read from the PNG/JPEG header),
and every pair of photos has cosine similarity of at least 0.50 (the standard
classroom threshold, ADR-007). The vision service does not count faces, so
"only this student in the photo" is checked by the administrator's photo grid.
The stored template is the normalised mean of the photos' embeddings.

**Approval** (one by one or in bulk, each audited): the first request makes
the student eligible (account APPROVED, template ACTIVE, enrolment written,
first photo becomes the profile photo). A change keeps the approved setup and
template until it is approved. Rejecting needs a reason, keeps the account and
deletes the waiting photos. The 14-day purge never removes a student whose
request is waiting.

## Official section list and bulk approval

An administrator uploads the college's section list per cohort (Academic
Setup → Section lists). Columns: `roll_no, name, email, section, de2, de3,
dlda` (common header names such as "Roll No" or "DE-II" are accepted; a group
is written `PA G2`, `PA-G2`, `PA/G2`, or alone when it belongs to one option,
e.g. `AJ`, `DP`, `DL3`). The file is always checked first; a list with any
error is not stored. One list per cohort (`section_lists`), replaced by a new
upload, deletable; audit entries hold counts only.

The match report is computed on demand, by roll number:

| Category | Meaning |
| --- | --- |
| MATCH | waiting request; section, DE-II, DE-III, DLDA and email agree with the list |
| DIFFERENT | waiting request; section or a group differs (both shown) |
| EMAIL_DIFFERS | roll number on the list, but registered with another email |
| NOT_ON_LIST | waiting request, roll number not on the list |
| NO_REQUEST | registered, no setup sent |
| NOT_REGISTERED | on the list, no account |
| APPROVED_AGREES / APPROVED_DIFFERS | already approved; agrees or not |

A name that differs only in spaces or case is not a difference; another
spelling is a warning. Under Pending Approvals each request shows its
category; "Approve all matching" first shows the matching requests' photos,
then approves them through a route that re-checks every request and approves
none if any no longer matches. Each approval is audited with `via:
section_list`.
