#!/usr/bin/env bash
set -euo pipefail

export RCLONE_CONFIG="/root/.config/rclone/rclone.conf"
export RESTIC_REPOSITORY="rclone:cloud:Backups_Homelab/restic-repo"
export RESTIC_PASSWORD_FILE="/root/.config/restic/password"
export RESTIC_CACHE_DIR="/var/cache/restic"

RESTIC_OPTS=(
  -o "rclone.connections=2"
  -o "rclone.args=serve restic --stdio --drive-chunk-size 64M --tpslimit 2 --tpslimit-burst 2 --retries 10 --low-level-retries 20"
)

mkdir -p /data/backups
if docker ps --format '{{.Names}}' | grep -qx 'nextcloud-db'; then
  docker exec nextcloud-db sh -c '
    DUMP_BIN=$(command -v mariadb-dump || command -v mysqldump)
    ROOT_PW="${MARIADB_ROOT_PASSWORD:-${MYSQL_ROOT_PASSWORD:-}}"
    "$DUMP_BIN" --single-transaction --quick -uroot -p"$ROOT_PW" --all-databases
  ' | gzip -c > /data/backups/nextcloud-db.sql.gz.tmp
  mv /data/backups/nextcloud-db.sql.gz.tmp /data/backups/nextcloud-db.sql.gz
  chmod 600 /data/backups/nextcloud-db.sql.gz
fi

restic "${RESTIC_OPTS[@]}" unlock || true
restic "${RESTIC_OPTS[@]}" backup \
  --tag homelab \
  --pack-size 64 \
  --exclude /data/appdata/nextcloud/db \
  --exclude /data/appdata/jellyfin/cache \
  --exclude '**/node_modules' \
  /data/appdata \
  /data/backups \
  /data/share \
  /var/lib/docker/volumes/portainer_data/_data \
  /var/lib/docker/volumes/open-webui/_data

restic "${RESTIC_OPTS[@]}" forget --keep-daily 14 --keep-weekly 4 --keep-monthly 6 --prune
restic "${RESTIC_OPTS[@]}" check

# Push heartbeat to Uptime Kuma only when backup + integrity check succeed
if [ -f /root/.config/restic/kuma-push-url ]; then
  curl -fsS --max-time 10 "$(cat /root/.config/restic/kuma-push-url)" > /dev/null || true
fi