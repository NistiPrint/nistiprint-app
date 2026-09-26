#!/bin/sh
set -eu

if [ -z "${RCLONE_CONFIG_S3_ACCESS_KEY_ID:-}" ] ||
   [ -z "${RCLONE_CONFIG_S3_SECRET_ACCESS_KEY:-}" ] ||
   [ -z "${RCLONE_CONFIG_S3_ENDPOINT:-}" ] ||
   [ -z "${RCLONE_CONFIG_S3_REGION:-}" ] ||
   [ -z "${RCLONE_CONFIG_ENCRYPTED_PASSWORD:-}" ] ||
   [ -z "${RCLONE_CONFIG_ENCRYPTED_PASSWORD2:-}" ] ||
   [ -z "${BACKUP_S3_BUCKET:-}" ]; then
  echo "Off-site backup credentials and bucket configuration are required" >&2
  exit 1
fi

rclone lsd encrypted: >/dev/null
while true; do
  # WAL is visible here after PostgreSQL has completed each segment.
  rclone move --min-age 2m --transfers 2 /wal encrypted:wal --log-level INFO

  # Base backup directories appear only after pg_basebackup exits successfully.
  for directory in /base/*; do
    [ -d "$directory" ] || continue
    case "$directory" in */.incomplete-*) continue ;; esac
    name=${directory##*/}
    rclone move --min-age 15m --transfers 1 "$directory" "encrypted:base/$name" --log-level INFO
    rmdir "$directory" 2>/dev/null || true
  done

  rclone delete --min-age "${BACKUP_WAL_RETENTION_HOURS:-744}h" encrypted:wal
  rclone delete --min-age "${BACKUP_BASE_RETENTION_HOURS:-720}h" encrypted:base
  touch /tmp/backup-uploader-ok
  sleep 60
done
