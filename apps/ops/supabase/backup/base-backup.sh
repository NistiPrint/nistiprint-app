#!/bin/sh
set -eu

interval=${BASE_BACKUP_INTERVAL_SECONDS:-86400}
while true; do
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  work="/backups/.incomplete-${stamp}"
  ready="/backups/${stamp}"
  mkdir -p "$work"

  if pg_basebackup --host="$PGHOST" --port="$PGPORT" --username="$PGUSER" \
      --pgdata="$work" --format=tar --gzip --wal-method=stream --progress; then
    mv "$work" "$ready"
    date +%s > /backups/.last-success
    echo "Base backup completed: ${stamp}"
    sleep "$interval"
  else
    rm -rf "$work"
    echo "Base backup failed; retrying in five minutes" >&2
    sleep 300
  fi
done
