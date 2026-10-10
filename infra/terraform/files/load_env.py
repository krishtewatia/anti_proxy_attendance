#!/usr/bin/env python3
"""Read the deployment's secrets from SSM Parameter Store into a root-only file.

Runs on the instance at every start. The parameters under SSM_PATH are
written as NAME=value lines to /run/antiproxy/env, which lives in memory
(tmpfs) and is readable by root only. Nothing is printed except parameter
names, and nothing is written to disk.
"""

import json
import os
import subprocess
import sys

ENV_FILE = "/run/antiproxy/env"
REQUIRED = [
    "MONGODB_URL",
    "JWT_SECRET_KEY",
    "VISION_SERVICE_API_KEY",
    "RECOGNITION_SIGNING_KEY",
    "DUCKDNS_TOKEN",
]


def main() -> int:
    region = os.environ["AWS_REGION"]
    path = os.environ["SSM_PATH"].rstrip("/") + "/"
    result = subprocess.run(
        [
            "aws", "ssm", "get-parameters-by-path",
            "--region", region,
            "--path", path,
            "--with-decryption",
            "--output", "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # The CLI's error text names the call and the reason, never a value.
        print(f"Could not read parameters under {path}: {result.stderr.strip()[:300]}", file=sys.stderr)
        return 1

    values: dict[str, str] = {}
    for parameter in json.loads(result.stdout).get("Parameters", []):
        name = parameter["Name"][len(path):]
        value = parameter["Value"]
        if "/" in name or "\n" in value or "\r" in value:
            print(f"Skipping parameter with an unusable name or value: {name}", file=sys.stderr)
            continue
        values[name] = value

    missing = [name for name in REQUIRED if not values.get(name)]
    if missing:
        print(f"Missing parameters under {path}: {', '.join(missing)}", file=sys.stderr)
        print("Run `make secrets` on the machine that manages the deployment.", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(ENV_FILE), mode=0o700, exist_ok=True)
    descriptor = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        for name in sorted(values):
            # Single quotes: Compose takes the value literally.
            handle.write(f"{name}='{values[name].replace(chr(39), '')}'\n")
    print(f"Loaded {len(values)} parameters: {', '.join(sorted(values))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
