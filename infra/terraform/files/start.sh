#!/bin/bash
# Start (or restart) the application on the instance. Run by antiproxy.service
# at every boot and by deploy.sh. It never prints a secret.
set -euo pipefail
umask 077

set -a
. /opt/antiproxy/config.env
set +a
RELEASE="$(cat /opt/antiproxy/release)"
APP_DIR=/opt/antiproxy/app
RAW="https://raw.githubusercontent.com/$GITHUB_REPOSITORY/$RELEASE"

# 1. Secrets: from SSM Parameter Store into memory.
python3 /opt/antiproxy/load_env.py

# 2. DNS: the public address is new after every stop and start.
python3 /opt/antiproxy/duckdns.py

# 3. The Compose file and Caddy configuration of this release.
mkdir -p "$APP_DIR/docker"
curl --fail --silent --show-error --location --retry 5 -o "$APP_DIR/docker-compose.prod.yml.new" "$RAW/docker-compose.prod.yml"
curl --fail --silent --show-error --location --retry 5 -o "$APP_DIR/docker/Caddyfile.new" "$RAW/docker/Caddyfile"
mv "$APP_DIR/docker-compose.prod.yml.new" "$APP_DIR/docker-compose.prod.yml"
mv "$APP_DIR/docker/Caddyfile.new" "$APP_DIR/docker/Caddyfile"
chmod 644 "$APP_DIR/docker-compose.prod.yml" "$APP_DIR/docker/Caddyfile"
chmod 755 "$APP_DIR" "$APP_DIR/docker"

# 4. Pull this release's images and start.
cd "$APP_DIR"
export IMAGE_TAG="$RELEASE"
compose() {
  docker compose --env-file /opt/antiproxy/config.env --env-file /run/antiproxy/env -f docker-compose.prod.yml "$@"
}
compose pull --quiet
compose up --detach --remove-orphans
echo "Started release $RELEASE"
