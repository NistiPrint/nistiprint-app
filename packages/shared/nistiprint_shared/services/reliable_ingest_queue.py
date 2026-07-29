"""Reliable Redis-list transport for external webhook envelopes.

The HTTP path only builds and durably publishes an envelope. Database access,
signature validation and domain processing happen after the acknowledgement.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import redis

logger = logging.getLogger(__name__)

INBOX_READY = "np:ingest:inbox:ready:v1"
INBOX_PROCESSING = "np:ingest:inbox:processing:v1"
ORDERS_READY = "np:ingest:orders:ready:v1"
ORDERS_PROCESSING = "np:ingest:orders:processing:v1"
CHAT_READY = "np:ingest:chat:ready:v1"
CHAT_PROCESSING = "np:ingest:chat:processing:v1"
RETRY_ZSET = "np:ingest:retry:v1"
LEASES_HASH = "np:ingest:leases:v1"
ORPHANS_HASH = "np:ingest:orphans:v1"
DLQ = "np:ingest:dlq:v1"

QUEUE_PAIRS = {
    INBOX_PROCESSING: INBOX_READY,
    ORDERS_PROCESSING: ORDERS_READY,
    CHAT_PROCESSING: CHAT_READY,
}
READY_QUEUES = frozenset(QUEUE_PAIRS.values())
MAX_ENVELOPE_BYTES = int(os.getenv("WEBHOOK_MAX_ENVELOPE_BYTES", str(1_250_000)))
DEFAULT_LEASE_SECONDS = int(os.getenv("INGEST_LEASE_SECONDS", "300"))
DEFAULT_ORPHAN_GRACE_SECONDS = int(os.getenv("INGEST_ORPHAN_GRACE_SECONDS", "30"))
RETRY_DELAYS = (60, 300, 900, 3600, 14400, 43200)

_FINISH_LUA = """
local lease_raw = redis.call('HGET', KEYS[2], ARGV[2])
if not lease_raw then return 0 end
local lease = cjson.decode(lease_raw)
if lease.token ~= ARGV[3] then return 0 end
local removed = redis.call('LREM', KEYS[1], 1, ARGV[1])
if removed ~= 1 then return 0 end
if ARGV[4] ~= '' then redis.call('RPUSH', ARGV[4], ARGV[5]) end
redis.call('HDEL', KEYS[2], ARGV[2])
redis.call('HDEL', KEYS[3], ARGV[1])
return 1
"""

_RETRY_LUA = """
local lease_raw = redis.call('HGET', KEYS[2], ARGV[2])
if not lease_raw then return 0 end
local lease = cjson.decode(lease_raw)
if lease.token ~= ARGV[3] then return 0 end
local removed = redis.call('LREM', KEYS[1], 1, ARGV[1])
if removed ~= 1 then return 0 end
redis.call('ZADD', KEYS[3], ARGV[4], ARGV[5])
redis.call('HDEL', KEYS[2], ARGV[2])
redis.call('HDEL', KEYS[4], ARGV[1])
return 1
"""

_PROMOTE_RETRY_LUA = """
if redis.call('ZREM', KEYS[1], ARGV[1]) ~= 1 then return 0 end
redis.call('RPUSH', KEYS[2], ARGV[1])
return 1
"""

_REAP_LEASE_LUA = """
local lease_raw = redis.call('HGET', KEYS[2], ARGV[2])
if not lease_raw then return 0 end
local lease = cjson.decode(lease_raw)
if lease.token ~= ARGV[3] or tonumber(lease.expires_at) > tonumber(ARGV[4]) then return 0 end
local removed = redis.call('LREM', KEYS[1], 1, ARGV[1])
if removed ~= 1 then return 0 end
redis.call('RPUSH', KEYS[3], ARGV[1])
redis.call('HDEL', KEYS[2], ARGV[2])
redis.call('HDEL', KEYS[4], ARGV[1])
return 1
"""

_REAP_ORPHAN_LUA = """
if ARGV[2] ~= '' and redis.call('HGET', KEYS[2], ARGV[2]) then
  redis.call('HDEL', KEYS[3], ARGV[1])
  return 0
