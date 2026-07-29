import json
import logging
import os
import time

import redis


logger = logging.getLogger(__name__)


BLING_RATE_LIMIT_PER_SECOND = int(os.environ.get("BLING_RATE_LIMIT_PER_SECOND", "3"))
BLING_RATE_LIMIT_GLOBAL_PER_SECOND = int(
    os.environ.get("BLING_RATE_LIMIT_GLOBAL_PER_SECOND", "12")
)
BLING_RATE_LIMIT_ACQUIRE_TIMEOUT_MS = int(
    os.environ.get("BLING_RATE_LIMIT_ACQUIRE_TIMEOUT_MS", "1200")
)
BLING_ORDER_DETAIL_CACHE_SECONDS = int(
    os.environ.get("BLING_ORDER_DETAIL_CACHE_SECONDS", "5")
)
BLING_ORDER_DETAIL_LOCK_MS = int(
    os.environ.get("BLING_ORDER_DETAIL_LOCK_MS", "1500")
)

_redis_client = None


def get_redis_client():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=os.environ.get("CACHE_REDIS_HOST", os.environ.get("REDIS_HOST", "redis-cache")),
            port=int(os.environ.get("CACHE_REDIS_PORT", os.environ.get("REDIS_PORT", 6379))),
            db=int(os.environ.get("CACHE_REDIS_DB", os.environ.get("REDIS_DB", 0))),
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis_client


class BlingRateLimitCoordinator:
    _ACQUIRE_SCRIPT = """
local account_key = KEYS[1]
local global_key = KEYS[2]
local account_limit = tonumber(ARGV[1])
local global_limit = tonumber(ARGV[2])
local ttl_ms = tonumber(ARGV[3])

local account_count = tonumber(redis.call('get', account_key) or '0')
local global_count = tonumber(redis.call('get', global_key) or '0')

if account_count >= account_limit or global_count >= global_limit then
  local account_ttl = redis.call('pttl', account_key)
  local global_ttl = redis.call('pttl', global_key)
  if account_ttl < 0 then account_ttl = ttl_ms end
  if global_ttl < 0 then global_ttl = ttl_ms end
  local wait_ms = math.max(account_ttl, global_ttl, 1)
  return {0, wait_ms, account_count, global_count}
end

account_count = redis.call('incr', account_key)
if account_count == 1 then
  redis.call('pexpire', account_key, ttl_ms)
end

global_count = redis.call('incr', global_key)
if global_count == 1 then
  redis.call('pexpire', global_key, ttl_ms)
end

return {1, 0, account_count, global_count}
"""

    _RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""

    def __init__(self, redis_client=None):
        self.redis = redis_client

    def acquire(
        self,
        *,
        integration_id,
        endpoint: str,
        account_limit: int | None = None,
        global_limit: int | None = None,
        max_wait_ms: int | None = None,
    ) -> dict:
        account_limit = int(account_limit or BLING_RATE_LIMIT_PER_SECOND)
        global_limit = int(global_limit or BLING_RATE_LIMIT_GLOBAL_PER_SECOND)
        max_wait_ms = int(max_wait_ms or BLING_RATE_LIMIT_ACQUIRE_TIMEOUT_MS)

        if not integration_id:
            return {"granted": True, "wait_ms": 0, "fallback": True}

        client = self.redis or get_redis_client()
        deadline = time.monotonic() + (max_wait_ms / 1000.0)

        while True:
            bucket = int(time.time())
            ttl_ms = max(50, int(((bucket + 1) - time.time()) * 1000) + 50)
            account_key = f"bling:rate:{integration_id}:{bucket}"
            global_key = f"bling:rate:global:{bucket}"
            allowed, wait_ms, account_count, global_count = client.eval(
                self._ACQUIRE_SCRIPT,
                2,
                account_key,
                global_key,
                account_limit,
                global_limit,
                ttl_ms,
            )
            if int(allowed) == 1:
                return {
                    "granted": True,
                    "wait_ms": 0,
                    "account_count": int(account_count),
                    "global_count": int(global_count),
                    "integration_id": integration_id,
                    "endpoint": endpoint,
                }

            wait_ms = max(1, int(wait_ms or 1))
            if time.monotonic() + (wait_ms / 1000.0) > deadline:
                return {
                    "granted": False,
                    "wait_ms": wait_ms,
                    "account_count": int(account_count or 0),
                    "global_count": int(global_count or 0),
                    "integration_id": integration_id,
                    "endpoint": endpoint,
                }
            time.sleep(wait_ms / 1000.0)

    def get_cached_order_detail(self, *, integration_id, order_id):
        if not integration_id or not order_id:
            return None
        client = self.redis or get_redis_client()
        payload = client.get(f"bling:order-detail-cache:{integration_id}:{order_id}")
        if not payload:
            return None
        try:
            return json.loads(payload)
        except Exception:
            logger.warning(
                "[bling-rate-limit] cache invalido integration_id=%s order_id=%s",
                integration_id,
                order_id,
            )
            return None

    def cache_order_detail(self, *, integration_id, order_id, payload: dict):
        if not integration_id or not order_id or not payload:
            return
        client = self.redis or get_redis_client()
        client.setex(
            f"bling:order-detail-cache:{integration_id}:{order_id}",
            BLING_ORDER_DETAIL_CACHE_SECONDS,
            json.dumps(payload, ensure_ascii=False, default=str),
        )

    def acquire_order_lock(self, *, integration_id, order_id) -> tuple[str | None, str | None]:
        if not integration_id or not order_id:
            return None, None
        client = self.redis or get_redis_client()
        key = f"bling:order-detail-lock:{integration_id}:{order_id}"
        value = f"{time.time():.6f}"
        acquired = client.set(key, value, nx=True, px=BLING_ORDER_DETAIL_LOCK_MS)
        return (key, value) if acquired else (None, None)

    def release_order_lock(self, lock_key: str | None, lock_value: str | None) -> None:
        if not lock_key or not lock_value:
            return
        client = self.redis or get_redis_client()
        try:
            client.eval(self._RELEASE_LOCK_SCRIPT, 1, lock_key, lock_value)
        except Exception as exc:
            logger.warning("[bling-rate-limit] falha ao liberar lock %s: %s", lock_key, exc)


bling_rate_limit_coordinator = BlingRateLimitCoordinator()
