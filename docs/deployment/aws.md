# AWS deployment

One EC2 instance in Mumbai runs the production stack
([production_stack.md](production_stack.md)); the database is a free MongoDB
Atlas cluster; HTTPS comes from Caddy and Let's Encrypt on a free DuckDNS name.
Everything is created by Terraform (`infra/terraform`), driven by two Python
scripts in `infra/scripts`.

The first part of this page is a checklist for **Windows PowerShell**. The
second part is reference.

The design assumes an AWS **Free plan** account: usage is paid from credits
and the account cannot be charged. Do not join the account to AWS
Organizations and do not enable IAM Identity Center: either moves it to the
Paid plan.

---

# Checklist: first deployment from Windows PowerShell

Three rules that prevent most problems:

- **One PowerShell window for the whole checklist.** Variables set with
  `$env:` exist only in the window where you typed them. If you open a new
  window, repeat step 3.
- **One folder.** Run everything from the run folder
  (`C:\Users\hp\Downloads\anti_proxy_run`). Terraform remembers what it
  created in a file inside that folder; running `tf.py up` from a second
  clone would create a second copy of everything.
- **When unsure, run preflight** (step 4). It changes nothing and says in
  plain words what is missing.

## Step 1. Tools (once)

```powershell
winget install Hashicorp.Terraform
```

```powershell
winget install Amazon.AWSCLI
```

Close PowerShell and open a new window afterwards, so the new programs are
found. Python 3.10 or newer and Git are already needed for the project.
`make` is not needed: every command below is plain `python`.

## Step 2. Sign-in details (once)

**AWS.** Create an access key for the IAM admin user (never for root), then:

```powershell
aws configure --profile antiproxy
```

It asks four questions: the access key ID, the secret access key, region
`ap-south-1`, output format `json`. Nothing is printed afterwards.

**Atlas.** In the Atlas console: Organization → Access Manager → API Keys →
Create API Key, role **Organization Project Creator**. Copy the public and
the private key (the private key is shown only once). On the same screen add
your current public IP address to the key's access list. Copy the
Organization ID from Organization → Settings.

**Settings file.** In the run folder:

```powershell
cd C:\Users\hp\Downloads\anti_proxy_run
git pull
Copy-Item infra\terraform\terraform.tfvars.example infra\terraform\terraform.tfvars
notepad infra\terraform\terraform.tfvars
```

Fill in `site_host`, `alert_email` and `atlas_org_id`, and remove the `#` in
front of the `acme_ca` line (the staging certificate authority, for the first
runs). Save. The file must stay exactly at
`infra\terraform\terraform.tfvars`; git ignores it there.

## Step 3. Open the window you will work in

Every time you start, in one PowerShell window:

```powershell
cd C:\Users\hp\Downloads\anti_proxy_run
$env:AWS_PROFILE = "antiproxy"
$env:AWS_REGION = "ap-south-1"
$env:MONGODB_ATLAS_PUBLIC_API_KEY = "paste the public key"
$env:MONGODB_ATLAS_PRIVATE_API_KEY = "paste the private key"
```

These lines print nothing. The keys live only in this window and are gone
when it closes; do not put them in a file.

## Step 4. Preflight

```powershell
python infra/scripts/tf.py preflight
```

It checks the folder, the tools, the settings file, the AWS sign-in, the
Atlas key and the published images, and changes nothing. You want every line
to start with `OK` (a `NOTE` is information) and the last line to be:

```
Ready. Next: python infra/scripts/manage_secrets.py init
```

If a line says `MISSING`, the line under it, starting with `->`, is the fix.
Do it and run preflight again.

| `MISSING` line | What to do |
|---|---|
| Terraform / AWS CLI is not installed or not on PATH | Install it (step 1) and open a **new** PowerShell window, then repeat step 3 |
| terraform.tfvars does not exist / is in the wrong place | It must be at `infra\terraform\terraform.tfvars` in **this** folder; preflight prints the `Move-Item` command when it finds it elsewhere |
| ... still has the example value | Edit the file (step 2) |
| the staging certificate line is not on | Remove the `#` in front of `acme_ca` in the file |
| the AWS CLI cannot sign in | `$env:AWS_PROFILE = "antiproxy"` in this window; if it still fails, `aws configure --profile antiproxy` again |
| these are ROOT credentials | Use the IAM admin user's access key |
| MONGODB_ATLAS_..._KEY is not set in this window | The `$env:` lines of step 3, in this window |
| Atlas rejected the API key | A key value is wrong; create a new key if the private one was lost |
| Atlas refused this address or this key's role | Add your current IP to the key's access list in Atlas (it changes when your network changes); the role must be Organization Project Creator |
| this folder is behind origin/main | `git pull` |
| no published image for the newest commit | Wait for the *Publish Images* workflow on GitHub (about 15 minutes after a merge) |

