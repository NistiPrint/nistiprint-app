"""Bounded Mercado Livre first passes and durable, deferred retries."""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone

import httpx

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.ai.base import AIProviderError
from nistiprint_shared.services.ai.gemini_provider import GeminiProvider
from nistiprint_shared.services.ai.openrouter_provider import OpenRouterProvider

logger = logging.getLogger(__name__)


def _row(data):
    return (data[0] if data else None) if isinstance(data, list) else data


def _rpc(name, params):
    return supabase_db.rpc(name, params).execute().data


class SavedResultError(RuntimeError):
    """The model already succeeded; retry only the supplied persistence payload."""
    def __init__(self, error, payload):
        super().__init__(f"Falha ao gravar a resposta da IA: {error}")
        self.payload = payload
        self.retryable = True
        self.retry_after = getattr(error, "retry_after", None)


class BatchClients:
    """One provider instance per thread/account/model, closed with the batch run."""
    def __init__(self, integration_id, settings):
        self.settings = dict(settings)
        self.keys = {
            name: (os.getenv(f"MERCADOLIVRE_PERSONALIZACAO_{name.upper()}_API_KEY_{integration_id}")
                   or os.getenv(f"MERCADOLIVRE_PERSONALIZACAO_{name.upper()}_API_KEY"))
            for name in ("gemini", "openrouter")
        }
        self.local = threading.local()
        self.registry = []
        self.lock = threading.Lock()

    @property
    def has_fallback(self):
        fallback = self.settings.get("fallback_provider")
        return bool(fallback and self.keys.get(fallback))

    def selection(self, phase):
        name = self.settings.get("provider") or "gemini"
        model = self.settings.get("model_name")
        if phase == "RETRY" and self.has_fallback:
            name = self.settings["fallback_provider"]
            model = "gemini-2.5-flash" if name == "gemini" else "openrouter/auto"
        return name, model

    def complete(self, phase, prompt, payload, schema):
        name, model = self.selection(phase)
        if name not in self.keys or not self.keys[name]:
            raise AIProviderError(f"Credencial de IA Mercado Livre ausente para {name}.", retryable=False)
        cache = getattr(self.local, "providers", None)
        if cache is None:
            self.local.providers = cache = {}
        timeout = max(1, min(600, int(self.settings.get("timeout_seconds") or 60)))
        key = (name, model, timeout)
        if key not in cache:
            cache[key] = (GeminiProvider(model=model, api_key=self.keys[name], timeout=timeout,
                                         retry_attempts=1) if name == "gemini" else
                          OpenRouterProvider(model=model, api_key=self.keys[name], timeout=timeout))
            with self.lock:
                self.registry.append(cache[key])
        return cache[key].complete(prompt, payload, response_schema=schema)

    def close(self):
        for provider in self.registry:
            try:
                provider.close()
            except Exception:
                logger.exception("Could not close Mercado Livre AI provider")


def persist_pack_result(batch_id, pack_id, token, payload, metrics, *, checkpoint=True):
    try:
        if checkpoint:
            _rpc("ml_ai_checkpoint_result", {
                "p_batch_id": batch_id, "p_pack_id": pack_id, "p_token": token,
                "p_payload": payload, "p_metrics": metrics,
            })
        saved = _row(_rpc("ml_ai_persist_result", {
            "p_batch_id": batch_id, "p_pack_id": pack_id, "p_token": token,
            "p_metrics": metrics,
        }))
        if (not isinstance(saved, dict) or saved.get("saved") != len(payload["p_records"])
                or saved.get("status") != payload["p_status"]):
            raise RuntimeError("Banco não confirmou o resultado completo da IA")
    except Exception as exc:
        raise SavedResultError(exc, payload) from exc
    return {"status": payload["p_status"].lower(), "pack_id": str(pack_id),
            "personalizations": len(payload["p_records"]), "ledger_completed": True}


def retry_eligible(error, clients):
    if isinstance(error, SavedResultError):
        return True
    if isinstance(error, AIProviderError):
        return error.retryable or clients.has_fallback
    return bool(getattr(error, "retryable", False) or
                isinstance(error, (httpx.HTTPError, ConnectionError, TimeoutError)))


