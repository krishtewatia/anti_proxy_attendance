#!/usr/bin/env python3
"""Create, stop, start and destroy the AWS deployment. Used by the Makefile.

    python infra/scripts/tf.py up        create or update everything, then wait for the site
    python infra/scripts/tf.py stop      stop the instance (only its volume is billed)
    python infra/scripts/tf.py start     start it again, then wait for the site
    python infra/scripts/tf.py status    what exists and whether the site answers
    python infra/scripts/tf.py plan      show what `up` would change, change nothing
    python infra/scripts/tf.py logs      last lines of the start-up log and the container list
    python infra/scripts/tf.py deploy    switch the running instance to the current origin/main
    python infra/scripts/tf.py backup    take a backup now and list the stored backups
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
import http.client
import json
import ssl
import sys
import time
import urllib.parse

from common import REPO_ROOT, STATE_TFVARS, TFVARS, aws, fail, outputs, require_tools, run, terraform

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
        fail(f"{TFVARS} does not exist. Copy terraform.tfvars.example to terraform.tfvars and fill it in.")
    identity = aws("sts", "get-caller-identity", check=False)
    if identity.returncode != 0:
        fail("the AWS CLI has no working credentials. See docs/deployment/aws.md, section \"Credentials\".")
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
    print("Look at it with:  make logs")
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


def bring_up(*, auto_approve: bool) -> int:
    write_instance_state("running")
    apply(public_ip(), auto_approve=auto_approve)
    address = public_ip()
    if not address:
        fail("the instance has no public address after the apply")
    print(f"Instance address: {address}. Allowing it to reach the database ...")
    apply(address, auto_approve=True)

    # Secrets live outside Terraform; make sure they exist before waiting.
    run([sys.executable, str(SECRETS_SCRIPT), "init", "--if-missing"])
    return 0 if wait_for_site(outputs().get("site_url", "")) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["up", "stop", "start", "status", "plan", "logs", "deploy", "backup", "github-vars", "destroy"])
    command = parser.parse_args().command
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
            fail("nothing has been created yet. Run `make up` first.")
        return bring_up(auto_approve=True)

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
        return 0

    if command == "logs":
        return show_logs()

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
        print("Destroyed. Check that nothing is left with:  make sweep")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