end
local first_seen = redis.call('HGET', KEYS[3], ARGV[1])
if not first_seen then
  redis.call('HSET', KEYS[3], ARGV[1], ARGV[3])
  return 0
end
if tonumber(ARGV[3]) - tonumber(first_seen) < tonumber(ARGV[4]) then return 0 end
local removed = redis.call('LREM', KEYS[1], 1, ARGV[1])
if removed ~= 1 then
  redis.call('HDEL', KEYS[3], ARGV[1])
  return 0
end
redis.call('RPUSH', KEYS[4], ARGV[1])
redis.call('HDEL', KEYS[3], ARGV[1])
return 1
"""


def redis_client() -> redis.Redis:
    return redis.Redis.from_url(
        os.getenv("INGEST_REDIS_URL", "redis://redis:6379/0"),
        decode_responses=True,
        socket_connect_timeout=1.5,
        socket_timeout=5.0,
        health_check_interval=30,
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def build_envelope(source: str, payload: Any, headers: Optional[dict[str, str]] = None, *,
                   raw_body: str | bytes | None = None, event_id: str | None = None,
                   received_at: str | None = None,
                   provider_delivery_id: str | None = None) -> dict[str, Any]:
    """Build the versioned envelope while preserving the provider body."""
    allowed = {
        "content-type", "user-agent", "x-bling-signature-256",
        "x-hub-signature", "x-hub-signature-256", "x-request-id", "x-signature",
        "x-shopee-signature",
    }
    safe_headers = {str(k).lower(): str(v)[:2048] for k, v in (headers or {}).items()
                    if str(k).lower() in allowed}
    if isinstance(raw_body, bytes):
        raw = raw_body.decode("utf-8", errors="strict")
    elif isinstance(raw_body, str):
        raw = raw_body
    else:
        raw = _canonical_json(payload)
    envelope = {
        "schema_version": 1,
        "event_id": event_id or str(uuid.uuid4()),
        "source": str(source or "").strip().lower(),
        "received_at": received_at or datetime.now(timezone.utc).isoformat(),
        "headers": safe_headers,
        "raw_body": raw,
        "parsed_payload": payload if isinstance(payload, (dict, list)) else None,
        "body_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "provider_delivery_id": str(provider_delivery_id) if provider_delivery_id not in (None, "") else None,
        "attempt": 0,
    }
    envelope["payload"] = envelope["parsed_payload"]  # compatibility during rollout
    if len(serialize(envelope).encode("utf-8")) > MAX_ENVELOPE_BYTES:
        raise ValueError("webhook envelope exceeds configured size limit")
    return envelope


def serialize(envelope: dict[str, Any]) -> str:
    return _canonical_json({k: v for k, v in envelope.items() if not k.startswith("_")})


def publish_envelope(envelope: dict[str, Any], client: Optional[redis.Redis] = None) -> str:
    raw = serialize(envelope)
    if len(raw.encode("utf-8")) > MAX_ENVELOPE_BYTES:
        raise ValueError("webhook envelope exceeds configured size limit")
    (client or redis_client()).rpush(INBOX_READY, raw)
    return str(envelope["event_id"])


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def spool_envelope(envelope: dict[str, Any], spool_dir: Optional[str] = None) -> Path:
    raw = serialize(envelope)
    if len(raw.encode("utf-8")) > MAX_ENVELOPE_BYTES:
        raise ValueError("webhook envelope exceeds configured size limit")
    root = Path(spool_dir or os.getenv("WEBHOOK_SPOOL_DIR", "/data/webhook-spool"))
    ready = root / "ready"
    ready.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = ready / f"{envelope['event_id']}.json"
    temporary = ready / f".{envelope['event_id']}.{uuid.uuid4().hex}.tmp"
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    os.replace(temporary, target)
    _fsync_directory(ready)
    return target


def replay_spool_once(client: Optional[redis.Redis] = None, spool_dir: Optional[str] = None,
                      *, limit: int = 100) -> int:
    """Delete a spool file only after a confirmed RPUSH."""
    r = client or redis_client()
    root = Path(spool_dir or os.getenv("WEBHOOK_SPOOL_DIR", "/data/webhook-spool"))
    ready, processing = root / "ready", root / "processing"
    ready.mkdir(parents=True, exist_ok=True, mode=0o700)
    processing.mkdir(parents=True, exist_ok=True, mode=0o700)
    for abandoned in processing.glob("*.json"):
        os.replace(abandoned, ready / abandoned.name)
    replayed = 0
    for source_path in sorted(ready.glob("*.json"))[:limit]:
        claimed_path = processing / source_path.name
        try:
            os.replace(source_path, claimed_path)
            raw = claimed_path.read_text(encoding="utf-8")
            envelope = json.loads(raw)
            if str(envelope.get("event_id")) != claimed_path.stem:
                raise ValueError("spool filename/event_id mismatch")
            if len(raw.encode("utf-8")) > MAX_ENVELOPE_BYTES:
                raise ValueError("spooled envelope exceeds configured size limit")
            r.rpush(INBOX_READY, raw)
            claimed_path.unlink()
            _fsync_directory(processing)
            replayed += 1
        except Exception:
            logger.exception("failed to replay spool file %s", claimed_path)
            if claimed_path.exists():
                os.replace(claimed_path, source_path)
            break
    return replayed


def claim(queue: str, processing: str, worker: str, timeout: int = 5,
          client: Optional[redis.Redis] = None, *,
          lease_seconds: int = DEFAULT_LEASE_SECONDS) -> Optional[dict[str, Any]]:
    if QUEUE_PAIRS.get(processing) != queue:
        raise ValueError("invalid ready/processing queue pair")
    r = client or redis_client()
    raw = r.blmove(queue, processing, timeout=timeout, src="LEFT", dest="RIGHT")
    if not raw:
        return None
    envelope = json.loads(raw)
    event_id = str(envelope["event_id"])
    now, token = time.time(), uuid.uuid4().hex
    lease = {"token": token, "worker": worker, "claimed_at": now,
             "expires_at": now + max(1, lease_seconds), "ready": queue,
             "processing": processing, "raw": raw}
    r.hset(LEASES_HASH, event_id, _canonical_json(lease))
    r.hdel(ORPHANS_HASH, raw)
    envelope.update(_claim_token=token, _raw=raw, _processing=processing)
    return envelope


def renew_lease(envelope: dict[str, Any], *, lease_seconds: int = DEFAULT_LEASE_SECONDS,
                client: Optional[redis.Redis] = None) -> bool:
    r, event_id = client or redis_client(), str(envelope["event_id"])
    raw = r.hget(LEASES_HASH, event_id)
    if not raw:
        return False
    lease = json.loads(raw)
    if lease.get("token") != envelope.get("_claim_token"):
        return False
    lease["expires_at"] = time.time() + max(1, lease_seconds)
    r.hset(LEASES_HASH, event_id, _canonical_json(lease))
    return True


def _finish(envelope: dict[str, Any], processing: str, destination: Optional[str],
            client: Optional[redis.Redis] = None, *, destination_raw: str | None = None) -> bool:
    r = client or redis_client()
    return bool(r.eval(_FINISH_LUA, 3, processing, LEASES_HASH, ORPHANS_HASH,
                       envelope["_raw"], str(envelope["event_id"]),
                       envelope["_claim_token"], destination or "",
                       destination_raw or envelope["_raw"]))


def complete(envelope: dict[str, Any], processing: str,
             client: Optional[redis.Redis] = None) -> bool:
    return _finish(envelope, processing, None, client)


def forward(envelope: dict[str, Any], processing: str, destination: str,
            client: Optional[redis.Redis] = None) -> bool:
    if destination not in READY_QUEUES:
        raise ValueError("invalid ingest destination")
    return _finish(envelope, processing, destination, client,
                   destination_raw=serialize(envelope))


def move_to_dlq(envelope: dict[str, Any], processing: str,
                client: Optional[redis.Redis] = None, *, reason: str | None = None) -> bool:
    dead = {k: v for k, v in envelope.items() if not k.startswith("_")}
    dead["dlq_at"] = datetime.now(timezone.utc).isoformat()
    dead["dlq_reason"] = str(reason or "terminal_error")[:500]
    return _finish(envelope, processing, DLQ, client, destination_raw=serialize(dead))


def schedule_retry(envelope: dict[str, Any], processing: str, attempt: int,
                   client: Optional[redis.Redis] = None, *,
                   retry_after: float | None = None) -> bool:
    r, ready = client or redis_client(), QUEUE_PAIRS.get(processing)
    if not ready:
        raise ValueError("unknown processing queue")
    default_delay = RETRY_DELAYS[min(max(attempt - 1, 0), len(RETRY_DELAYS) - 1)]
    delay = max(1.0, float(retry_after if retry_after is not None else default_delay))
    retry = {k: v for k, v in envelope.items() if not k.startswith("_")}
    retry.update(attempt=attempt, retry_queue=ready,
                 next_attempt_at=datetime.fromtimestamp(time.time() + delay, tz=timezone.utc).isoformat())
    return bool(r.eval(_RETRY_LUA, 4, processing, LEASES_HASH, RETRY_ZSET,
                       ORPHANS_HASH, envelope["_raw"], str(envelope["event_id"]),
                       envelope["_claim_token"], time.time() + delay, serialize(retry)))


def requeue_due_retries(client: Optional[redis.Redis] = None, limit: int = 100) -> int:
    r, count = client or redis_client(), 0
    for raw in r.zrangebyscore(RETRY_ZSET, 0, time.time(), start=0, num=limit):
        try:
            destination = json.loads(raw).get("retry_queue")
        except (TypeError, ValueError):
            destination = None
        if destination not in READY_QUEUES:
            logger.error("retry member has invalid destination")
            continue
        count += int(r.eval(_PROMOTE_RETRY_LUA, 2, RETRY_ZSET, destination, raw))
    return count


def reap_expired_leases(client: Optional[redis.Redis] = None, *, now: float | None = None,
                        scan_count: int = 500) -> int:
    r, current, recovered, cursor = client or redis_client(), now or time.time(), 0, 0
    while True:
        cursor, leases = r.hscan(LEASES_HASH, cursor=cursor, count=scan_count)
        for event_id, lease_raw in leases.items():
            try:
                lease = json.loads(lease_raw)
                processing, ready, raw = lease["processing"], lease["ready"], lease["raw"]
                token, expires_at = lease["token"], float(lease["expires_at"])
            except (KeyError, TypeError, ValueError):
                logger.error("malformed lease for event %s", event_id)
                continue
            if expires_at > current or QUEUE_PAIRS.get(processing) != ready:
                continue
            recovered += int(r.eval(_REAP_LEASE_LUA, 4, processing, LEASES_HASH,
                                    ready, ORPHANS_HASH, raw, event_id, token, current))
        if cursor == 0:
            break
    return recovered


def reap_orphaned_processing(client: Optional[redis.Redis] = None, *, now: float | None = None,
                             grace_seconds: int = DEFAULT_ORPHAN_GRACE_SECONDS,
                             limit_per_queue: int = 500) -> int:
    """Recover the narrow BLMOVE-to-HSET crash window after a grace period."""
    r, current, recovered = client or redis_client(), now or time.time(), 0
    for processing, ready in QUEUE_PAIRS.items():
        for raw in r.lrange(processing, 0, max(0, limit_per_queue - 1)):
            try:
                event_id = str(json.loads(raw)["event_id"])
            except Exception:
                event_id = ""
            recovered += int(r.eval(_REAP_ORPHAN_LUA, 4, processing, LEASES_HASH,
                                    ORPHANS_HASH, ready, raw, event_id, current,
                                    max(1, grace_seconds)))
    return recovered


def queue_lengths(client: Optional[redis.Redis] = None) -> dict[str, int]:
    r = client or redis_client()
    keys = (INBOX_READY, INBOX_PROCESSING, ORDERS_READY, ORDERS_PROCESSING,
            CHAT_READY, CHAT_PROCESSING, DLQ)
    result = {key: int(r.llen(key)) for key in keys}
    result[RETRY_ZSET], result[LEASES_HASH] = int(r.zcard(RETRY_ZSET)), int(r.hlen(LEASES_HASH))
    return result