def _run_item(service, batch, item, clients):
    batch_id, token, pack_id = str(batch["id"]), str(batch["run_token"]), str(item["pack_id"])
    claimed = _row(_rpc("ml_ai_claim_item", {
        "p_batch_id": batch_id, "p_pack_id": pack_id, "p_token": token,
    }))
    if not claimed:
        return {"status": "ignored"}
    started = time.monotonic()
    metrics = {**(claimed.get("metrics") or {})}
    if not claimed.get("persistence_payload"):
        metrics["provider"] = clients.selection(batch["phase"])[0]
    context = {"clients": clients, "phase": batch["phase"], "metrics": metrics,
               "attempt": claimed.get("attempts", 0),
               "prepared_payload": claimed.get("persistence_payload"), "started": started}
    try:
        result = service.process_pack(
            batch["marketplace_integration_id"], pack_id, batch_id=batch_id,
            force=bool(batch.get("force")), settings=clients.settings, run_token=token,
            execution_context=context,
        )
        if result.get("ledger_completed"):
            return result
        status, error, next_at, payload, kind = "COMPLETED", None, None, None, None
    except Exception as exc:
        metrics["duration_ms"] = int((time.monotonic() - started) * 1000)
        error = str(exc)[:1000]
        payload = exc.payload if isinstance(exc, SavedResultError) else None
        kind = "PERSISTENCE" if payload is not None else "MODEL"
        may_retry = ((payload is not None and max(1, claimed.get("persistence_attempts", 0)) < 2)
                     or (batch["phase"] == "FIRST_PASS" and claimed.get("attempts", 0) < 2
                         and retry_eligible(exc, clients)))
        status = "RETRY_PENDING" if may_retry else "FAILED"
        delay = getattr(exc, "retry_after", None)
        next_at = datetime.fromtimestamp(time.time() + max(0, float(delay if delay is not None else 30)),
                                        timezone.utc).isoformat() if may_retry else None
    metrics["duration_ms"] = int((time.monotonic() - started) * 1000)
    accepted = _rpc("ml_ai_finish_item", {
        "p_batch_id": batch_id, "p_pack_id": pack_id, "p_token": token,
        "p_status": status, "p_error": error, "p_next_at": next_at,
        "p_metrics": metrics, "p_payload": payload, "p_retry_kind": kind,
    })
    return {"status": status.lower() if accepted else "ignored", "pack_id": pack_id}


def process_batch(service, integration_id, batch_id):
    service._integration(integration_id)
    existing = _row(supabase_db.table("mercadolivre_personalization_batches").select("*")
                    .eq("id", str(batch_id)).eq("marketplace_integration_id", int(integration_id))
                    .limit(1).execute().data)
    if not existing:
        raise LookupError("Lote não encontrado nesta conta")
    if existing["status"] == "COMPLETED" or (existing["status"] == "FAILED" and existing.get("phase") == "DONE"):
        return {"status": "completed", "processed": existing.get("processed", 0)}
    batch = _row(_rpc("ml_ai_claim_batch", {
        "p_integration_id": int(integration_id), "p_batch_id": str(batch_id),
        "p_token": str(uuid.uuid4()),
    }))
    if not batch:
        return {"status": "running" if existing["status"] == "RUNNING" else "waiting_for_account_slot",
                "next_attempt_at": existing.get("available_at"), "processed": existing.get("processed", 0)}
    _publish(service, batch)
    stop = threading.Event()
    heartbeat = threading.Thread(target=service._renew_batch_lease,
        args=(integration_id, str(batch_id), str(batch["run_token"]), stop), daemon=True,
        name=f"ml-ai-lease-{integration_id}")
    heartbeat.start()
    clients = None
    try:
        clients = BatchClients(integration_id, service._settings(integration_id))
        status = "PENDING" if batch["phase"] == "FIRST_PASS" else "RETRY_PENDING"
        items = (supabase_db.table("mercadolivre_personalization_batch_items").select("*")
                 .eq("batch_id", str(batch_id)).eq("status", status).eq("phase", batch["phase"])
                 .lte("next_attempt_at", service._now()).order("pack_id").execute().data or [])
        last_publication = time.monotonic()
        last_counts = None

        def publish_progress():
            nonlocal last_publication, last_counts
            if time.monotonic() - last_publication < 1:
                return
            last_publication = time.monotonic()
            try:
                current = _row(supabase_db.table("mercadolivre_personalization_batches")
                               .select("*").eq("id", str(batch_id)).limit(1).execute().data)
                if current:
                    counts = tuple(current.get(key) for key in
                                   ("processed", "success_count", "failed_count", "retry_pending_count",
                                    "running_count", "retry_processed"))
                    if counts != last_counts:
                        _publish(service, current)
                        last_counts = counts
            except Exception:
                logger.exception("Could not read Mercado Livre progress snapshot")

        for item, _result, failure in service._iter_pack_results(
            integration_id, str(batch_id), items, bool(batch.get("force")), clients.settings,
            str(batch["run_token"]), process_fn=lambda item: _run_item(service, batch, item, clients),
            progress_fn=publish_progress,
        ):
            if failure:
                logger.error("Could not commit pack outcome batch=%s pack=%s: %s", batch_id, item["pack_id"], failure)
            publish_progress()
        released = _row(_rpc("ml_ai_release_batch", {
            "p_batch_id": str(batch_id), "p_token": str(batch["run_token"]),
        }))
        if not released:
            return {"status": "lease_lost"}
        _publish(service, released)
        return {"status": "completed" if released["status"] == "COMPLETED" else "waiting_retry",
                "next_attempt_at": released.get("available_at"), "processed": released["processed"],
                "success": released["success_count"], "failed": released["failed_count"]}
    finally:
        stop.set()
        heartbeat.join(timeout=1)
        if clients:
            clients.close()


def _publish(service, batch):
    try:
        service._sync_batch_operation(batch)
    except Exception:
        logger.exception("Could not publish Mercado Livre batch progress")
