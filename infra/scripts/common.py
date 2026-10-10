"""Shared helpers for the deployment scripts. Standard library only."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TF_DIR = REPO_ROOT / "infra" / "terraform"
TFVARS = TF_DIR / "terraform.tfvars"
STATE_TFVARS = TF_DIR / "state.auto.tfvars"


def fail(message: str) -> "None":
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def require_tools(*names: str) -> None:
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        fail(
            f"not installed or not on PATH: {', '.join(missing)}. "
            "See docs/deployment/aws.md, section \"Tools\"."
        )


def run(cmd: list[str], *, capture: bool = False, check: bool = True, cwd: Path | None = None):
    """Run a command. Output goes to the terminal unless ``capture`` is set."""
    result = subprocess.run(  # nosec B603 - fixed commands, no shell
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False,
    )
    if check and result.returncode != 0:
        if capture and result.stderr:
            print(result.stderr.strip()[:2000], file=sys.stderr)
        fail(f"`{' '.join(cmd[:3])} ...` failed (exit {result.returncode})")
    return result


def terraform(*args: str, capture: bool = False, check: bool = True):
    return run(["terraform", f"-chdir={TF_DIR}", *args], capture=capture, check=check)


def outputs() -> dict[str, str]:
    """Terraform outputs as plain strings; empty when nothing has been created."""
    result = terraform("output", "-json", capture=True, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return {}
    return {name: str(entry.get("value", "")) for name, entry in json.loads(result.stdout).items()}


def aws(*args: str, region: str | None = None, check: bool = True):
    cmd = ["aws", *args, "--output", "json"]
    if region:
        cmd += ["--region", region]
    return run(cmd, capture=True, check=check)
