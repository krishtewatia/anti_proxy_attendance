#!/bin/bash
# First boot only (run by cloud-init): swap, Docker, Docker Compose, and the
# service that starts the application. No secret is used or written here.
set -euo pipefail

set -a
. /opt/antiproxy/config.env
set +a

# Swap: the vision service's memory peaks close to what a 2 GiB instance has.
if [ ! -f /swapfile ]; then
  dd if=/dev/zero of=/swapfile bs=1M count="$SWAP_MB" status=none
  chmod 600 /swapfile
  mkswap /swapfile > /dev/null
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi
swapon --all
echo "vm.swappiness=10" > /etc/sysctl.d/90-antiproxy.conf
sysctl --quiet --system

dnf install --assumeyes --quiet docker

# Docker Compose plugin, pinned and checked against its published checksum.
PLUGIN_DIR=/usr/libexec/docker/cli-plugins
mkdir -p "$PLUGIN_DIR"
curl --fail --silent --show-error --location --retry 5 \
  -o "$PLUGIN_DIR/docker-compose" \
  "https://github.com/docker/compose/releases/download/$COMPOSE_VERSION/docker-compose-linux-x86_64"
echo "$COMPOSE_SHA256  $PLUGIN_DIR/docker-compose" | sha256sum --check --quiet
chmod 755 "$PLUGIN_DIR/docker-compose"

systemctl enable --now docker
systemctl daemon-reload
systemctl enable antiproxy.service
# Not waited for: it keeps retrying until the secrets have been written.
systemctl start --no-block antiproxy.service
