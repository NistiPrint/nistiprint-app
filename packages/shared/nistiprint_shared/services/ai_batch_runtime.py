"""Bounded in-process starters for user-requested AI work."""
from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None
_capacity: threading.BoundedSemaphore | None = None


def start_background(callback, *args) -> bool:
    """Start immediately when a local coordinator slot is available."""
    global _executor, _capacity
    try:
        limit = max(1, min(8, int(os.getenv("AI_MANUAL_MAX_ACCOUNTS", "2"))))
    except (TypeError, ValueError):
        limit = 2
    with _lock:
        if _executor is None or _capacity is None:
            _executor = ThreadPoolExecutor(max_workers=limit, thread_name_prefix="ai-manual")
            _capacity = threading.BoundedSemaphore(limit)
        executor, capacity = _executor, _capacity
    if not capacity.acquire(blocking=False):
        return False

    def run():
        try:
            callback(*args)
        except Exception:
            logger.exception("Background AI extraction failed")
        finally:
            capacity.release()

    try:
        executor.submit(run)
    except Exception:
        capacity.release()
        raise
    return True
