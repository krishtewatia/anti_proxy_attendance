#!/usr/bin/env python3
"""Point the DuckDNS name at this instance's current public address.

Runs on the instance at every start, because the address changes each time
the instance is stopped and started. The token is read from the in-memory
secrets file and is never printed; DuckDNS answers "OK" or "KO" and only that
answer is shown.
"""

import os
import sys
import urllib.parse
import urllib.request

ENV_FILE = "/run/antiproxy/env"


def read_token() -> str:
    with open(ENV_FILE) as handle:
        for line in handle:
            name, _, value = line.rstrip("\n").partition("=")
            if name == "DUCKDNS_TOKEN":
                return value.strip("'")
    return ""


def main() -> int:
    subdomain = os.environ["DUCKDNS_SUBDOMAIN"]
    token = read_token()
    if not token:
        print("DUCKDNS_TOKEN is not set", file=sys.stderr)
        return 1
    # No "ip" value: DuckDNS uses the address the request comes from, which is
    # this instance's public address.
    query = urllib.parse.urlencode({"domains": subdomain, "token": token, "ip": ""})
    try:
        with urllib.request.urlopen(f"https://www.duckdns.org/update?{query}", timeout=20) as response:
            answer = response.read().decode("ascii", "replace").strip()
    except Exception as exc:  # the URL holds the token, so the error text is not shown
        print(f"DuckDNS update failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"DuckDNS update for {subdomain}: {answer[:2]}")
    return 0 if answer.startswith("OK") else 1


if __name__ == "__main__":
    sys.exit(main())
