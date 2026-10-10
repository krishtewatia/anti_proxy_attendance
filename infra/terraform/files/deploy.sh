#!/bin/bash
# Switch the instance to another release (a commit whose images are in the
# registry) and wait until the site answers. Usage: deploy.sh <40-char commit>
set -euo pipefail

RELEASE="${1:-}"
if ! [[ "$RELEASE" =~ ^[0-9a-f]{40}$ ]]; then
  echo "usage: deploy.sh <full commit id>" >&2
  exit 2
fi

set -a
. /opt/antiproxy/config.env
set +a

PREVIOUS="$(cat /opt/antiproxy/release)"
echo "$RELEASE" > /opt/antiproxy/release
if ! /opt/antiproxy/start.sh; then
  echo "Start failed; going back to $PREVIOUS" >&2
  echo "$PREVIOUS" > /opt/antiproxy/release
  /opt/antiproxy/start.sh || true
  exit 1
fi

# Through Caddy on this machine, with the real host name and certificate.
for attempt in $(seq 1 60); do
  if curl --fail --silent --max-time 5 --resolve "$SITE_ADDRESS:443:127.0.0.1" "https://$SITE_ADDRESS/health" > /dev/null; then
    echo "Release $RELEASE is healthy"
    # Old images are not needed any more; the volume is small.
    docker image prune --all --force > /dev/null
    exit 0
  fi
  sleep 5
done
echo "Release $RELEASE did not become healthy in time" >&2
exit 1
