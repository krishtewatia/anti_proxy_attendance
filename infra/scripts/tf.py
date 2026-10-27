#!/usr/bin/env python3
"""Create, stop, start and destroy the AWS deployment. Used by the Makefile.

    python infra/scripts/tf.py preflight check this machine is ready; changes nothing
    python infra/scripts/tf.py secrets   same as: python infra/scripts/manage_secrets.py init
    python infra/scripts/tf.py up        create or update everything, then wait for the site
    python infra/scripts/tf.py stop      stop the instance (only its volume is billed)
    python infra/scripts/tf.py start     start it again, wait for the site, update it to the newest release
    python infra/scripts/tf.py status    what exists and whether the site answers
    python infra/scripts/tf.py plan      show what `up` would change, change nothing
    python infra/scripts/tf.py logs      last lines of the start-up log and the container list
    python infra/scripts/tf.py certificate   make the instance use the certificate authority set in terraform.tfvars
    python infra/scripts/tf.py deploy    switch the running instance to the current origin/main
    python infra/scripts/tf.py backup    take a backup now and list the stored backups
    python infra/scripts/tf.py restore-drill   restore the newest backup into a throwaway local database and count it
    python infra/scripts/tf.py golive-reset    take a backup, then clear the test data (asks before deleting)
    python infra/scripts/tf.py restore-photos  put the newest photo backup back on the server (after a rebuild)
    python infra/scripts/tf.py github-vars   the repository variables the deploy pipeline needs
    python infra/scripts/tf.py destroy   remove everything, including the secrets

`up` and `destroy` show Terraform's plan and ask before changing anything.
How the instance runs is one setting, `run_mode`, in infra/terraform/terraform.tfvars.

The instance's public address changes whenever it is stopped and started, and
the database only accepts connections from that address, so `up` and `start`
apply twice: once to start the instance, once to allow its new address.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import http.client
import json
import shutil
import ssl
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

from common import (
    REPO_ROOT,
    STATE_TFVARS,
    TFVARS,
    aws,
    fail,
    outputs,
    parse_tfvars,
    require_tools,
    run,
    terraform,
)

# The two certificate authorities the deployment may use, and nothing else.
CERTIFICATE_AUTHORITIES = {
    "real": "https://acme-v02.api.letsencrypt.org/directory",
    "staging": "https://acme-staging-v02.api.letsencrypt.org/directory",
}


def certificate_commands(tfvars_text: str) -> tuple[str, list[str]]:
    """Which authority terraform.tfvars asks for, and the commands that switch the instance to it.

    The instance read the setting once, when it was created, so changing the
    file alone does nothing. Certificates from the other authority are
    removed, otherwise Caddy would keep serving them.
    """
    wanted = parse_tfvars(tfvars_text).get("acme_ca", CERTIFICATE_AUTHORITIES["real"])
    kinds = {url: kind for kind, url in CERTIFICATE_AUTHORITIES.items()}
    if wanted not in kinds:
        fail(f"acme_ca in terraform.tfvars is not one of the two known addresses: {wanted}")
    commands = [
        "set -eu",
        f"sed -i 's|^ACME_CA=.*|ACME_CA={wanted}|' /opt/antiproxy/config.env",
        "docker ps --all --quiet --filter name=caddy | xargs --no-run-if-empty docker rm --force",
        "docker volume rm --force anti_proxy_caddy_data anti_proxy_caddy_config",
        "systemctl restart antiproxy.service",
        "grep '^ACME_CA=' /opt/antiproxy/config.env",
    ]
    return kinds[wanted], commands

SECRETS_SCRIPT = REPO_ROOT / "infra" / "scripts" / "manage_secrets.py"


def release_sha() -> str:
    """The commit on origin/main: the images the instance starts on first boot."""
    result = run(["git", "-C", str(REPO_ROOT), "ls-remote", "origin", "refs/heads/main"], capture=True)
    sha = result.stdout.split()[0] if result.stdout.split() else ""
    if len(sha) != 40:
        fail("could not read the commit of origin/main")
    return sha


def write_instance_state(state: str) -> None:
    STATE_TFVARS.write_text(
        "# Written by infra/scripts/tf.py (make start / make stop). Do not edit.\n"
        f'instance_state = "{state}"\n',
        encoding="utf-8",
    )


def prepare() -> None:
    require_tools("terraform", "aws", "git")
    if not TFVARS.exists():
        fail(f"{TFVARS} does not exist. Run `python infra/scripts/tf.py preflight` to see what is missing.")
    identity = aws("sts", "get-caller-identity", region="ap-south-1", check=False)
    if identity.returncode != 0:
        fail("the AWS CLI cannot sign in. Run `python infra/scripts/tf.py preflight` to see what is missing.")
    arn = json.loads(identity.stdout).get("Arn", "")
    if arn.endswith(":root"):
        fail("these are root credentials. Use the IAM admin user instead.")
    print(f"AWS identity: {arn}")
    terraform("init", "-input=false", capture=True)


def apply(allowed_ip: str, *, auto_approve: bool) -> None:
    args = [
        "apply",
        "-input=false",
        f"-var=release_sha={release_sha()}",
        f"-var=atlas_allowed_ip={allowed_ip}",
    ]
    if auto_approve:
        args.append("-auto-approve")
    terraform(*args)


def public_ip() -> str:
    """The instance's current public address, asked from EC2 directly (empty when stopped)."""
    out = outputs()
    if not out.get("instance_id"):
        return ""
    result = aws(
        "ec2", "describe-instances",
        "--instance-ids", out["instance_id"],
        "--query", "Reservations[0].Instances[0].PublicIpAddress",
        region=out.get("aws_region"),
        check=False,
    )
    value = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else None
    return value or ""


