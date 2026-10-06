"""Account-scoped distributed request limiter for Mercado Livre workers."""
from __future__ import annotations

import os
import time

import redis


ACCOUNT_LIMIT_PER_SECOND = int(os.getenv("MERCADOLIVRE_API_RATE_LIMIT_PER_SECOND", "2"))
GLOBAL_LIMIT_PER_SECOND = int(os.getenv("MERCADOLIVRE_API_GLOBAL_RATE_LIMIT_PER_SECOND", "12"))
ACQUIRE_TIMEOUT_MS = int(os.getenv("MERCADOLIVRE_API_RATE_LIMIT_WAIT_MS", "10000"))


class MercadoLivreRateLimitWait(RuntimeError):
    def __init__(self, retry_after: float):
        self.retry_after = max(1.0, float(retry_after))
        super().__init__("Limite local de chamadas do Mercado Livre atingido")


class MercadoLivreRateLimitCoordinator:
    _ACQUIRE_SCRIPT = """
local account_key = KEYS[1]
local global_key = KEYS[2]
local account_limit = tonumber(ARGV[1])
local global_limit = tonumber(ARGV[2])
local window_ms = tonumber(ARGV[3])
local member = ARGV[4]
local now_parts = redis.call('time')
local now_ms = tonumber(now_parts[1]) * 1000 + math.floor(tonumber(now_parts[2]) / 1000)
local cutoff = now_ms - window_ms
redis.call('zremrangebyscore', account_key, '-inf', cutoff)
redis.call('zremrangebyscore', global_key, '-inf', cutoff)
local account_count = redis.call('zcard', account_key)
local global_count = redis.call('zcard', global_key)
if account_count >= account_limit or global_count >= global_limit then
  local account_first = redis.call('zrange', account_key, 0, 0, 'withscores')
  local global_first = redis.call('zrange', global_key, 0, 0, 'withscores')
  local account_wait = account_count >= account_limit and (tonumber(account_first[2]) + window_ms - now_ms) or 0
  local global_wait = global_count >= global_limit and (tonumber(global_first[2]) + window_ms - now_ms) or 0
  return {0, math.max(account_wait, global_wait, 1)}
end
redis.call('zadd', account_key, now_ms, member)
redis.call('zadd', global_key, now_ms, member)
redis.call('pexpire', account_key, window_ms * 2)
redis.call('pexpire', global_key, window_ms * 2)
return {1, 0}
"""

    def __init__(self, client=None):
        self.client = client

    def _redis(self):
        if self.client is None:
            self.client = redis.Redis.from_url(
                os.getenv("CELERY_BROKER_URL", "redis://redis-celery:6379/0"),
                decode_responses=True, socket_connect_timeout=2, socket_timeout=2,
            )
        return self.client

    def acquire(self, integration_id: int, endpoint: str = "unknown") -> None:
        if int(integration_id) <= 0:
            raise ValueError("integration_id deve ser positivo para limitar chamadas")
        deadline = time.monotonic() + ACQUIRE_TIMEOUT_MS / 1000.0
        while True:
            allowed, wait_ms = self._redis().eval(
                self._ACQUIRE_SCRIPT, 2,
                f"mercadolivre:api:rate:{int(integration_id)}",
                "mercadolivre:api:rate:global",
                max(1, ACCOUNT_LIMIT_PER_SECOND), max(1, GLOBAL_LIMIT_PER_SECOND), 1000,
                f"{os.getpid()}:{time.time_ns()}:{endpoint}",
            )
            if int(allowed) == 1:
                return
            wait_seconds = max(0.01, int(wait_ms or 1) / 1000.0)
            if time.monotonic() + wait_seconds > deadline:
                raise MercadoLivreRateLimitWait(wait_seconds)
            time.sleep(wait_seconds)


mercadolivre_rate_limit_coordinator = MercadoLivreRateLimitCoordinator()
