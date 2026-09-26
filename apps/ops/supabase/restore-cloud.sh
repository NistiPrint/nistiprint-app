#!/usr/bin/env bash
# Restore a Supabase Platform export into the Portainer-managed local database.
set -euo pipefail
umask 077

dump_dir=${1:?directory containing roles.sql, schema.sql and data.sql required}
data_file=${2:-data.sql}
for file in roles.sql schema.sql "$data_file"; do
    test -s "$dump_dir/$file"
done

log_file="$dump_dir/restore.log"
if {
    cat "$dump_dir/roles.sql" "$dump_dir/schema.sql"
    printf '\nSET session_replication_role = replica;\n'
    cat "$dump_dir/$data_file"
} | docker exec -i supabase-db psql \
    --username postgres --dbname postgres \
    --single-transaction --set ON_ERROR_STOP=1 --file - \
    >"$log_file" 2>&1; then
    chmod 600 "$log_file"
    printf 'Restore completed successfully; log: %s\n' "$log_file"
else
    chmod 600 "$log_file"
    printf 'Restore failed; inspect restricted log: %s\n' "$log_file" >&2
    exit 1
fi