def wait_for_site(url: str, minutes: int = 15) -> bool:
    host = urllib.parse.urlsplit(url).hostname
    if not url.startswith("https://") or not host:
        fail(f"unexpected site address: {url!r}")
    print(f"Waiting for {url}/health (first start pulls about 2.5 GB of images) ...", flush=True)
    deadline = time.time() + minutes * 60
    last = ""
    while time.time() < deadline:
        # Certificates are verified (explicit default context); the rule named
        # here is about Python 2.
        # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected
        connection = http.client.HTTPSConnection(
            host, timeout=10, context=ssl.create_default_context()
        )
        try:
            connection.request("GET", "/health")
            status = connection.getresponse().status
            if status == 200:
                print(f"The site answers: {url}")
                return True
            last = f"HTTP {status}"
        except ssl.SSLCertVerificationError:
            # The site is up; its certificate comes from the staging authority.
            print(f"The site answers at {url}, with a certificate browsers do not trust")
            print("(acme_ca is set to the staging authority in terraform.tfvars).")
            return True
        except OSError as exc:
            last = type(exc).__name__
        finally:
            connection.close()
        time.sleep(15)
    print(f"The site did not answer within {minutes} minutes (last result: {last}).")
    print("Look at it with:  python infra/scripts/tf.py logs")
    return False


def show_logs() -> int:
    """Start-up log and container states, fetched through Systems Manager (no SSH)."""
    out = outputs()
    if not out.get("instance_id"):
        fail("nothing has been created yet.")
    commands = [
        "journalctl --unit antiproxy --no-pager --lines 40",
        "docker ps --all --format 'table {{.Names}} {{.Status}}'",
        "docker stats --no-stream --format 'table {{.Name}} {{.MemUsage}}'",
        "free -m | head -3",
    ]
    return run_on_instance(out, "AWS-RunShellScript", {"commands": commands}, wait_seconds=60)


