#!/usr/bin/env python3
"""Report COPY blocks in a Cloud dump that the local Supabase DB cannot accept."""

from pathlib import Path
import re
import subprocess
import sys


dump_path = Path(sys.argv[1])
sql = """
select n.nspname, c.relname, a.attname
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
join pg_attribute a on a.attrelid = c.oid
where c.relkind in ('r', 'p') and a.attnum > 0 and not a.attisdropped
order by n.nspname, c.relname, a.attnum
"""
result = subprocess.run(
    ["docker", "exec", "supabase-db", "psql", "-U", "postgres", "-d", "postgres", "-At", "-F", "\t", "-c", sql],
    check=True,
    text=True,
    capture_output=True,
)
tables = {}
for line in result.stdout.splitlines():
    schema, table, column = line.split("\t", 2)
    tables.setdefault((schema, table), set()).add(column)

pattern = re.compile(r'^COPY "([^"]+)"\."([^"]+)" \((.*)\) FROM stdin;$')
current = None
row_count = 0
blocks = 0
problems = []
storage_blocks = []
with dump_path.open("r", encoding="utf-8") as stream:
    for line in stream:
        if current is None:
            match = pattern.match(line.rstrip("\n"))
            if match:
                schema, table, columns_text = match.groups()
                columns = [value.strip().strip('"') for value in columns_text.split(",")]
                current = (schema, table, columns)
                row_count = 0
                blocks += 1
        elif line.rstrip("\r\n") == r"\.":
            schema, table, columns = current
            if schema == "storage":
                storage_blocks.append((table, row_count))
            available = tables.get((schema, table))
            if available is None:
                problems.append((schema, table, row_count, "missing table"))
            else:
                missing_columns = sorted(set(columns) - available)
                if missing_columns:
                    problems.append((schema, table, row_count, "missing columns: " + ", ".join(missing_columns)))
            current = None
        else:
            row_count += 1

print(f"COPY blocks: {blocks}; incompatible blocks: {len(problems)}")
for schema, table, rows, issue in problems:
    print(f"{schema}.{table}: {rows} rows; {issue}")
if len(sys.argv) > 2 and sys.argv[2] == "--storage":
    for table, rows in storage_blocks:
        print(f"storage.{table}: {rows} rows")
