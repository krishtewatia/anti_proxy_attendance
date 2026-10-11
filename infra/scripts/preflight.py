#!/usr/bin/env python3
"""Check, in one go, that this machine is ready to create the deployment.

    python infra/scripts/tf.py preflight

Read-only: nothing is created or changed, in AWS, in Atlas or on disk. Each
line is OK, MISSING (must be fixed before `tf.py up`) or NOTE (worth knowing).
Secret values are never printed.
"""

from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import re
import urllib.error
import urllib.request

from common import REPO_ROOT, TF_DIR, TFVARS, aws, child_environment, parse_tfvars

EXPECTED_REMOTE = "anti_proxy_attendance"
STAGING_CA = "https://acme-staging-v02.api.letsencrypt.org/directory"
ATLAS_API = "https://cloud.mongodb.com/api/atlas/v2"
PLACEHOLDERS = {
    "site_host": "your-subdomain.duckdns.org",
    "alert_email": "you@example.com",
    "atlas_org_id": "000000000000000000000000",
}


class Report:
    def __init__(self) -> None:
        self.missing = 0

    def ok(self, text: str) -> None:
        print(f"  OK       {text}")

    def note(self, text: str) -> None:
        print(f"  NOTE     {text}")

    def miss(self, text: str, fix: str) -> None:
        self.missing += 1
        print(f"  MISSING  {text}")
        print(f"           -> {fix}")