## Step 5. Secrets

```powershell
python infra/scripts/manage_secrets.py init
```

It generates the application's keys, then asks three things. While you type
or paste at a "hidden" prompt **nothing appears on screen**; that is normal.
Press Enter after each.

```
Secrets under /antiproxy/prod (ap-south-1):
  stored JWT_SECRET_KEY
  stored VISION_SERVICE_API_KEY
  stored RECOGNITION_SIGNING_KEY
DuckDNS token (hidden, nothing is shown while you paste):
  stored DUCKDNS_TOKEN
  MONGODB_URL: later. `python infra/scripts/tf.py up` creates the database,
               then stores this one by itself.
First administrator of the deployed site (...):
  Email: you@example.org
  Temporary password (hidden, at least 12 characters):
  Again:
  stored BOOTSTRAP_ADMIN_EMAIL
  stored BOOTSTRAP_ADMIN_PASSWORD
  After the first sign-in run:  python infra/scripts/manage_secrets.py remove-bootstrap
Done for now. Next: python infra/scripts/tf.py up
```

Remember the email and temporary password: they are the first sign-in on the
deployed site. Do not use the `'` character in the password.

Check what is stored (names and dates only; values are never shown):

```powershell
python infra/scripts/manage_secrets.py list
```

Six names: the three keys, `DUCKDNS_TOKEN`, `BOOTSTRAP_ADMIN_EMAIL`,
`BOOTSTRAP_ADMIN_PASSWORD`. `MONGODB_URL` is added in step 6.

If it fails:

| Message | What to do |
|---|---|
| `Unable to locate credentials` / `could not be found` | `$env:AWS_PROFILE = "antiproxy"` in this window |
| `AccessDenied` | The IAM user needs administrator access |
| It stopped half way | Run the same command again: whatever is already stored is kept ("exists, kept") and it continues |
| You typed a wrong value | `python infra/scripts/manage_secrets.py purge` deletes them all; then run `init` again |

## Step 6. Create the deployment

```powershell
python infra/scripts/tf.py up
```

What happens, in order:

1. `AWS identity: arn:aws:iam::...:user/...` (your IAM user).
2. Terraform prints its plan, ending with `Plan: ... to add, 0 to change, 0 to destroy.`
   and asks `Enter a value:`. Nothing exists yet at this point. Type `yes`
   and Enter to create it; anything else cancels.
3. Creating takes 5 to 10 minutes; most of it is the Atlas cluster.
   It ends with `Apply complete!`.
4. `Instance address: x.x.x.x. Allowing it to reach the database ...` and a
   second, short apply by itself.
5. `Atlas database user antiproxy_app: readWrite on anti_proxy_attendance`
   and `stored MONGODB_URL`.
6. `Waiting for https://<site_host>/health ...` for up to 15 minutes: the
   instance installs Docker and pulls about 2.5 GB of images.
7. With the staging certificate authority on, the last lines are:

   ```
   The site answers at https://<site_host>, with a certificate browsers do not trust
   (acme_ca is set to the staging authority in terraform.tfvars).
   ```

If it fails:

| What you see | What to do |
|---|---|
| An error during the first apply | Read the last red block; fix the cause; run `python infra/scripts/tf.py up` again. It continues from where it stopped and never creates a second copy |
| Atlas error mentioning IP access list or 401/403 | Your IP changed or the key variables are missing in this window: preflight (step 4) tells which |
| `InvalidParameterCombination` or "not eligible for Free Tier" for the instance type | Tell me: the instance type has to change |
| The site did not answer within 15 minutes | `python infra/scripts/tf.py logs` shows the instance's start-up log, the containers and memory. Send me that output |
| You want to stop and undo everything | `python infra/scripts/tf.py destroy` |

## Step 7. First sign-in

Open `https://<site_host>` in Chrome. With the staging certificate the
browser shows a warning; continue past it for this test only. Sign in with
the email and temporary password from step 5 and set a new password when
asked. Then remove the first-administrator secrets:

```powershell
python infra/scripts/manage_secrets.py remove-bootstrap
```

## Step 8. Switch to the real certificate

When the test run looks right: put the `#` back in front of the `acme_ca`
line in `terraform.tfvars`, save, then:

```powershell
python infra/scripts/tf.py certificate
```

It tells the instance to use the certificate authority named in the file,
removes the test certificate and restarts the site; within a few minutes it
prints `The site answers: https://<site_host>` and Chrome shows no warning.
Let's Encrypt gives at most five real certificates a week for one name, so
do this once, on purpose, and do not destroy and recreate the deployment
repeatedly after it.

## Every later session

Step 3 (the window), then:

