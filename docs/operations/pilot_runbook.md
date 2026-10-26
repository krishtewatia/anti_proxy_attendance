# Pilot runbook

How to run the deployment during the NIET pilot (CSE-DS 3rd year, Sections
A-D). Every command runs from the folder that holds the Terraform state
(`anti_proxy_run`), with the AWS CLI signed in. None of them costs money beyond
the instance itself, which is paid from the credits.

## Before go-live (once)

1. **Always on.** In `infra/terraform/terraform.tfvars` set
   `run_mode = "always_on"`, then run `python infra/scripts/tf.py up`. The
   nightly stop goes away. A t3.small costs about $0.0224 an hour, about $16 a
   month, from the credits; the budget alarm still emails when the credits run
   low. Always on also matters for speed (see "Capacity" below): overnight the
   instance saves up the CPU credits that a day of classes uses.
2. **Alarms.** The same `tf.py up` creates two instance alarms
   (`monitoring.tf`). AWS sends a confirmation email to `alert_email`: click the
   link in it, or the alarms email nobody.
3. **Uptime check.** In the repository settings (Settings → Secrets and
   variables → Actions → Variables), `SITE_URL` is already set. The workflow
   "Uptime" runs every 15 minutes in college hours and GitHub emails you when it
   fails. Set a variable `UPTIME_ENABLED` = `false` to pause it while the
   instance is stopped on purpose.
4. **Restore drill.** `python infra/scripts/tf.py restore-drill` restores the
   newest backup into a throwaway database on this machine (Docker must be
   running) and prints the documents per collection and the newest session
   day. Compare with the live site; if they match, the backups work. Nothing
   on AWS or Atlas is changed and the photo archive is not downloaded.
5. **Go-live reset** (on the day, after the drill):
   `python infra/scripts/tf.py golive-reset`. It
   1. takes a backup and stops if the backup fails;
   2. lists what would be removed and what is kept (administrators, approved
      teachers with their classes, the timetable, subjects, sections and
      settings are kept; all students, their photos and face data, sessions,
      attendance, unapproved teachers and waiting requests are removed);
   3. deletes only after you type the total it listed.

   Students then register from scratch.

## Every day

* `python infra/scripts/tf.py status` shows the run mode, the instance, the
  site and the age of the newest backup (a warning above 26 hours).
* A failed "Uptime" run, or an alarm email: run `python infra/scripts/tf.py
  logs`. If the host failed, AWS has already moved the instance to healthy
  hardware (auto-recover).

## Restoring for real

If data is lost, follow "Backups" in
[docs/deployment/aws.md](../deployment/aws.md#backups): `mongorestore --drop` from the
chosen backup into Atlas, from this machine, with the Atlas access list opened
for this machine's address. Take a fresh backup of the current state first.

## Capacity (load test)

`scripts/load_test.py` runs one period with four sections at once against a
throwaway local copy of the stack limited to about the t3.small's size, and
writes [load_test_results.md](load_test_results.md). It only measures.

What it showed (26 Oct 2026):

* Pages are fast. 280 students opening their dashboard and subject-wise
  attendance in the same minute: p95 at most 0.11 s, no errors. Teachers'
  class overview, register, session sheet and hand marks: p95 at most 0.14 s.
* Recognition is the limit. With four cameras sending at once, the vision
  service uses all the CPU it gets (one vCPU in the test) and each camera gets
  an answer about every 2.9 s (p95 4.5 s). 2 of 172 frames timed out; the
  camera simply sends the next one. In practice a student has to stay in view
  for about 3-5 s instead of about 1 s. The target (p95 under 1.5 s) is not
  met with four cameras at once.
* Opening a round took up to 1.35 s while the cameras were busy (target 1 s).
* The t3.small runs on CPU credits (`cpu_credits = "standard"`: it never costs
  extra, it slows down instead). It earns 24 credits an hour and stores up to
  576; four cameras at once use about 90-120 an hour (1.5-2 vCPU). From a full
  store that lasts about 6-9 hours of back-to-back recognition, so a normal college day fits if
  the instance was on overnight (hence always on). If recognition gets slow
  late in the day, the credits ran out.

Options if the pilot needs faster recognition (not done; each needs a
decision):

* stagger the rounds (ENTRY for A/B, then C/D a minute later);
* a larger instance (t3.medium, 4 GB, about $30 a month from the credits);
* fewer frames per camera (the vision service would see each student less
  often but answer sooner).