def quiet(cmd: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(  # nosec B603 - fixed commands, no shell
            cmd, env=child_environment(), text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
    except FileNotFoundError:
        return 127, ""
    return result.returncode, result.stdout or ""


def version_tuple(text: str) -> tuple[int, ...]:
    digits = "".join(ch if ch.isdigit() or ch == "." else " " for ch in text).split()
    for part in digits:
        if "." in part:
            return tuple(int(piece) for piece in part.split(".") if piece.isdigit())
    return ()


def check_folder(report: Report) -> None:
    print("Folder")
    code, remote = quiet(["git", "-C", str(REPO_ROOT), "remote", "get-url", "origin"])
    if code == 127:
        report.miss("git is not installed or not on PATH", "install Git for Windows, then open a new PowerShell window")
        return
    if code != 0 or EXPECTED_REMOTE not in remote:
        report.miss(
            f"{REPO_ROOT} is not a clone of the project",
            "run the scripts from a clone of krishtewatia/anti_proxy_attendance",
        )
    else:
        report.ok(f"project folder: {REPO_ROOT}")
    here = Path.cwd().resolve()
    if here != REPO_ROOT:
        report.note(f"you are in {here}; the commands in the guide are written for {REPO_ROOT}")
    code, _ = quiet(["git", "-C", str(REPO_ROOT), "fetch", "--quiet", "origin", "main"])
    behind_code, behind = quiet(["git", "-C", str(REPO_ROOT), "rev-list", "--count", "HEAD..origin/main"])
    if code == 0 and behind_code == 0 and behind.strip().isdigit() and int(behind.strip()) > 0:
        report.miss(
            f"this folder is {behind.strip()} commit(s) behind origin/main",
            "git pull",
        )
    elif code == 0:
        report.ok("up to date with origin/main")


def check_tools(report: Report) -> None:
    print("Tools")
    if sys.version_info < (3, 10):
        report.miss(f"Python {sys.version.split()[0]} is too old", "install Python 3.10 or newer")
    else:
        report.ok(f"Python {sys.version.split()[0]}")

    code, text = quiet(["terraform", "version"])
    if code != 0:
        report.miss(
            "Terraform is not installed or not on PATH",
            "winget install Hashicorp.Terraform   then open a NEW PowerShell window",
        )
    else:
        found = version_tuple(text.splitlines()[0] if text else "")
        if found and found < (1, 9):
            report.miss(f"Terraform {'.'.join(map(str, found))} is too old", "winget upgrade Hashicorp.Terraform")
        else:
            report.ok(f"Terraform {'.'.join(map(str, found)) or 'found'}")

    if shutil.which("aws") is None:
        report.miss("the AWS CLI is not installed or not on PATH", "winget install Amazon.AWSCLI   then open a NEW PowerShell window")
    else:
        report.ok("AWS CLI found")


def check_tfvars(report: Report) -> dict[str, str]:
    print("Settings file")
    if not TFVARS.exists():
        strays = [
            path for path in (
                REPO_ROOT / "terraform.tfvars",
                REPO_ROOT / "infra" / "terraform.tfvars",
                REPO_ROOT / "infra" / "scripts" / "terraform.tfvars",
                TF_DIR / "terraform.tfvars.txt",
            ) if path.exists()
        ]
        if strays:
            report.miss(
                f"terraform.tfvars is in the wrong place: {strays[0]}",
                f'Move-Item "{strays[0]}" "{TFVARS}"',
            )
        else:
            report.miss(
                f"{TFVARS} does not exist",
                "Copy-Item infra\\terraform\\terraform.tfvars.example infra\\terraform\\terraform.tfvars   then fill it in",
            )
        return {}
    report.ok(f"found {TFVARS}")

    code, _ = quiet(["git", "-C", str(REPO_ROOT), "check-ignore", "--quiet", str(TFVARS)])
    if code == 0:
        report.ok("terraform.tfvars is ignored by git")
    else:
        report.miss("terraform.tfvars is NOT ignored by git", "git pull   (the ignore rule is in the repository's .gitignore)")
    code, tracked = quiet(["git", "-C", str(REPO_ROOT), "ls-files", "--", "*.tfvars", "*.tfstate", "*.tfstate.*"])
    if code == 0 and tracked.strip():
        report.miss(f"tracked by git but must not be: {tracked.split()[0]}", "git rm --cached <that file>")

    values = parse_tfvars(TFVARS.read_text(encoding="utf-8-sig", errors="replace"))
    for name, placeholder in PLACEHOLDERS.items():
        value = values.get(name, "")
        if not value:
            report.miss(f"{name} is not set in terraform.tfvars", f'add the line:  {name} = "..."')
        elif value == placeholder:
            report.miss(f"{name} still has the example value", f"put your own value in terraform.tfvars for {name}")
        else:
            report.ok(f"{name} is set")
    site_host = values.get("site_host", "")
    if site_host and not site_host.endswith(".duckdns.org"):
        report.miss("site_host is not a DuckDNS name", 'use the form  site_host = "yourname.duckdns.org"')

    run_mode = values.get("run_mode", "on_demand")
    if run_mode not in ("on_demand", "always_on"):
        report.miss(f'run_mode is "{run_mode}"', 'use "on_demand" or "always_on"')
    else:
        report.ok(f"run_mode = {run_mode}")

    state_file = TF_DIR / "terraform.tfstate"
    resources = 0
    if state_file.exists():
        try:
            resources = len(json.loads(state_file.read_text(encoding="utf-8")).get("resources", []))
        except (OSError, ValueError):
            resources = -1
    if resources == 0:
        report.note("nothing has been created from this folder yet (no Terraform state here)")
    else:
        report.note(
            "this folder already holds the deployment's Terraform state; "
            "always run tf.py from this same folder, or a second copy of everything would be created"
        )
    if values.get("acme_ca") == STAGING_CA:
        if resources == 0:
            report.ok("staging certificate authority is on (right for the first runs)")
        else:
            report.note("terraform.tfvars names the staging certificate authority (browsers will warn)")
    elif resources == 0:
        report.miss(
            "the staging certificate line is not on",
            f'in terraform.tfvars, remove the # in front of:  acme_ca = "{STAGING_CA}"',
        )
    else:
        # Already deployed: the real authority is what a finished deployment uses.
        report.ok("real certificate authority (the staging line is off)")
    return values


def check_aws(report: Report) -> None:
    print("AWS")
    profile = os.environ.get("AWS_PROFILE", "")
    if profile:
        report.ok(f"AWS_PROFILE = {profile}")
    else:
        report.note('AWS_PROFILE is not set in this window ($env:AWS_PROFILE = "antiproxy")')
    region = os.environ.get("AWS_REGION", "")
    if region and region != "ap-south-1":
        report.miss(f"AWS_REGION is {region}", '$env:AWS_REGION = "ap-south-1"')
    elif region:
        report.ok("AWS_REGION = ap-south-1")
    else:
        report.note('AWS_REGION is not set in this window ($env:AWS_REGION = "ap-south-1")')
    if shutil.which("aws") is None:
        return

    identity = aws("sts", "get-caller-identity", region="ap-south-1", check=False)
    if identity.returncode != 0:
        reason = (identity.stderr or "").strip().splitlines()[-1][:160] if (identity.stderr or "").strip() else ""
        report.miss(
            f"the AWS CLI cannot sign in ({reason or 'no credentials'})",
            'aws configure --profile antiproxy   then   $env:AWS_PROFILE = "antiproxy"',
        )
        return
    try:
        who = json.loads(identity.stdout)
    except ValueError:
        report.miss("the AWS CLI answered with something unexpected", "aws sts get-caller-identity")
        return
    arn = who.get("Arn", "")
    if arn.endswith(":root"):
        report.miss("these are ROOT credentials", "use the access key of the IAM admin user, never root's")
    elif ":user/" in arn:
        report.ok(f"signed in as IAM user {arn.rsplit('/', 1)[-1]} in account {who.get('Account')}")
    else:
        report.note(f"signed in as {arn} (not an IAM user)")


def check_atlas(report: Report, values: dict[str, str]) -> None:
    print("MongoDB Atlas")
    public = os.environ.get("MONGODB_ATLAS_PUBLIC_API_KEY") or os.environ.get("MONGODB_ATLAS_PUBLIC_KEY")
    private = os.environ.get("MONGODB_ATLAS_PRIVATE_API_KEY") or os.environ.get("MONGODB_ATLAS_PRIVATE_KEY")
    if not public:
        report.miss("MONGODB_ATLAS_PUBLIC_API_KEY is not set in this window", '$env:MONGODB_ATLAS_PUBLIC_API_KEY = "..."')
    if not private:
        report.miss("MONGODB_ATLAS_PRIVATE_API_KEY is not set in this window", '$env:MONGODB_ATLAS_PRIVATE_API_KEY = "..."')
    if not public or not private:
        return
    report.ok("both Atlas API key variables are set")

    org_id = values.get("atlas_org_id", "")
    if not org_id or org_id == PLACEHOLDERS["atlas_org_id"]:
        return
    if not re.fullmatch(r"[0-9a-f]{24}", org_id):
        report.miss(
            "atlas_org_id does not look like an Atlas organization id (24 characters, 0-9 and a-f)",
            "copy the Organization ID from Atlas -> Organization Settings",
        )
        return
    passwords = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    passwords.add_password(None, ATLAS_API, public, private)
    opener = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(passwords))
    request = urllib.request.Request(
        f"{ATLAS_API}/orgs/{org_id}", headers={"Accept": "application/vnd.atlas.2023-01-01+json"}
    )
    try:
        with opener.open(request, timeout=20) as response:  # nosec B310 - fixed https address
            if response.status == 200:
                report.ok("the Atlas key works for this organization")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            report.miss("Atlas rejected the API key", "check both key values; the private key is shown only once when created")
        elif exc.code == 403:
            report.miss(
                "Atlas refused this address or this key's role",
                "Atlas -> Organization -> Access Manager -> API Keys -> the key -> add your current IP to its access list; role: Organization Project Creator",
            )
        elif exc.code == 404:
            report.miss("Atlas does not know this organization id", "copy the Organization ID from Atlas -> Organization Settings into atlas_org_id")
        else:
            report.note(f"Atlas answered HTTP {exc.code}; could not confirm the key")
    except OSError as exc:
        report.note(f"could not reach Atlas to confirm the key ({type(exc).__name__})")


def check_images(report: Report) -> None:
    print("Images")
    code, text = quiet(["git", "-C", str(REPO_ROOT), "ls-remote", "origin", "refs/heads/main"])
    sha = text.split()[0] if code == 0 and text.split() else ""
    if len(sha) != 40:
        report.note("could not read the commit of origin/main; images not checked")
        return
    absent = []
    for name in ("backend", "frontend", "vision"):
        repository = f"krishtewatia/anti-proxy-{name}"
        try:
            # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected
            connection = http.client.HTTPSConnection("ghcr.io", timeout=20, context=ssl.create_default_context())
            connection.request("GET", f"/token?scope=repository:{repository}:pull")
            token = json.loads(connection.getresponse().read() or b"{}").get("token", "")
            connection.request(
                "HEAD", f"/v2/{repository}/manifests/{sha}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.v2+json",
                },
            )
            status = connection.getresponse().status
            connection.close()
        except (OSError, ValueError):
            report.note("could not reach the image registry; images not checked")
            return
        if status != 200:
            absent.append(name)
    if absent:
        report.miss(
            f"no published image for the newest commit ({sha[:7]}): {', '.join(absent)}",
            "wait for the 'Publish Images' workflow on GitHub to finish (about 15 minutes after a merge), then run preflight again",
        )
    else:
        report.ok(f"images for the newest commit ({sha[:7]}) are published")


def main() -> int:
    report = Report()
    check_folder(report)
    check_tools(report)
    values = check_tfvars(report)
    check_aws(report)
    check_atlas(report, values)
    check_images(report)
    print()
    if report.missing:
        print(f"{report.missing} thing(s) to fix before `python infra/scripts/tf.py up`. Fix them and run preflight again.")
        return 1
    print("Ready. Next: python infra/scripts/manage_secrets.py init")
    return 0


if __name__ == "__main__":
    sys.exit(main())
