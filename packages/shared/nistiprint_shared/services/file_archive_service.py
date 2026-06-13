from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict


class FileArchiveService:
    def __init__(self) -> None:
        self.base_dir = Path(os.getenv("NISTIPRINT_LOG_ARCHIVE_DIR", str(Path.cwd() / "temp" / "log-archive")))
        self._lock = Lock()

    def _safe_name(self, value: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in (value or "unknown"))
        return safe.strip("_") or "unknown"

    def _archive_path(self, source: str, timestamp: str | None = None) -> Path:
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        day = ts[:10] if len(ts) >= 10 else datetime.now(timezone.utc).date().isoformat()
        return self.base_dir / self._safe_name(source) / f"dt={day}" / "events.jsonl"

    def append(self, source: str, payload: Dict[str, Any], timestamp: str | None = None) -> str:
        path = self._archive_path(source, timestamp)
        path.parent.mkdir(parents=True, exist_ok=True)

        record = {
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            **payload,
        }

        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

        return str(path)


file_archive_service = FileArchiveService()