def run_on_instance(out: dict[str, str], document: str, parameters: dict, *, wait_seconds: int) -> int:
    """Run an SSM document on the instance and print what it printed."""
    region = out.get("aws_region")
    sent = aws(
        "ssm", "send-command",
        "--instance-ids", out["instance_id"],
        "--document-name", document,
        "--parameters", json.dumps(parameters),
        region=region,
    )
    command_id = json.loads(sent.stdout)["Command"]["CommandId"]
    for _ in range(max(1, wait_seconds // 2)):
        time.sleep(2)
        result = aws(
            "ssm", "get-command-invocation",
            "--command-id", command_id, "--instance-id", out["instance_id"],
            region=region, check=False,
        )
        if result.returncode != 0:
            continue
        invocation = json.loads(result.stdout)
        if invocation.get("Status") in {"Success", "Failed", "TimedOut", "Cancelled"}:
            print(invocation.get("StandardOutputContent", ""))
            if invocation.get("StandardErrorContent"):
                print(invocation["StandardErrorContent"], file=sys.stderr)
            return 0 if invocation["Status"] == "Success" else 1
    print("The instance did not answer (is it running?).")
    return 1


def bring_up(*, auto_approve: bool, catch_up_release: bool = False) -> int:
    before = outputs().get("instance_id", "")
    write_instance_state("running")
    apply(public_ip(), auto_approve=auto_approve)
    replaced_warning(before, outputs().get("instance_id", ""))
    address = public_ip()
    if not address:
        fail("the instance has no public address after the apply")
    print(f"Instance address: {address}. Allowing it to reach the database ...")
    apply(address, auto_approve=True)

    # Secrets live outside Terraform; make sure they exist before waiting.
    run([sys.executable, str(SECRETS_SCRIPT), "init", "--if-missing"])
    if not wait_for_site(outputs().get("site_url", "")):
        return 1
    return catch_up() if catch_up_release else 0


def running_release(out: dict[str, str]) -> str:
    """The commit the instance is running, read through Systems Manager ('' if unknown)."""
    region = out.get("aws_region")
    sent = aws(
        "ssm", "send-command",
        "--instance-ids", out["instance_id"],
        "--document-name", "AWS-RunShellScript",
        "--parameters", json.dumps({"commands": ["cat /opt/antiproxy/release"]}),
        region=region, check=False,
    )
    if sent.returncode != 0:
        return ""
    command_id = json.loads(sent.stdout)["Command"]["CommandId"]
    for _ in range(30):
        time.sleep(2)
        result = aws(
            "ssm", "get-command-invocation",
            "--command-id", command_id, "--instance-id", out["instance_id"],
            region=region, check=False,
        )
        if result.returncode != 0:
            continue
        invocation = json.loads(result.stdout)
        if invocation.get("Status") in {"Success", "Failed", "TimedOut", "Cancelled"}:
            return invocation.get("StandardOutputContent", "").strip()
    return ""


def catch_up() -> int:
    """After a start: move the instance to the newest release if merges happened while it was stopped."""
    out = outputs()
    newest = release_sha()
    current = running_release(out)
    if current == newest:
        print(f"Running the newest release ({newest[:7]}).")
        return 0
    import preflight

    missing = preflight.unpublished_images(newest)
    if missing is None or missing:
        print(
            f"The instance runs {current[:7] or 'an unknown release'}; the newest commit is {newest[:7]}, "
            "but its images are not published yet. Staying on the current release.\n"
            "When the 'Publish Images' run on GitHub has finished:  python infra/scripts/tf.py deploy"
        )
        return 0
    print(f"Merges happened while the instance was stopped: updating {current[:7] or '?'} -> {newest[:7]} ...")
    return run_on_instance(out, out["deploy_document"], {"ReleaseSha": [newest]}, wait_seconds=900)


# ------------------------------------------------------------------ backups

BACKUP_MAX_AGE_HOURS = 26
DRILL_CONTAINER = "antiproxy-restore-drill"
DRILL_PORT = 27098
COMPOSE_ON_INSTANCE = (
    "cd /opt/antiproxy/app && docker compose --env-file /opt/antiproxy/config.env "
    "--env-file /run/antiproxy/env -f docker-compose.prod.yml"
)


def backup_listing(out: dict[str, str]) -> list[tuple[str, int, str]]:
    """(key, size, last modified) of every stored backup file, oldest first."""
    listing = aws(
        "s3api", "list-objects-v2", "--bucket", out["backup_bucket"],
        "--query", "Contents[].[Key, Size, LastModified]",
        region=out.get("aws_region"), check=False,
    )
    rows = json.loads(listing.stdout or "null") or []
    return sorted(((k, int(n), m) for k, n, m in rows), key=lambda row: row[2])


def newest_backup(rows: list[tuple[str, int, str]], name: str = "database.archive.gz") -> tuple[str, int, str] | None:
    found = [row for row in rows if row[0].endswith("/" + name)]
    return found[-1] if found else None


def backup_age_hours(last_modified: str, now: datetime | None = None) -> float:
    """Hours since an S3 LastModified time such as 2026-10-26T18:00:05+00:00 or ...Z."""
    stamp = datetime.fromisoformat(last_modified.replace("Z", "+00:00"))
    now = now or datetime.now(timezone.utc)
    return (now - stamp).total_seconds() / 3600


# An empty photo archive (a tar.gz of an empty folder) is about 140 bytes.
PHOTO_ARCHIVE = "uploads.tar.gz"
PHOTO_ARCHIVE_MIN_BYTES = 1024
PHOTO_LINK_SECONDS = 300
UPLOADS_VOLUME = "/var/lib/docker/volumes/anti_proxy_uploads/_data"


def newest_good_photos(rows: list[tuple[str, int, str]]) -> tuple[str, int, str] | None:
    """The newest photo archive that holds photos (rows oldest first)."""
    good = [r for r in rows if r[0].endswith("/" + PHOTO_ARCHIVE) and r[1] >= PHOTO_ARCHIVE_MIN_BYTES]
    return good[-1] if good else None


def photo_backup_warning(
    rows: list[tuple[str, int, str]], retention_days: int, now: datetime | None = None
) -> str | None:
    """A warning when the newest photo backup is empty but an older one is not."""
    newest = newest_backup(rows, PHOTO_ARCHIVE)
    good = newest_good_photos(rows)
    if newest is None or good is None or newest[1] >= PHOTO_ARCHIVE_MIN_BYTES:
        return None
    left = retention_days - backup_age_hours(good[2], now) / 24
    return (
        f"the newest photo backup is empty, the last one with photos is {good[0]} "
        f"(deleted in {max(left, 0):.1f} days). Photos may be missing on the server: "
        "run `python infra/scripts/tf.py restore-photos`."
    )


def replaced_warning(before: str, after: str) -> bool:
    """Say so when an apply replaced the server: its photo storage starts empty."""
    if before and after and before != after:
        print(
            f"\nThe server was replaced ({before} -> {after}): its photo storage is empty.\n"
            "Run `python infra/scripts/tf.py restore-photos` to put the newest photo backup back.\n"
            "Also update the repository variable AWS_INSTANCE_ID (`python infra/scripts/tf.py github-vars`)."
        )
        return True
    return False


def retention_days() -> int:
    try:
        return int(parse_tfvars(TFVARS.read_text(encoding="utf-8-sig")).get("backup_retention_days", "14"))
    except (OSError, ValueError):
        return 14


def restore_photos_commands(link: str) -> list[str]:
    """Shell lines run on the server: download one archive by a short-lived link
    into memory, check it, and add the missing photos. Prints counts only."""
    return [
        "set -euo pipefail",
        f'V="{UPLOADS_VOLUME}"',
        '[ -d "$V" ] || { echo "The photo volume does not exist (is the site running?)"; exit 1; }',
        'T="$(mktemp -d /run/antiproxy-restore.XXXXXX)"',
        "trap 'rm -rf \"$T\"' EXIT",
        f"curl --fail --silent --show-error --max-time 300 -o \"$T/photos.tar.gz\" '{link}'",
        'tar -tzf "$T/photos.tar.gz" > /dev/null',
        'before="$(find "$V" -type f | wc -l)"',
        'tar -xzf "$T/photos.tar.gz" -C "$V" --skip-old-files --same-owner',
        'after="$(find "$V" -type f | wc -l)"',
        'echo "Photo files: $before before, $((after - before)) added, $after now."',
    ]


def restore_photos(out: dict[str, str], ask=input) -> int:
    good = newest_good_photos(backup_listing(out))
    if good is None:
        print("No photo backup with photos is stored, so there is nothing to restore.")
        return 1
    key, size, modified = good
    print(f"Newest photo backup with photos: {key} ({size / 1e6:.1f} MB, {backup_age_hours(modified) / 24:.1f} days old).")
    if ask("Add the photos from it that are missing on the server? Type yes: ").strip().lower() != "yes":
        print("Stopped. Nothing was changed.")
        return 0
    signed = aws(
        "s3", "presign", f"s3://{out['backup_bucket']}/{key}",
        "--expires-in", str(PHOTO_LINK_SECONDS), region=out.get("aws_region"),
    )
    link = signed.stdout.strip()
    if not link.startswith("https://") or "'" in link:
        fail("could not make a download link for the backup.")
    code = run_on_instance(out, "AWS-RunShellScript", {"commands": restore_photos_commands(link)}, wait_seconds=600)
    if code != 0:
        return code
    print("Taking a fresh backup, so the newest one holds the photos again ...")
    return run_on_instance(out, "AWS-RunShellScript", {"commands": ["/opt/antiproxy/backup.sh"]}, wait_seconds=600)


def restore_target_is_local(uri: str) -> bool:
    """The drill only ever restores into a database on this machine."""
    host = urllib.parse.urlsplit(uri).hostname or ""
    return host in {"127.0.0.1", "localhost", "::1"}


# Counts per collection and the newest session day, printed as one JSON line.
DRILL_COUNT_SCRIPT = (
    "const d = db.getSiblingDB(process.env.DB || 'anti_proxy_attendance');"
    "const out = {};"
    "d.getCollectionNames().sort().forEach(c => { out[c] = d.getCollection(c).estimatedDocumentCount(); });"
    "const s = d.sessions.find({}, {date: 1}).sort({date: -1}).limit(1).toArray();"
    "print(JSON.stringify({counts: out, newest_session_day: s.length ? s[0].date : null}));"
)


def restore_drill(out: dict[str, str]) -> int:
    rows = backup_listing(out)
    newest = newest_backup(rows)
    if newest is None:
        fail("no database backup is stored yet. Run `python infra/scripts/tf.py backup` first.")
    key, size, modified = newest
    photos = newest_backup(rows, "uploads.tar.gz")
    uri = f"mongodb://127.0.0.1:{DRILL_PORT}"
    if not restore_target_is_local(uri):
        fail("the drill restores only into a database on this machine.")
    work = Path(tempfile.mkdtemp(prefix="antiproxy-drill-"))
    try:
        print(f"Newest backup: {key} ({size / 1e6:.1f} MB, {backup_age_hours(modified):.1f} h old)")
        archive = work / "database.archive.gz"
        aws("s3", "cp", "--only-show-errors", f"s3://{out['backup_bucket']}/{key}", str(archive),
            region=out.get("aws_region"))
        run(["docker", "rm", "-f", DRILL_CONTAINER], capture=True, check=False)
        run(["docker", "run", "-d", "--name", DRILL_CONTAINER, "-p", f"127.0.0.1:{DRILL_PORT}:27017", "mongo:8.0"], capture=True)
        for _ in range(30):
            if run(["docker", "exec", DRILL_CONTAINER, "mongosh", "--quiet", "--eval", "db.runCommand({ping: 1}).ok"],
                   capture=True, check=False).returncode == 0:
                break
            time.sleep(1)
        run(["docker", "cp", str(archive), f"{DRILL_CONTAINER}:/tmp/database.archive.gz"], capture=True)
        run(["docker", "exec", DRILL_CONTAINER, "mongorestore", "--quiet", "--gzip",
             "--archive=/tmp/database.archive.gz"], capture=True)
        counted = run(["docker", "exec", DRILL_CONTAINER, "mongosh", "--quiet", "--eval", DRILL_COUNT_SCRIPT],
                      capture=True)
        report = json.loads(counted.stdout.strip().splitlines()[-1])
        print("Restored into a throwaway local database. Documents per collection:")
        for name, count in report["counts"].items():
            print(f"  {count:>8}  {name}")
        print(f"Newest session day in the backup: {report['newest_session_day'] or '(none)'}")
        if photos:
            print(f"Photo archive stored: {photos[0]} ({photos[1] / 1e6:.1f} MB); not downloaded.")
        print("Compare these numbers with the live site. The drill passed if they match.")
        return 0
    finally:
        run(["docker", "rm", "-f", DRILL_CONTAINER], capture=True, check=False)
        shutil.rmtree(work, ignore_errors=True)


def golive_reset(out: dict[str, str], ask=input) -> int:
    print("1/3 Taking a backup first ...")
    if run_on_instance(out, "AWS-RunShellScript", {"commands": ["/opt/antiproxy/backup.sh"]}, wait_seconds=600) != 0:
        print("The backup failed, so nothing was deleted.")
        return 1
    tool = (
        COMPOSE_ON_INSTANCE + " exec -T backend sh -c "
        "'python -m app.tools.golive_reset --database \"${DATABASE_NAME:-anti_proxy_attendance}\" \"$@\"' _"
    )
    print("2/3 What would be removed:")
    if run_on_instance(out, "AWS-RunShellScript", {"commands": [tool]}, wait_seconds=300) != 0:
        return 1
    answer = ask("Type the 'Total to remove' number to delete exactly that, or press Enter to stop: ").strip()
    if not answer.isdigit():
        print("Stopped. Nothing was deleted.")
        return 0
    print("3/3 Deleting ...")
    return run_on_instance(
        out, "AWS-RunShellScript", {"commands": [f"{tool} --apply --expect {int(answer)}"]}, wait_seconds=900
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["preflight", "secrets", "up", "stop", "start", "status", "plan", "logs", "certificate", "deploy", "backup", "restore-drill", "golive-reset", "restore-photos", "github-vars", "destroy"])
    command = parser.parse_args().command
    if command == "preflight":
        import preflight

        return preflight.main()
    if command == "secrets":
        return run([sys.executable, str(SECRETS_SCRIPT), "init"], check=False).returncode
    prepare()

    if command == "plan":
        terraform(
            "plan", "-input=false",
            f"-var=release_sha={release_sha()}", f"-var=atlas_allowed_ip={public_ip()}",
        )
        return 0

    if command == "up":
        return bring_up(auto_approve=False)

    if command == "start":
        if not outputs().get("instance_id"):
            fail("nothing has been created yet. Run `python infra/scripts/tf.py up` first.")
        return bring_up(auto_approve=True, catch_up_release=True)

    if command == "stop":
        if not outputs().get("instance_id"):
            fail("nothing has been created yet.")
        write_instance_state("stopped")
        # With the instance stopped, no address is allowed to reach the database.
        apply("", auto_approve=True)
        print("Stopped. Only the 20 GB volume is billed while it is stopped.")
        return 0

    if command == "status":
        out = outputs()
        if not out.get("instance_id"):
            print("Nothing has been created.")
            return 0
        state = aws(
            "ec2", "describe-instances", "--instance-ids", out["instance_id"],
            "--query", "Reservations[0].Instances[0].State.Name",
            region=out.get("aws_region"), check=False,
        )
        print(f"run_mode : {out.get('run_mode')}")
        print(f"instance : {out['instance_id']} ({json.loads(state.stdout) if state.stdout.strip() else 'unknown'})")
        print(f"address  : {public_ip() or '(none while stopped)'}")
        print(f"site     : {out.get('site_url')}")
        newest = newest_backup(backup_listing(out)) if out.get("backup_bucket") else None
        if newest is None:
            print("backup   : none stored yet")
        else:
            age = backup_age_hours(newest[2])
            warning = "  <- older than expected, check the nightly backup" if age > BACKUP_MAX_AGE_HOURS else ""
            print(f"backup   : {newest[0]} ({age:.1f} h old){warning}")
            photos = photo_backup_warning(backup_listing(out), retention_days())
            if photos:
                print(f"photos   : WARNING: {photos}")
        return 0

    if command == "logs":
        return show_logs()

    if command == "certificate":
        out = outputs()
        if not out.get("instance_id"):
            fail("nothing has been created yet.")
        kind, commands = certificate_commands(TFVARS.read_text(encoding="utf-8-sig"))
        print(f"Switching the instance to the {kind} certificate authority (the site restarts) ...")
        code = run_on_instance(out, "AWS-RunShellScript", {"commands": commands}, wait_seconds=600)
        return code if code else (0 if wait_for_site(out.get("site_url", ""), minutes=10) else 1)

    if command == "deploy":
        out = outputs()
        if not out.get("instance_id"):
            fail("nothing has been created yet.")
        sha = release_sha()
        print(f"Deploying {sha} ...")
        return run_on_instance(out, out["deploy_document"], {"ReleaseSha": [sha]}, wait_seconds=900)

    if command == "backup":
        out = outputs()
        if not out.get("instance_id"):
            fail("nothing has been created yet.")
        code = run_on_instance(
            out, "AWS-RunShellScript", {"commands": ["/opt/antiproxy/backup.sh"]}, wait_seconds=600
        )
        listing = aws(
            "s3api", "list-objects-v2", "--bucket", out["backup_bucket"],
            "--query", "Contents[].[Key, Size, LastModified]",
            region=out.get("aws_region"), check=False,
        )
        print(f"Stored in s3://{out['backup_bucket']}:")
        for key, size, modified in json.loads(listing.stdout or "null") or []:
            print(f"  {modified[:19]}  {size:>10}  {key}")
        return code

    if command in ("restore-drill", "golive-reset", "restore-photos"):
        out = outputs()
        if not out.get("backup_bucket"):
            fail("nothing has been created yet.")
        if command == "restore-photos":
            return restore_photos(out)
        return restore_drill(out) if command == "restore-drill" else golive_reset(out)

    if command == "github-vars":
        out = outputs()
        if not out.get("deploy_role_arn"):
            fail("nothing has been created yet.")
        print("Repository variables for the deploy pipeline (none of them is a secret):\n")
        for name, value in (
            ("AWS_DEPLOY_ROLE_ARN", out["deploy_role_arn"]),
            ("AWS_REGION", out["aws_region"]),
            ("AWS_INSTANCE_ID", out["instance_id"]),
            ("AWS_DEPLOY_DOCUMENT", out["deploy_document"]),
            ("SITE_URL", out["site_url"]),
        ):
            print(f'gh variable set {name} --body "{value}"')
        print("\nTo switch automatic deployment off again:  gh variable delete AWS_DEPLOY_ROLE_ARN")
        return 0

    if command == "destroy":
        before = outputs()
        terraform("destroy", "-input=false", f"-var=release_sha={release_sha()}", "-var=atlas_allowed_ip=")
        if outputs().get("instance_id"):
            print("Terraform still reports resources; the destroy was not completed.")
            return 1
        # The parameters are not Terraform's, so they are removed here.
        run(
            [
                sys.executable, str(SECRETS_SCRIPT), "purge",
                "--region", before.get("aws_region") or "ap-south-1",
                "--path", before.get("ssm_path") or "/antiproxy/prod",
            ]
        )
        STATE_TFVARS.unlink(missing_ok=True)
        print("Destroyed. Check that nothing is left with:  python infra/scripts/sweep.py")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
