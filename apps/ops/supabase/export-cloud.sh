#!/bin/sh
# Export a Supabase Platform project for a self-hosted restore.
# Run on a trusted host with Docker and the Supabase CLI available.
set -eu
umask 077

password_file=${1:?password file required}
output_dir=${2:?output directory required}
project_ref=${3:?project ref required}

test -r "$password_file"
mkdir -p "$output_dir"
chmod 700 "$output_dir"

encoded_password=$(python3 - "$password_file" <<'PY'
from pathlib import Path
from sys import argv
from urllib.parse import quote

password = Path(argv[1]).read_text(encoding='utf-8').rstrip('\r\n')
if not password:
    raise SystemExit('Cloud database password file is empty')
print(quote(password, safe=''))
PY
)

database_url="postgresql://postgres:${encoded_password}@db.${project_ref}.supabase.co:5432/postgres?sslmode=require"
unset encoded_password

dump() {
    name=$1
    shift
    if npx --yes supabase@2.116.0 db dump --network-id host --db-url "$database_url" -f "$output_dir/$name.sql" "$@" >"$output_dir/$name.log" 2>&1; then
        chmod 600 "$output_dir/$name.sql" "$output_dir/$name.log"
        printf '%s dump complete\n' "$name"
    else
        printf '%s dump failed; inspect restricted log %s\n' "$name" "$output_dir/$name.log" >&2
        exit 1
    fi
}

dump roles --role-only
dump schema
dump data --use-copy --data-only
unset database_url
