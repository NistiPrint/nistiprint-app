#!/usr/bin/env python3
"""Remove known empty Cloud COPY blocks incompatible with self-hosted services."""

from pathlib import Path
import os
import re
import sys


source = Path(sys.argv[1])
target = Path(sys.argv[2])
if source.resolve() == target.resolve():
    raise SystemExit("Source and target must differ")

skip_tables = {
    ("auth", "audit_log_entries"),
    ("auth", "mfa_recovery_code_sets"),
    ("auth", "mfa_recovery_codes"),
    ("auth", "one_time_tokens"),
    ("auth", "scim_tokens"),
    ("auth", "scim_users"),
    ("storage", "buckets_vectors"),
    ("storage", "vector_indexes"),
}
pattern = re.compile(r'^COPY "([^"]+)"\."([^"]+)" \(.*\) FROM stdin;$')
found = set()
skipping = None
os.umask(0o077)
with source.open("r", encoding="utf-8") as reader, target.open("w", encoding="utf-8") as writer:
    for line in reader:
        if skipping:
            if line.rstrip("\r\n") != r"\.":
                raise SystemExit(f"Refusing to skip nonempty COPY block: {skipping[0]}.{skipping[1]}")
            found.add(skipping)
            skipping = None
            continue
        match = pattern.match(line.rstrip("\r\n"))
        if match and match.groups() in skip_tables:
            skipping = match.groups()
            continue
        writer.write(line)

if skipping:
    raise SystemExit("Unterminated COPY block")
if found != skip_tables:
    raise SystemExit(f"Expected {len(skip_tables)} empty compatibility blocks; found {len(found)}")
print(f"Removed {len(found)} empty COPY blocks; original dump preserved")
