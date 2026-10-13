import copy
import os
import threading
import time
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from nistiprint_shared.services import mercadolivre_ai_batch as batch_service
from nistiprint_shared.services import mercadolivre_personalization_service as service
from nistiprint_shared.services.ai.base import AIProviderError, AIResponse, retry_after_seconds


class Ledger:
    """Thread-safe RPC fixture; real SQL transitions have their own PG suite."""
    def __init__(self, size=12):
        self.lock = threading.RLock()
        self.batch = dict(id="batch", marketplace_integration_id=7, phase="FIRST_PASS", status="PENDING",
                          total=size, processed=0, success_count=0, failed_count=0, running_count=0,
                          retry_pending_count=0, retry_total=0, retry_processed=0, force=False)
        self.items = [dict(pack_id=str(index), phase="FIRST_PASS", status="PENDING", attempts=0,
                           first_pass_done=False, next_attempt_at="2000-01-01T00:00:00+00:00")
                      for index in range(size)]

    def table(self, name):
        ledger = self
        class Query:
            def __init__(self): self.filters = []
            def select(self, *_a, **_k): return self
            def eq(self, key, value):
                if key not in ("batch_id", "id", "marketplace_integration_id"):
                    self.filters.append(lambda row: row.get(key) == value)
                return self
            def lte(self, key, value):
                self.filters.append(lambda row: str(row.get(key)) <= str(value)); return self
            def limit(self, *_a): return self
            def order(self, *_a, **_k): return self
            def execute(self):
                with ledger.lock:
                    rows = [ledger.batch] if name.endswith("batches") else ledger.items
                    return SimpleNamespace(data=copy.deepcopy([row for row in rows if all(fn(row) for fn in self.filters)]))
        return Query()

    def rpc(self, name, params):
        with self.lock:
            if name == "ml_ai_claim_batch":
                self.batch.update(status="RUNNING", run_token=params["p_token"])
                return [copy.deepcopy(self.batch)]
            if name == "ml_ai_release_batch":
                pending = [item for item in self.items if item["status"] == "RETRY_PENDING"]
                self.batch.update(status="PENDING" if pending else "COMPLETED",
                                  phase="RETRY" if pending else "DONE", available_at=service._now())
                return [copy.deepcopy(self.batch)]
            item = next(item for item in self.items if item["pack_id"] == params["p_pack_id"])
            if name == "ml_ai_claim_item":
                if item["status"] not in ("PENDING", "RETRY_PENDING"): return []
                was_retry = item["status"] == "RETRY_PENDING"
                item.update(status="RUNNING", attempts=item["attempts"] + 1)
                self.batch["running_count"] += 1
                self.batch["retry_pending_count"] -= int(was_retry)
                return [copy.deepcopy(item)]
            if name == "ml_ai_finish_item":
                if item["status"] != "RUNNING": return False
                outcome = params["p_status"]
                if not item["first_pass_done"]:
                    self.batch["processed"] += 1
                    item["first_pass_done"] = True
                self.batch["running_count"] -= 1
                if outcome == "RETRY_PENDING":
                    self.batch["retry_pending_count"] += 1
                    self.batch["retry_total"] += 1
                else:
                    self.batch["success_count" if outcome == "COMPLETED" else "failed_count"] += 1
                    if item["phase"] == "RETRY": self.batch["retry_processed"] += 1
                item.update(status=outcome, phase="RETRY" if outcome == "RETRY_PENDING" else item["phase"],
                            next_attempt_at=params.get("p_next_at") or service._now())
                return True
            raise AssertionError(name)


