#!/bin/bash
# Nightly backup, run by antiproxy-backup.timer: a dump of the database and an
# archive of the uploaded photos, copied to the private backup bucket.
# The connection string is passed to mongodump in a root-only file in memory,
# never on the command line, and nothing here prints a secret.
set -euo pipefail
umask 077

set -a
. /opt/antiproxy/config.env
set +a

python3 /opt/antiproxy/load_env.py > /dev/null

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d /var/lib/antiproxy-backup.XXXXXX)"
CONFIG=/run/antiproxy/mongodump.yaml
trap 'rm -rf "$WORK" "$CONFIG"' EXIT

# mongodump reads the address (which contains the password) from this file.
python3 - "$CONFIG" <<'PY'
import json, os, sys
uri = ""
with open("/run/antiproxy/env") as handle:
    for line in handle:
        name, _, value = line.rstrip("\n").partition("=")
        if name == "MONGODB_URL":
            uri = value.strip("'")
descriptor = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(descriptor, "w") as handle:
    handle.write("uri: " + json.dumps(uri) + "\n")
PY

mongodump --config="$CONFIG" --archive="$WORK/database.archive.gz" --gzip --quiet

UPLOADS=/var/lib/docker/volumes/anti_proxy_uploads/_data
if [ -d "$UPLOADS" ]; then
  tar --create --gzip --file "$WORK/uploads.tar.gz" --directory "$UPLOADS" .
fi

for file in "$WORK"/*; do
  aws s3 cp --only-show-errors --region "$AWS_REGION" "$file" "s3://$BACKUP_BUCKET/$STAMP/$(basename "$file")"
done
echo "Backup $STAMP stored: $(ls "$WORK" | tr '\n' ' ')"
