#!/usr/bin/env python3
"""Create the deployment's secrets and store them in SSM Parameter Store.

    python infra/scripts/manage_secrets.py init           create whatever is missing
    python infra/scripts/manage_secrets.py list           names and dates only
    python infra/scripts/manage_secrets.py rotate NAME    replace one generated secret
    python infra/scripts/manage_secrets.py remove-bootstrap
    python infra/scripts/manage_secrets.py purge          delete all of them

Every secret is new for the deployment: generated here, or typed at a hidden
prompt. Values go from this process straight to Parameter Store as
SecureString parameters. They are never printed, never written to the
repository or to Terraform's state, and never placed on a command line (the
AWS CLI reads them from a temporary file that only this user can read and
that is deleted immediately).

What is stored under the deployment's path (default /antiproxy/prod):

    JWT_SECRET_KEY, VISION_SERVICE_API_KEY, RECOGNITION_SIGNING_KEY   generated
    MONGODB_URL        built from a database user this script creates in Atlas
    DUCKDNS_TOKEN      typed at a hidden prompt
    BOOTSTRAP_ADMIN_EMAIL, BOOTSTRAP_ADMIN_PASSWORD   typed; first start only

The Atlas API key is read from the environment (MONGODB_ATLAS_PUBLIC_API_KEY
and MONGODB_ATLAS_PRIVATE_API_KEY), the same variables Terraform uses.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from common import aws, fail, outputs, require_tools

GENERATED = ["JWT_SECRET_KEY", "VISION_SERVICE_API_KEY", "RECOGNITION_SIGNING_KEY"]
BOOTSTRAP = ["BOOTSTRAP_ADMIN_EMAIL", "BOOTSTRAP_ADMIN_PASSWORD"]
DATABASE_NAME = "anti_proxy_attendance"
DATABASE_USER = "antiproxy_app"
ATLAS_API = "https://cloud.mongodb.com/api/atlas/v2"
ATLAS_ACCEPT = "application/vnd.atlas.2023-01-01+json"


class Store:
    """The deployment's parameters in SSM Parameter Store."""

    def __init__(self, region: str, path: str) -> None:
        self.region = region
        self.path = path.rstrip("/")

    def names(self) -> dict[str, str]:
        """Existing parameter names (without the path) and when each was last changed."""
        result = aws(
            "ssm", "describe-parameters",
            "--parameter-filters", f"Key=Path,Option=Recursive,Values={self.path}",
            region=self.region,
        )
        found = {}
        for parameter in json.loads(result.stdout).get("Parameters", []):
            found[parameter["Name"][len(self.path) + 1:]] = str(parameter.get("LastModifiedDate", ""))[:19]
        return found

    def put(self, name: str, value: str) -> None:
        """Store one value. It reaches the AWS CLI through a private temporary file."""
        request = {
            "Name": f"{self.path}/{name}",
            "Value": value,
            "Type": "SecureString",
            "Overwrite": True,
            "Tier": "Standard",
        }
        directory = tempfile.mkdtemp(prefix="antiproxy-")
        request_file = Path(directory) / "request.json"
        try:
            descriptor = os.open(request_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(request, handle)
            aws("ssm", "put-parameter", "--cli-input-json", request_file.as_uri(), region=self.region)
        finally:
            request_file.unlink(missing_ok=True)
            os.rmdir(directory)
        print(f"  stored {name}")

    def delete(self, names: list[str]) -> None:
        for start in range(0, len(names), 10):
            batch = [f"{self.path}/{name}" for name in names[start:start + 10]]
            aws("ssm", "delete-parameters", "--names", *batch, region=self.region)
        for name in names:
            print(f"  deleted {name}")


# ------------------------------------------------------------------------------
# Atlas: the application's database user
# ------------------------------------------------------------------------------


def atlas_request(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    public = os.environ.get("MONGODB_ATLAS_PUBLIC_API_KEY") or os.environ.get("MONGODB_ATLAS_PUBLIC_KEY")
    private = os.environ.get("MONGODB_ATLAS_PRIVATE_API_KEY") or os.environ.get("MONGODB_ATLAS_PRIVATE_KEY")
    if not public or not private:
        fail("set MONGODB_ATLAS_PUBLIC_API_KEY and MONGODB_ATLAS_PRIVATE_API_KEY (see docs/deployment/aws.md)")
    passwords = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    passwords.add_password(None, ATLAS_API, public, private)
    opener = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(passwords))
    request = urllib.request.Request(
        f"{ATLAS_API}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Accept": ATLAS_ACCEPT, "Content-Type": "application/json"},
    )
    try:
        with opener.open(request, timeout=30) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read() or b"{}")
        except ValueError:
            detail = {}
        # Atlas error bodies describe the problem; they do not echo the password.
        return exc.code, {"errorCode": detail.get("errorCode"), "detail": str(detail.get("detail", ""))[:200]}


