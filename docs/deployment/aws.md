# AWS deployment

One EC2 instance in Mumbai runs the production stack
([production_stack.md](production_stack.md)); the database is a free MongoDB
Atlas cluster; HTTPS comes from Caddy and Let's Encrypt on a free DuckDNS name.
Everything is created by Terraform (`infra/terraform`) through four commands:
`make up`, `make stop`, `make start`, `make destroy`.

The design assumes an AWS **Free plan** account: usage is paid from credits
and the account cannot be charged. Do not join the account to AWS
Organizations and do not enable IAM Identity Center: either moves it to the
Paid plan.

## What is created

| Where | What | Cost |
|---|---|---|
| AWS | VPC, one public subnet, internet gateway, security group (80 and 443 in) | free |
| AWS | EC2 `t3.small`, 20 GB encrypted gp3 volume, auto-assigned public address | credits |
| AWS | IAM role for the instance: Systems Manager, and read its own parameters | free |
| AWS | Nightly automatic stop (`on_demand` mode only) | free |
| AWS | GitHub OIDC provider, deploy role, deploy command document | free |
| AWS | SSM Parameter Store SecureString parameters (by `make secrets`, not Terraform) | free |
| Atlas | Project, M0 cluster in Mumbai, access list with the instance's address | free |

Not used: NAT gateway, load balancer, RDS, Secrets Manager, ECR, Elastic IP.
There is no SSH: port 22 is closed and no key pair exists. A shell on the
instance is `aws ssm start-session --target <instance id>`.

## Running all the time or on demand

One setting, `run_mode` in `infra/terraform/terraform.tfvars`:

| `run_mode` | Behaviour |
|---|---|
| `on_demand` | You start and stop it (`make start`, `make stop`). It is also stopped automatically every night at 23:30 India time, so a forgotten instance does not use up credits. |
| `always_on` | No automatic stop. It runs until `make stop`. |

Change the value and run `make up`. While stopped, only the volume is billed
(about $1.80 a month); the public address is released, so nothing is charged
for it.

Approximate credit use (ap-south-1, October 2026): running costs $0.0274 an
hour (instance plus public address), so a full day is about $0.66 and
24 October to 30 November is about $25.

## Tools

On the machine that manages the deployment:

- Terraform 1.9 or newer: `winget install Hashicorp.Terraform`
- AWS CLI v2
- Python 3.10 or newer (standard library only)
- Optional: GNU make (`winget install ezwinports.make`). Without it, run the
  script each target wraps, for example `python infra/scripts/tf.py up`.

## Credentials

Nothing here goes into the repository.

**AWS.** Use the IAM admin user, never root (the scripts refuse root). Create
an access key for that user and store it in a named profile:

```bash
aws configure --profile antiproxy
```

Region `ap-south-1`. Then, in every terminal you deploy from:

```bash
export AWS_PROFILE=antiproxy
```

**Atlas.** In the Atlas console: Organization → Access Manager → API Keys →
create a key with the *Organization Project Creator* role, and add your
current public address to the key's access list. Then:

```bash
export MONGODB_ATLAS_PUBLIC_API_KEY=...
export MONGODB_ATLAS_PRIVATE_API_KEY=...
```

Set them in the terminal only. Delete the key in Atlas after `make destroy`.

## First deployment

1. Images: the *Publish Images* workflow pushes three images to GitHub
   Container Registry after every merge to `main`. New packages are private;
   set each one to public once (GitHub profile → Packages → the package →
   Package settings → Change visibility) so the instance can pull them
   without a credential. They contain no secrets and no student data.
2. Settings:

   ```bash
   cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
   ```

   Fill in `site_host` and `atlas_org_id`. For trial runs also set `acme_ca`
   to the staging address in the example file: Let's Encrypt issues at most
   five real certificates a week for one name, and a rebuilt instance asks
   for a new one.
3. Create it:

   ```bash
   make up
   ```

   Terraform shows its plan and asks before creating anything. After the
   instance exists the script asks, with hidden prompts, for the DuckDNS
   token and the first administrator's email and temporary password, creates
   the database user in Atlas, and stores everything in Parameter Store. It
   then waits until `https://<site_host>/health` answers (first start pulls
   about 2.5 GB of images; allow ten minutes).
4. Sign in as the first administrator and change the password when asked.
   Then delete the first-administrator parameters:

   ```bash
   make secrets-remove-bootstrap
   ```

The site starts with an empty database: that administrator and nothing else.

## Secrets

`make secrets` (run by `make up` when something is missing) creates:

| Parameter | Source |
|---|---|
| `JWT_SECRET_KEY`, `VISION_SERVICE_API_KEY`, `RECOGNITION_SIGNING_KEY` | generated, 256 bits each |
| `MONGODB_URL` | a database user the script creates in Atlas (read and write on the application's database only) with a generated password |
| `DUCKDNS_TOKEN` | typed at a hidden prompt |
| `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD` | typed; needed for the first start only |

They are SecureString parameters under `/antiproxy/prod`. Values are never
printed, never written to the repository, to Terraform's state, to instance
user data or to an image. On the instance they are read at every start into
`/run/antiproxy/env`, a root-only file that exists in memory only.

`make secrets-list` shows names and dates. Nothing shows values.

## Day to day

```bash
make stop      # end of a working session
make start     # next session: new address, DuckDNS and the database access list are updated
make status
make logs      # start-up log, container states, memory
```

After `make start` the same URL works again within a few minutes.

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
- If the instance is stopped, the job says so and ends successfully.
- The check afterwards is `scripts/smoke_e2e.py --base-url <site> --checks-only`:
  it needs no photos, no account and no secret, and creates nothing on the
  site. The full flow with face photos is run from a laptop:

  ```bash
  SMOKE_ADMIN_EMAIL=... SMOKE_ADMIN_PASSWORD=...     python scripts/smoke_e2e.py --base-url https://<site_host> --photos /path/to/photos
  ```

  That run leaves two smoke-test students and a session behind; use it before
  real data is entered, or delete them afterwards from the admin panel.

Switch it on once the deployment exists:

```bash
make github-vars
```

prints five `gh variable set ...` commands (role ARN, region, instance id,
document name, site URL; none is a secret). Run them. To switch automatic
deployment off: `gh variable delete AWS_DEPLOY_ROLE_ARN`.

`make deploy` deploys the current `origin/main` by hand, for example after
`make start` when merges happened while the instance was stopped.

## After the evaluation

1. `make destroy` (asks first; also deletes the stored secrets).
2. `make sweep`: a read-only check of every region for instances, volumes,
   snapshots, Elastic IPs, NAT gateways, load balancers, RDS and buckets. It
   should report nothing.
3. Atlas console: delete the API key; confirm the project is gone.
4. AWS console: delete the IAM user's access key.
5. GitHub: delete the three packages if they are no longer wanted.
6. A week later, check Billing: credits used should have stopped changing.

The application still runs locally with `docker compose up -d --build`.
