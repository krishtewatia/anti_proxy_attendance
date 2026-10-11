"""Shared helpers for the deployment scripts. Standard library only.

Everything here has to behave the same on Windows (PowerShell) and Linux.
"""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePath
import re
import shutil
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TF_DIR = REPO_ROOT / "infra" / "terraform"
TFVARS = TF_DIR / "terraform.tfvars"
STATE_TFVARS = TF_DIR / "state.auto.tfvars"

# A Windows console may not be able to show every character; never crash on one.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


def fail(message: str) -> "None":
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def require_tools(*names: str) -> None:
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        fail(
            f"not installed or not on PATH: {', '.join(missing)}. "
            "See docs/deployment/aws.md, step 1. After installing, open a new PowerShell window."
        )


def cli_file_argument(path: PurePath) -> str:
    """The ``file://`` argument that makes the AWS CLI read a parameter from ``path``.

    The AWS CLI does not take a URL here: it removes the ``file://`` prefix
    and opens whatever follows as a path of the operating system. So the
    plain path goes after the prefix: ``file://C:\\Users\\me\\request.json``
    on Windows, ``file:///tmp/request.json`` on Linux. A real file URL
    (``Path.as_uri()``, ``file:///C:/...``) leaves ``/C:/...`` on Windows,
    which is not a path there.
    """
    return f"file://{path}"


def child_environment() -> dict[str, str]:
    env = dict(os.environ)
    # Never hand output to a pager: nothing here is read interactively.
    env["AWS_PAGER"] = ""
    return env


def run(cmd: list[str], *, capture: bool = False, check: bool = True, cwd: Path | None = None):
    """Run a command. Output goes to the terminal unless ``capture`` is set."""
    try:
        result = subprocess.run(  # nosec B603 - fixed commands, no shell
            cmd,
            cwd=str(cwd) if cwd else None,
            env=child_environment(),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            check=False,
        )
    except FileNotFoundError:
        fail(f"`{cmd[0]}` is not installed or not on PATH (see docs/deployment/aws.md, step 1).")
    if check and result.returncode != 0:
        if capture and result.stderr:
            print(result.stderr.strip()[:2000], file=sys.stderr)
        fail(f"`{' '.join(cmd[:3])} ...` failed (exit {result.returncode})")
    return result


def terraform(*args: str, capture: bool = False, check: bool = True):
    return run(["terraform", f"-chdir={TF_DIR}", *args], capture=capture, check=check)


def outputs() -> dict[str, str]:
    """Terraform outputs as plain strings; empty when nothing has been created."""
    if shutil.which("terraform") is None:
        return {}
    result = terraform("output", "-json", capture=True, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return {}
    try:
        parsed = json.loads(result.stdout)
    except ValueError:
        return {}
    return {name: str(entry.get("value", "")) for name, entry in parsed.items()}


def aws(*args: str, region: str | None = None, check: bool = True):
    cmd = ["aws", *args, "--output", "json"]
    if region:
        cmd += ["--region", region]
    return run(cmd, capture=True, check=check)


def parse_tfvars(text: str) -> dict[str, str]:
    """The simple ``name = "value"`` settings of a tfvars file; comment lines are skipped."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"([^"]*)"', line)
        if match:
            values[match.group(1)] = match.group(2)
    return values
