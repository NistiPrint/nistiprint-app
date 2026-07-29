"""Idempotent JSONL.zst archival for operational ingest datasets."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from nistiprint_shared.database.supabase_db_service import supabase_db


DATASETS = (
    "webhook_payloads",
    "shopee_chat_payloads",
    "webhook_event_attempts",
    "task_execution_logs",
    "pedido_ingest_log",
    "integration_refresh_logs",
)


def _event_time(row: dict[str, Any]) -> datetime:
    for key in ("received_at", "event_time", "created_at", "started_at"):
        value = row.get(key)
        if value:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _jsonl(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in rows
    )


def _s3_client():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=os.getenv("INGEST_ARCHIVE_S3_ENDPOINT") or None,
        region_name=os.getenv("INGEST_ARCHIVE_S3_REGION") or None,
        aws_access_key_id=os.getenv("INGEST_ARCHIVE_S3_ACCESS_KEY") or None,
        aws_secret_access_key=os.getenv("INGEST_ARCHIVE_S3_SECRET_KEY") or None,
    )


def archive_dataset_once(dataset: str, *, now: datetime | None = None, client=None) -> int:
    if dataset not in DATASETS:
        raise ValueError(f"unsupported archive dataset: {dataset}")
    bucket = os.getenv("INGEST_ARCHIVE_S3_BUCKET")
    if not bucket:
        raise RuntimeError("INGEST_ARCHIVE_S3_BUCKET is required")
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)
    response = supabase_db.rpc("get_ingest_archive_batch", {
        "p_dataset": dataset,
        "p_before": cutoff.isoformat(),
        "p_limit": int(os.getenv("INGEST_ARCHIVE_BATCH_SIZE", "1000")),
    }).execute()
    rows = response.data or []
    if not isinstance(rows, list) or not rows:
        return 0

    import zstandard

    raw = _jsonl(rows)
    compressed = zstandard.ZstdCompressor(level=9).compress(raw)
    checksum = hashlib.sha256(compressed).hexdigest()
    times = [_event_time(row) for row in rows]
    ids = [str(row["id"]) for row in rows]
    identity = hashlib.sha256("\n".join(ids).encode()).hexdigest()[:24]
    object_key = (
        f"dataset={dataset}/dt={min(times).date().isoformat()}/"
        f"part-{identity}.jsonl.zst"
    )
    s3 = client or _s3_client()
    put_args = {
        "Bucket": bucket,
        "Key": object_key,
        "Body": compressed,
        "ContentType": "application/zstd",
        "Metadata": {"sha256": checksum, "schema-version": "1"},
    }
    encryption = os.getenv("INGEST_ARCHIVE_S3_ENCRYPTION", "AES256")
    if encryption:
        put_args["ServerSideEncryption"] = encryption
    s3.put_object(**put_args)
    head = s3.head_object(Bucket=bucket, Key=object_key)
    if int(head.get("ContentLength", -1)) != len(compressed):
        raise RuntimeError("archive object size verification failed")
    if (head.get("Metadata") or {}).get("sha256") != checksum:
        raise RuntimeError("archive object checksum metadata verification failed")

    supabase_db.rpc("finalize_ingest_archive_batch", {
        "p_dataset": dataset,
        "p_ids": ids,
        "p_object_key": object_key,
        "p_sha256": checksum,
        "p_period_start": min(times).date().isoformat(),
        "p_period_end": max(times).date().isoformat(),
        "p_row_count": len(rows),
        "p_schema_version": 1,
    }).execute()
    return len(rows)


def archive_all_once() -> int:
    total = sum(archive_dataset_once(dataset) for dataset in DATASETS)
    supabase_db.rpc("cleanup_archived_ingest_hot_data", {
        "p_limit": int(os.getenv("INGEST_ARCHIVE_BATCH_SIZE", "1000")),
    }).execute()
    return total
