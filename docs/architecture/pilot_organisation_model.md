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