```powershell
python infra/scripts/tf.py start     # start the instance, wait for the site, update to the newest release
python infra/scripts/tf.py status    # what exists and whether it is running
python infra/scripts/tf.py logs      # start-up log, containers, memory
python infra/scripts/tf.py stop      # end of the session
```

After `start` the same URL works again within a few minutes; the new
address, DuckDNS and the database access list are updated by themselves.

---

# Reference

## What is created

| Where | What | Cost |
|---|---|---|
| AWS | VPC, one public subnet, internet gateway, security group (80 and 443 in) | free |
| AWS | EC2 `t3.small`, 20 GB encrypted gp3 volume, auto-assigned public address | credits |
| AWS | IAM role for the instance: Systems Manager, and read its own parameters | free |
| AWS | Nightly automatic stop (`on_demand` mode only) | free |
| AWS | GitHub OIDC provider, deploy role, deploy command document | free |
| AWS | Private S3 bucket for backups (encrypted, 14-day expiry) | cents, from credits |
| AWS | Two budgets with email alerts | free |
| AWS | SSM Parameter Store SecureString parameters (by `manage_secrets.py`, not Terraform) | free |
| Atlas | Project, M0 cluster in Mumbai, access list with the instance's address | free |

Not used: NAT gateway, load balancer, RDS, Secrets Manager, ECR, Elastic IP.
There is no SSH: port 22 is closed and no key pair exists.

## Running on demand (the final mode)

**Decision of 11 October 2026: the deployment stays on demand.** The site is
started when it is going to be shown and stopped afterwards; it does not run
all the time.

```powershell
python infra/scripts/tf.py start     # about an hour before showing the site
python infra/scripts/tf.py stop      # afterwards
```

- `start` waits until the site answers, then checks whether merges happened
  while the instance was stopped and, if so, moves it to the newest release
  by itself.
- If you forget to stop it, it is stopped automatically at 23:30 India time.
- While stopped, only the volume is billed (about $1.80 a month); the public
  address is released, so nothing is charged for it. Running costs $0.0274
  an hour (ap-south-1, October 2026), about $0.66 for a full day.
- Start it about an hour early: a freshly started instance has no CPU
  credits yet and recognition is slower until some have built up (24 an
  hour). A ten-minute webcam session used about 4.
- A merge to `main` while the instance is stopped cannot be deployed. The
  pipeline's deploy job then fails with the message "Not deployed: the
  instance is stopped. Nothing was changed." That is expected and harmless:
  the images are published, and the next `start` picks them up.

`run_mode` in `terraform.tfvars` stays `"on_demand"`. The other value,
`"always_on"`, removes the nightly automatic stop; it is not used.

## All commands

| Command | What it does |
|---|---|
| `python infra/scripts/tf.py preflight` | Checks this machine is ready; changes nothing |
| `python infra/scripts/manage_secrets.py init` | Creates whatever secret is missing (`tf.py secrets` is the same) |
| `python infra/scripts/manage_secrets.py list` | Names and dates of the stored secrets |
| `python infra/scripts/manage_secrets.py remove-bootstrap` | Deletes the first-administrator secrets |
| `python infra/scripts/manage_secrets.py purge` | Deletes all stored secrets |
| `python infra/scripts/tf.py plan` | Shows what `up` would change; changes nothing |
| `python infra/scripts/tf.py up` | Creates or updates the deployment (asks first) |
| `python infra/scripts/tf.py stop` / `start` / `status` / `logs` | Day to day |
| `python infra/scripts/tf.py certificate` | Makes the instance use the certificate authority set in `terraform.tfvars` |
| `python infra/scripts/tf.py deploy` | Switches the running instance to the current `origin/main` |
| `python infra/scripts/tf.py backup` | Takes a backup now and lists the stored ones |
| `python infra/scripts/tf.py github-vars` | Prints the repository variables for automatic deployment |
| `python infra/scripts/tf.py destroy` | Removes everything, including the stored secrets (asks first) |
| `python infra/scripts/sweep.py` | Read-only check of every region for billable resources |

Where GNU make is installed, the `Makefile` offers the same as `make up`,
`make stop` and so on.

## Secrets

