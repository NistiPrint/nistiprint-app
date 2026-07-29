import json
import tempfile
import unittest
from collections import defaultdict
from unittest.mock import patch

from nistiprint_shared.services import reliable_ingest_queue as queue


class FakeRedis:
    def __init__(self):
        self.lists, self.hashes, self.zsets = defaultdict(list), defaultdict(dict), defaultdict(dict)
    def rpush(self, key, value): self.lists[key].append(value); return len(self.lists[key])
    def blmove(self, source, destination, **_):
        if not self.lists[source]: return None
        value = self.lists[source].pop(0); self.lists[destination].append(value); return value
    def hset(self, key, field, value): self.hashes[key][field] = value; return 1
    def hget(self, key, field): return self.hashes[key].get(field)
    def hdel(self, key, field): return int(self.hashes[key].pop(field, None) is not None)
    def hscan(self, key, **_): return 0, dict(self.hashes[key])
    def lrange(self, key, start, end): return self.lists[key][start:end + 1]
    def llen(self, key): return len(self.lists[key])
    def zcard(self, key): return len(self.zsets[key])
    def zrangebyscore(self, key, low, high, **_):
        return [value for value, score in self.zsets[key].items() if low <= score <= high]
    def eval(self, script, _keys, *args):
        if script == queue._FINISH_LUA:
            processing, leases, orphans, raw, event_id, token, destination, output = args
            lease = json.loads(self.hashes[leases].get(event_id, "{}"))
            if lease.get("token") != token or raw not in self.lists[processing]: return 0
            self.lists[processing].remove(raw)
            if destination: self.lists[destination].append(output)
            self.hashes[leases].pop(event_id, None); self.hashes[orphans].pop(raw, None); return 1
        if script == queue._RETRY_LUA:
            processing, leases, zset, orphans, raw, event_id, token, score, output = args
            lease = json.loads(self.hashes[leases].get(event_id, "{}"))
            if lease.get("token") != token or raw not in self.lists[processing]: return 0
            self.lists[processing].remove(raw); self.zsets[zset][output] = float(score)
            self.hashes[leases].pop(event_id, None); self.hashes[orphans].pop(raw, None); return 1
        if script == queue._PROMOTE_RETRY_LUA:
            zset, destination, raw = args
            if raw not in self.zsets[zset]: return 0
            self.zsets[zset].pop(raw); self.lists[destination].append(raw); return 1
        if script == queue._REAP_LEASE_LUA:
            processing, leases, ready, orphans, raw, event_id, token, now = args
            lease = json.loads(self.hashes[leases].get(event_id, "{}"))
            if lease.get("token") != token or lease.get("expires_at", 1e20) > now: return 0
            if raw not in self.lists[processing]: return 0
            self.lists[processing].remove(raw); self.lists[ready].append(raw)
            self.hashes[leases].pop(event_id, None); self.hashes[orphans].pop(raw, None); return 1
        raise AssertionError("unexpected script")


class ReliableQueueTest(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.envelope = queue.build_envelope("shopee", {"code": 3}, raw_body='{ "code": 3 }', event_id="evt-1")

    def test_preserves_raw_body_and_hash(self):
        self.assertEqual(self.envelope["raw_body"], '{ "code": 3 }')
        self.assertEqual(len(self.envelope["body_sha256"]), 64)

    def test_claim_token_prevents_stale_completion(self):
        queue.publish_envelope(self.envelope, self.redis)
        item = queue.claim(queue.INBOX_READY, queue.INBOX_PROCESSING, "worker", client=self.redis)
        stale = dict(item, _claim_token="stale")
        self.assertFalse(queue.complete(stale, queue.INBOX_PROCESSING, self.redis))
        self.assertTrue(queue.complete(item, queue.INBOX_PROCESSING, self.redis))

    def test_retry_move_and_promotion_are_atomic_contract(self):
        queue.publish_envelope(self.envelope, self.redis)
        item = queue.claim(queue.INBOX_READY, queue.INBOX_PROCESSING, "worker", client=self.redis)
        with patch.object(queue.time, "time", return_value=1000):
            self.assertTrue(queue.schedule_retry(item, queue.INBOX_PROCESSING, 1, self.redis))
        with patch.object(queue.time, "time", return_value=1061):
            self.assertEqual(queue.requeue_due_retries(self.redis), 1)
        self.assertEqual(self.redis.llen(queue.INBOX_READY), 1)

    def test_expired_lease_recovers_processing_item(self):
        queue.publish_envelope(self.envelope, self.redis)
        item = queue.claim(queue.INBOX_READY, queue.INBOX_PROCESSING, "worker", client=self.redis, lease_seconds=1)
        lease = json.loads(self.redis.hget(queue.LEASES_HASH, item["event_id"]))
        self.assertEqual(queue.reap_expired_leases(self.redis, now=lease["expires_at"] + 1), 1)
        self.assertEqual(self.redis.llen(queue.INBOX_READY), 1)

    def test_spool_replays_and_deletes_only_after_push(self):
        with tempfile.TemporaryDirectory() as directory:
            path = queue.spool_envelope(self.envelope, directory)
            self.assertTrue(path.exists())
            self.assertEqual(queue.replay_spool_once(self.redis, directory), 1)
            self.assertFalse(path.exists())
            self.assertEqual(self.redis.llen(queue.INBOX_READY), 1)


if __name__ == "__main__": unittest.main()
