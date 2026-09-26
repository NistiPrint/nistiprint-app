#!/usr/bin/env python3
"""Point the VPS applications at the Portainer-managed local Supabase stack.

Run on the VPS as root after the final restore. Values are read locally from
the stack environment file and are never printed.
"""

from pathlib import Path
from urllib.parse import quote
import os
import shutil
import stat
import tempfile


SOURCE = Path("/opt/nistiprint-supabase/.env")
BACKUP_DIR = Path("/root/nistiprint-supabase-migration")


def load_env(path):
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def update(path, values, backup_name, mode=None):
    original = path.read_text(encoding="utf-8")
    backup = BACKUP_DIR / backup_name
    if not backup.exists():
        shutil.copy2(path, backup)
        os.chmod(backup, 0o600)

    seen = set()
    lines = []
    for line in original.splitlines(keepends=True):
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in values:
                lines.append(f"{key}={values[key]}\n")
                seen.add(key)
                continue
        lines.append(line)
    if lines and not lines[-1].endswith("\n"):
        lines.append("\n")
    for key, value in values.items():
        if key not in seen:
            lines.append(f"{key}={value}\n")

    info = path.stat()
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".env-cutover-", delete=False) as handle:
        temporary = Path(handle.name)
        handle.writelines(lines)
        handle.flush()
        os.fsync(handle.fileno())
    os.chown(temporary, info.st_uid, info.st_gid)
    os.chmod(temporary, mode if mode is not None else stat.S_IMODE(info.st_mode))
    os.replace(temporary, path)
    print(f"Updated {path} ({', '.join(values)}); backup: {backup}")


def main():
    secrets = load_env(SOURCE)
    required = ("ANON_KEY", "SERVICE_ROLE_KEY", "POSTGRES_PASSWORD")
    if any(not secrets.get(key) for key in required):
        raise SystemExit("Missing required stack secrets")
    database_url = (
        "postgresql://postgres:"
        + quote(secrets["POSTGRES_PASSWORD"], safe="")
        + "@127.0.0.1:5432/postgres"
    )
    app_values = {
        "SUPABASE_URL": "http://127.0.0.1:8000",
        "SUPABASE_DB_URL": database_url,
        "SUPABASE_SERVICE_KEY": secrets["SERVICE_ROLE_KEY"],
        "SUPABASE_ANON_KEY": secrets["ANON_KEY"],
        "VITE_SUPABASE_URL": "https://app.nistiprint.neolabs.com.br",
    }
    update(Path("/opt/nistiprint/.env"), app_values, "app.env.pre-cutover", mode=0o600)
    update(
        Path("/opt/nistiprint/apps/frontend/.env"),
        {
            "VITE_SUPABASE_URL": "https://app.nistiprint.neolabs.com.br",
            "VITE_SUPABASE_ANON_KEY": secrets["ANON_KEY"],
        },
        "frontend.env.pre-cutover",
    )
    update(
        Path("/opt/nistiprint-legado/.env"),
        {
            "SUPABASE_URL": "http://127.0.0.1:8000",
            "SUPABASE_SERVICE_KEY": secrets["SERVICE_ROLE_KEY"],
            "SUPABASE_ANON_KEY": secrets["ANON_KEY"],
        },
        "legado.env.pre-cutover",
        mode=0o600,
    )


if __name__ == "__main__":
    main()