class MercadoLivreDeferredRetryTests(unittest.TestCase):
    def test_clients_use_company_wide_credentials_and_ignore_legacy_account_keys(self):
        env = {
            "NISTIPRINT_AI_KEY": "company-gemini",
            "OPENROUTER_API_KEY": "company-openrouter",
            "MERCADOLIVRE_PERSONALIZACAO_GEMINI_API_KEY_7": "legacy-gemini-key",
            "MERCADOLIVRE_PERSONALIZACAO_OPENROUTER_API_KEY_7": "legacy-account-key",
        }
        with patch.dict(os.environ, env, clear=True):
            clients = batch_service.BatchClients({"provider": "openrouter"})
        self.assertEqual(clients.keys["openrouter"], "company-openrouter")
        self.assertEqual(clients.keys["gemini"], "company-gemini")

    def test_missing_company_wide_credential_is_reported_as_non_retryable(self):
        with patch.dict(os.environ, {
            "MERCADOLIVRE_PERSONALIZACAO_OPENROUTER_API_KEY_7": "legacy-account-key",
        }, clear=True):
            clients = batch_service.BatchClients({"provider": "openrouter"})
        with self.assertRaisesRegex(AIProviderError, "Credencial.*openrouter") as raised:
            clients.complete("FIRST_PASS", "prompt", "payload", {})
        self.assertFalse(raised.exception.retryable)

    def test_individual_processing_uses_shared_provider_credential(self):
        response = AIResponse(text='{"ok": true}', provider="openrouter", model_requested="openrouter/auto")
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "company-openrouter"}, clear=True), \
             patch("nistiprint_shared.services.ai.openrouter_provider.OpenRouterProvider") as provider:
            provider.return_value.complete.return_value = response
            parsed, actual_response = service._ai_response(
                7, {"provider": "openrouter", "model_name": "openrouter/auto", "timeout_seconds": 45},
                "system", "payload",
            )
        self.assertEqual(parsed, {"ok": True})
        self.assertIs(actual_response, response)
        provider.assert_called_once_with(model="openrouter/auto", api_key="company-openrouter", timeout=45.0)

    def _run(self, ledger, process):
        with patch.object(batch_service, "supabase_db", ledger), patch.object(batch_service, "_rpc", side_effect=ledger.rpc), \
             patch.object(service, "_integration"), patch.object(service, "_settings", return_value={
                 "provider": "gemini", "fallback_provider": "openrouter", "model_name": "gemini-2.5-flash"}), \
             patch.object(service, "_sync_batch_operation"), patch.object(service, "_renew_batch_lease"), \
             patch.object(service, "process_pack", side_effect=process), \
             patch.dict(os.environ, {"OPENROUTER_API_KEY": "test"}):
            return service.process_batch(7, "batch")

    def test_all_first_attempts_finish_before_retry_and_successes_are_never_replayed(self):
        ledger = Ledger()
        calls = []
        lock = threading.Lock()
        def process(_account, pack, **kwargs):
            phase = kwargs["execution_context"]["phase"]
            with lock: calls.append((pack, phase))
            if pack == "0" and phase == "FIRST_PASS": raise AIProviderError("timeout")
            return {"status": "success"}
        first = self._run(ledger, process)
        self.assertEqual(first["status"], "waiting_retry")
        self.assertEqual((ledger.batch["processed"], ledger.batch["success_count"]), (12,11))
        self.assertEqual({phase for _,phase in calls}, {"FIRST_PASS"})
        ledger.items[0]["next_attempt_at"] = "2000-01-01T00:00:00+00:00"
        second = self._run(ledger, process)
        self.assertEqual(second["status"], "completed")
        self.assertEqual(calls[-1], ("0", "RETRY"))
        self.assertEqual(len(calls), 13)
        self.assertEqual(ledger.batch["processed"], 12)
        self.assertEqual(ledger.batch["success_count"], 12)

    def test_second_failure_is_terminal_and_does_not_reset_first_pass_progress(self):
        ledger = Ledger(1)
        process = Mock(side_effect=AIProviderError("unavailable"))
        self._run(ledger, process)
        ledger.items[0]["next_attempt_at"] = "2000-01-01T00:00:00+00:00"
        self._run(ledger, process)
        self.assertEqual(process.call_count,2)
        self.assertEqual(ledger.items[0]["attempts"],2)
        self.assertEqual(ledger.batch["processed"],1)
        self.assertEqual(ledger.batch["failed_count"],1)
        self.assertEqual(ledger.batch["status"],"COMPLETED")

    def test_retry_after_is_saved_instead_of_sleeping_in_worker(self):
        item = dict(pack_id="p", attempts=1)
        rpc = Mock(side_effect=[[item],True])
        clients = Mock(has_fallback=False, settings={})
        clients.selection.return_value = ("gemini","test")
        error = AIProviderError("429",status_code=429,retry_after=75)
        fake_service = Mock()
        fake_service.process_pack.side_effect = error
        started = time.time()
        with patch.object(batch_service,"_rpc",rpc), patch.object(time,"sleep") as sleep, \
             patch.object(time,"time",return_value=1_700_000_000):
            batch_service._run_item(fake_service,{"id":"b","run_token":"r","marketplace_integration_id":7,"phase":"FIRST_PASS"},item,clients)
        values = rpc.call_args.args[1]
        self.assertEqual(values["p_status"],"RETRY_PENDING")
        self.assertEqual(datetime.fromisoformat(values["p_next_at"]).timestamp(),1_700_000_075)
        sleep.assert_not_called()

    def test_saved_response_resumes_persistence_without_calling_the_model(self):
        payload = {"p_records":[{}],"p_status":"SUCCESS"}
        context = {"prepared_payload":payload,"metrics":{"provider":"gemini"}}
        with patch.object(batch_service,"_rpc",return_value={"saved":1,"status":"SUCCESS"}) as rpc, \
             patch.object(service,"_ai_response") as ai, patch.object(service,"_integration") as integration:
            result = service.process_pack(7,"p",batch_id="b",run_token="t",execution_context=context)
        self.assertTrue(result["ledger_completed"])
        ai.assert_not_called()
        integration.assert_not_called()
        self.assertEqual(rpc.call_args.args[0],"ml_ai_persist_result")

    def test_primary_failure_does_not_call_fallback_and_clients_are_reused(self):
        with patch.dict(os.environ, {"NISTIPRINT_AI_KEY":"g", "OPENROUTER_API_KEY":"o"}), \
             patch.object(batch_service,"GeminiProvider") as primary, patch.object(batch_service,"OpenRouterProvider") as fallback:
            primary.return_value.complete.side_effect = AIProviderError("timeout")
            fallback.return_value.complete.return_value = AIResponse(text="{}",provider="openrouter",model_requested="auto")
            clients = batch_service.BatchClients({"provider":"gemini","model_name":"gemini-2.5-flash","fallback_provider":"openrouter","timeout_seconds":45})
            for _ in range(2):
                with self.assertRaises(AIProviderError): clients.complete("FIRST_PASS","prompt","data",{})
            fallback.assert_not_called()
            primary.assert_called_once_with(model="gemini-2.5-flash",api_key="g",timeout=45,retry_attempts=1)
            clients.complete("RETRY","prompt","data",{})
            self.assertEqual(fallback.return_value.complete.call_count,1)
            clients.close()
            primary.return_value.close.assert_called_once()
            fallback.return_value.close.assert_called_once()

    def test_permanent_configuration_failure_without_fallback_is_not_retried(self):
        self.assertFalse(batch_service.retry_eligible(AIProviderError("401",retryable=False),Mock(has_fallback=False)))
        self.assertTrue(batch_service.retry_eligible(AIProviderError("401",retryable=False),Mock(has_fallback=True)))
        self.assertFalse(batch_service.retry_eligible(LookupError("missing conversation"),Mock(has_fallback=True)))

    def test_delivery_without_item_lease_does_not_call_ai(self):
        fake_service = Mock()
        with patch.object(batch_service,"_rpc",return_value=[]):
            result = batch_service._run_item(fake_service,{"id":"b","run_token":"r"},{"pack_id":"p"},Mock())
        self.assertEqual(result["status"],"ignored")
        fake_service.process_pack.assert_not_called()

    def test_retry_after_accepts_http_date_and_invalid_values(self):
        self.assertEqual(retry_after_seconds("75"),75)
        self.assertIsNone(retry_after_seconds("invalid"))
        self.assertEqual(retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT"),0)


if __name__ == '__main__': unittest.main()