| Parameter | Source |
|---|---|
| `JWT_SECRET_KEY`, `VISION_SERVICE_API_KEY`, `RECOGNITION_SIGNING_KEY` | generated, 256 bits each |
| `MONGODB_URL` | a database user the script creates in Atlas (read and write on the application's database only) with a generated password |
| `DUCKDNS_TOKEN` | typed at a hidden prompt |
| `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD` | typed; needed for the first start only |

They are SecureString parameters under `/antiproxy/prod`. Values are never
printed, never written to the repository, to Terraform's state, to instance
user data or to an image, and never placed on a command line: the AWS CLI
reads each one from a temporary file that only your user can read and that
is deleted straight afterwards, also when the call fails. On the instance
they are read at every start into `/run/antiproxy/env`, a root-only file that
exists in memory only.

## Automatic deployment from GitHub

After every merge to `main` the *Publish Images* workflow waits for the ten
required checks, pushes the images, and then, if the deployment exists,
deploys that commit and checks the site.

- No AWS key is stored in GitHub. The job proves its identity with a
  short-lived GitHub token (OIDC). AWS accepts it only from workflows on this
  repository's `main` branch.
- The role it receives can do one thing: run the `antiproxy-prod-deploy`
  document on the one instance. That document takes a full commit id and runs
  `/opt/antiproxy/deploy.sh` with it; it cannot run anything else.
- If the instance is stopped, the job fails at its first step with "Not
  deployed: the instance is stopped. Nothing was changed.", before anything
  is sent to the instance. The next `tf.py start` brings the instance to the
  newest release.
- The role's trust names the repository the way GitHub does in its tokens,
  with the permanent numeric ids
  (`repo:<owner>@<owner id>/<name>@<repository id>:ref:refs/heads/main`). If
  a deploy ever fails with "Not authorized to perform
  sts:AssumeRoleWithWebIdentity", compare `github_oidc_subject_prefix` in
  `variables.tf` with the output of
  `gh api repos/<owner>/<name>/actions/oidc/customization/sub`.
- The check afterwards is `scripts/smoke_e2e.py --base-url <site> --checks-only`:
  it needs no photos, no account and no secret, and creates nothing on the
  site.

**The photo smoke test is for local runs only (decision of 11 October 2026).**
The full flow enrols the face photos in the fixtures folder, and those are
volunteers' faces: they are never uploaded to the deployment. The script
enforces this: with `--base-url` pointing anywhere but this machine it
refuses to run the photo flow, and there is no option to allow it. How each
part is checked instead:

| What | How |
|---|---|
| The whole flow with photos | Locally: `python scripts/smoke_e2e.py` and `python scripts/smoke_e2e.py --prod-rehearsal` (the production stack through Caddy, on the laptop) |
| The deployment from outside | `python scripts/smoke_e2e.py --base-url https://<site_host> --checks-only`, also run by the pipeline after every deploy |
| Recognition on the deployment | By hand, in Chrome, with the owner's own face |

Switch it on once the deployment exists:

```powershell
python infra/scripts/tf.py github-vars
```

prints five `gh variable set ...` commands (role ARN, region, instance id,
document name, site URL; none is a secret). Run them. To switch automatic
deployment off: `gh variable delete AWS_DEPLOY_ROLE_ARN`.

`python infra/scripts/tf.py deploy` deploys the current `origin/main` by
hand. `tf.py start` already does this when the instance is behind.

## Backups

The Atlas free tier has no backups, so the instance makes its own every day
at 21:00 India time (or at the next start if it was stopped then): a
`mongodump` of the database and an archive of the uploaded photos, copied to
a private S3 bucket.

- The bucket blocks all public access, accepts TLS only, encrypts everything
  at rest and deletes anything older than 14 days. The photos are biometric
  data; they leave the instance only for this bucket.
- The instance can add backups but cannot read, list or delete them.
- The database address reaches `mongodump` through a root-only file in
  memory, never on a command line.

`python infra/scripts/tf.py backup` takes one immediately and lists what is
stored.

To restore (from the managing machine, with the Atlas access list
temporarily allowing its address):

```powershell
aws s3 cp s3://<backup_bucket>/<timestamp>/database.archive.gz .
mongorestore --uri "<connection string>" --archive=database.archive.gz --gzip --drop
```

The photos archive unpacks into the `anti_proxy_uploads` Docker volume on the
instance. Rehearse a restore once before real data is entered.

## Alerts

Two budgets email `alert_email`:

| Budget | Alerts |
|---|---|
| Credit use (usage at list price, before credits) | at $25, $50 and $75 |
| Actual spend (after credits) | at $1, actual or forecast |

On a Free plan the second cannot fire, because nothing is charged; it is
there in case the plan ever changes. The first is the one to watch: when the
credits run out, a Free plan account is closed.

One more alert is a console setting, not Terraform: Billing and Cost
Management → Billing preferences → Alert preferences → turn on
**AWS Free Tier alerts**.

## After the evaluation

1. `python infra/scripts/tf.py destroy` (asks first; also deletes the stored secrets).
2. `python infra/scripts/sweep.py`: a read-only check of every region for
   instances, volumes, snapshots, Elastic IPs, NAT gateways, load balancers,
   RDS and buckets. It should report nothing.
3. Atlas console: delete the API key; confirm the project is gone.
4. AWS console: delete the IAM user's access key.
5. GitHub: delete the three packages if they are no longer wanted.
6. A week later, check Billing: credits used should have stopped changing.

The application still runs locally with `docker compose up -d --build`.