def create_database_user(project_id: str) -> str:
    """Create the application's database user (or give it a new password). Returns the password."""
    password = secrets.token_urlsafe(32)
    user = {
        "databaseName": "admin",
        "username": DATABASE_USER,
        "password": password,
        "groupId": project_id,
        # Read and write the application's own database, nothing else.
        "roles": [{"databaseName": DATABASE_NAME, "roleName": "readWrite"}],
    }
    status, answer = atlas_request("POST", f"/groups/{project_id}/databaseUsers", user)
    if status == 409:
        status, answer = atlas_request(
            "PATCH", f"/groups/{project_id}/databaseUsers/admin/{DATABASE_USER}", {"password": password}
        )
    if status not in (200, 201):
        fail(f"Atlas refused to create the database user (HTTP {status}): {answer}")
    print(f"  Atlas database user {DATABASE_USER}: readWrite on {DATABASE_NAME}")
    return password


def mongodb_url(srv_address: str, password: str) -> str:
    host = srv_address.split("://", 1)[-1].strip("/")
    if not host:
        fail("Terraform has no Atlas cluster address yet. Run `make up` first.")
    query = urllib.parse.urlencode({"retryWrites": "true", "w": "majority", "appName": "antiproxy"})
    return (
        f"mongodb+srv://{urllib.parse.quote(DATABASE_USER)}:{urllib.parse.quote(password, safe='')}"
        f"@{host}/{DATABASE_NAME}?{query}"
    )


# ------------------------------------------------------------------------------
# Prompts
# ------------------------------------------------------------------------------


def hidden(prompt: str, *, minimum: int = 1, confirm: bool = False) -> str:
    while True:
        value = getpass.getpass(prompt).strip()
        if len(value) < minimum:
            print(f"  At least {minimum} characters.")
            continue
        if confirm and getpass.getpass("  Again: ").strip() != value:
            print("  The two entries differ.")
            continue
        return value


# ------------------------------------------------------------------------------
# Commands
# ------------------------------------------------------------------------------


def command_init(store: Store, out: dict[str, str], only_if_missing: bool) -> int:
    existing = store.names()
    wanted = [*GENERATED, "MONGODB_URL", "DUCKDNS_TOKEN"]
    missing = [name for name in wanted if name not in existing]
    if only_if_missing and not missing:
        print("All secrets are already in Parameter Store.")
        return 0
    print(f"Secrets under {store.path} ({store.region}):")

    for name in GENERATED:
        if name in existing:
            print(f"  {name} exists, kept")
        else:
            store.put(name, secrets.token_hex(32))

    if "MONGODB_URL" in existing:
        print("  MONGODB_URL exists, kept")
    else:
        if not out.get("atlas_project_id"):
            fail("Terraform has not created the Atlas project yet. Run `make up` first.")
        password = create_database_user(out["atlas_project_id"])
        store.put("MONGODB_URL", mongodb_url(out.get("atlas_srv_address", ""), password))

    if "DUCKDNS_TOKEN" in existing:
        print("  DUCKDNS_TOKEN exists, kept")
    else:
        store.put("DUCKDNS_TOKEN", hidden("DuckDNS token (hidden): ", minimum=20))

    if not any(name in existing for name in BOOTSTRAP):
        print("First administrator of the deployed site (created at first start, must change the password at first sign-in):")
        email = input("  Email: ").strip()
        if "@" not in email:
            fail("that is not an email address")
        store.put("BOOTSTRAP_ADMIN_EMAIL", email)
        store.put(
            "BOOTSTRAP_ADMIN_PASSWORD",
            hidden("  Temporary password (hidden, at least 12 characters): ", minimum=12, confirm=True),
        )
        print("  After the first sign-in run:  make secrets-remove-bootstrap")
    return 0


def command_rotate(store: Store, name: str) -> int:
    if name not in GENERATED:
        fail(f"only these can be rotated here: {', '.join(GENERATED)}")
    store.put(name, secrets.token_hex(32))
    print("Restart the application so it reads the new value:  make stop && make start")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["init", "list", "rotate", "remove-bootstrap", "purge"])
    parser.add_argument("name", nargs="?", help="for rotate: the secret to replace")
    parser.add_argument("--if-missing", action="store_true", help="init: do nothing when everything exists")
    parser.add_argument("--region", help="default: from Terraform's outputs")
    parser.add_argument("--path", help="default: from Terraform's outputs")
    args = parser.parse_args()

    require_tools("aws")
    out = outputs() if not (args.region and args.path) or args.command == "init" else {}
    region = args.region or out.get("aws_region") or "ap-south-1"
    path = args.path or out.get("ssm_path") or "/antiproxy/prod"
    store = Store(region, path)

    if args.command == "init":
        return command_init(store, out, args.if_missing)
    if args.command == "list":
        for name, changed in sorted(store.names().items()):
            print(f"  {name:28s} last changed {changed}")
        return 0
    if args.command == "rotate":
        return command_rotate(store, args.name or "")
    if args.command == "remove-bootstrap":
        present = [name for name in BOOTSTRAP if name in store.names()]
        store.delete(present) if present else print("  nothing to remove")
        return 0
    if args.command == "purge":
        present = sorted(store.names())
        store.delete(present) if present else print("  no parameters left")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
