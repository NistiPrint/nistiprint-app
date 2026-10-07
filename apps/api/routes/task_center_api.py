"""Admin task center: bounded execution history and best-effort health signals."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, request
from routes.auth import admin_required
from nistiprint_shared.database.supabase_db_service import supabase_db

task_center_bp = Blueprint("task_center", __name__)
_SECRET_VALUE = re.compile(r"(?i)(access_token|refresh_token|client_secret|api[_-]?key|authorization)(\s*[\"'=:\s]+)([^,\s\"'&}]+)")


def _now():
    return datetime.now(timezone.utc)


def _json(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return {}
    return {}


def _sanitize(value):
    if isinstance(value, dict):
        return {key: ("[redigido]" if re.search(r"token|secret|password|api.?key|authorization|credential", str(key), re.I)
                       else _sanitize(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUE.sub(r"\1\2[redigido]", value)[:5000]
    return value


def _task_rows(hours: int, limit: int = 500):
    since = (_now() - timedelta(hours=hours)).isoformat()
    return (supabase_db.table("task_execution_logs").select("*")
            .gte("created_at", since).order("created_at", desc=True)
            .limit(limit).execute().data or [])


def _task_counts(hours: int) -> dict:
    since = (_now() - timedelta(hours=hours)).isoformat()
    counts = {}
    for status in ("PENDING", "PROCESSING", "COMPLETED", "FAILED", "CANCELLED"):
        result = (supabase_db.table("task_execution_logs").select("id", count="exact", head=True)
                  .gte("created_at", since).eq("status", status).execute())
        counts[status] = int(getattr(result, "count", 0) or 0)
    return counts


def _queue_signals():
    try:
        from nistiprint_shared.services.redis_queue_tasks import get_queue_stats
        legacy = get_queue_stats()
        webhook = {"status": "available", "queues": legacy}
    except Exception as exc:
        webhook = {"status": "unavailable", "reason": str(exc)[:300], "queues": {}}

    try:
        from nistiprint_shared.services.reliable_ingest_queue import queue_lengths
        reliable = {"status": "available", "queues": queue_lengths()}
    except Exception as exc:
        reliable = {"status": "unavailable", "reason": str(exc)[:300], "queues": {}}

    try:
        import redis
        client = redis.Redis.from_url(os.getenv("CELERY_BROKER_URL", "redis://redis-celery:6379/0"), socket_connect_timeout=1, socket_timeout=1)
        accounts = (supabase_db.table("mercadolivre_personalization_config")
                    .select("marketplace_integration_id").execute().data or [])
        queues = {}
        for row in accounts:
            integration_id = int(row["marketplace_integration_id"])
            key = f"meli_personalization_{integration_id}"
            queues[str(integration_id)] = {"queue": key, "ready": int(client.llen(key))}
        celery = {"status": "available", "queues": queues}
    except Exception as exc:
        celery = {"status": "unavailable", "reason": str(exc)[:300], "queues": {}}
    return {"webhooks": webhook, "reliable_ingest": reliable, "celery": celery}


def _process_signals():
    processes = []
    try:
        import redis
        client = redis.Redis.from_url(os.getenv("CELERY_BROKER_URL", "redis://redis-celery:6379/0"),
                                      decode_responses=True, socket_connect_timeout=1, socket_timeout=1)
        for role in ("router", "orders", "chat", "chatsync", "retry", "lease", "spool", "archive"):
            key = f"np/ingest/heartbeat/{role}"
            legacy_key = f"np:ingest:heartbeat:{role}"
            stamp = client.get(legacy_key) or client.get(key)
            processes.append({"name": f"ingest:{role}", "status": "normal" if stamp else "unavailable",
                              "last_heartbeat": stamp, "source": legacy_key})
        accounts = (supabase_db.table("installed_integrations").select("id,module_id,instance_name")
                    .eq("module_id", "mercadolivre").eq("is_active", True).execute().data or [])
        for account in accounts:
            integration_id = int(account["id"])
            running_rows = (supabase_db.table("task_execution_logs").select("id,started_at,task_name")
                            .eq("marketplace_integration_id", integration_id).eq("status", "PROCESSING")
                            .limit(50).execute().data or [])
            active_ages = []
            for task in running_rows:
                try:
                    start = datetime.fromisoformat(str(task.get("started_at")).replace("Z", "+00:00"))
                    if start.tzinfo is None:
                        start = start.replace(tzinfo=timezone.utc)
                    active_ages.append(max(0, int((_now() - start).total_seconds())))
                except (TypeError, ValueError):
                    pass
            for role in ("messages", "worker", "beat"):
                key = f"np:ml-personalization:heartbeat:{integration_id}:{role}"
                stamp = client.get(key)
                progress = client.get(f"np:ml-personalization:progress:{integration_id}:{role}")
                stale_task = role == "worker" and any(age > 900 for age in active_ages)
                processes.append({"name": f"Mercado Livre · {account.get('instance_name') or integration_id} · {role}",
                                  "integration_id": integration_id,
                                  "status": "unavailable" if not stamp else "attention" if stale_task else "normal",
                                  "last_heartbeat": stamp, "last_progress": progress,
                                  "active_tasks": len(running_rows) if role == "worker" else 0,
                                  "stale_tasks": sum(age > 900 for age in active_ages) if role == "worker" else 0})
    except Exception as exc:
        return {"status": "unavailable", "reason": str(exc)[:300], "items": []}
    return {"status": "available", "measured_at": _now().isoformat(), "items": processes}


@task_center_bp.get("/api/v2/admin/task-center/overview")
@admin_required
def overview():
    try:
        hours = max(1, min(168, request.args.get("hours", 24, type=int)))
        rows = _task_rows(hours)
        status_counts = _task_counts(hours)
        queues = _queue_signals()
        processes = _process_signals()
        meli = []
        health_status = "available"
        try:
            from nistiprint_shared.services.mercadolivre_personalization_service import (
                available_integrations, account_health, list_pending_conversations, list_unmatched_notifications,
            )
            for account in available_integrations():
                integration_id = account["integration_id"]
                pending = list_pending_conversations(integration_id, limit=100)
                unmatched = list_unmatched_notifications(integration_id, limit=100)
                meli.append({"integration_id": account["integration_id"], "name": account["name"],
                             "schedule_enabled": account.get("schedule_enabled", True),
                             "schedule_hour": account.get("schedule_hour", 9),
                             "schedule_minute": account.get("schedule_minute", 0),
                             "health": account_health(integration_id),
                             "pending_conversations": [{"pack_id": row.get("pack_id"),
                                 "pending_order_ids": row.get("pending_order_ids") or [],
                                 "message_count": len(row.get("messages") or []),
                                 "last_message_at": row.get("last_message_at")}
                                 for row in pending],
                             "unmatched_notifications": [{"provider_message_id": row.get("provider_message_id"),
                                 "account_user_id": row.get("account_user_id"),
                                 "application_id": row.get("application_id"),
                                 "actions": row.get("actions") or [], "status": row.get("status"),
                                 "last_error": row.get("last_error"), "created_at": row.get("created_at")}
                                 for row in unmatched]})
        except Exception as exc:
            health_status = "unavailable"
            meli_error = str(exc)[:300]
        return {"success": True, "data": {
            "hours": hours, "measured_at": _now().isoformat(), "task_stats": status_counts,
            "task_sample_size": len(rows), "queues": queues, "processes": processes,
            "mercadolivre": meli,
            "mercadolivre_status": health_status,
            "mercadolivre_error": locals().get("meli_error"),
            "recent_failures": [_sanitize(row) for row in rows if row.get("status") == "FAILED"][:20],
            "overdue": [row for row in rows if row.get("status") in {"PENDING", "PROCESSING"}][:50],
        }}
    except Exception as exc:
        return {"success": False, "error": "Não foi possível consultar a saúde do sistema.", "detail": str(exc)[:300]}, 503


@task_center_bp.get("/api/v2/admin/task-center/executions")
@admin_required
def executions():
    try:
        hours = max(1, min(168, request.args.get("hours", 24, type=int)))
        limit = max(1, min(200, request.args.get("limit", 50, type=int)))
        offset = max(0, request.args.get("offset", 0, type=int))
        query = supabase_db.table("task_execution_logs").select("*", count="exact")
        query = query.gte("created_at", (_now() - timedelta(hours=hours)).isoformat())
        for param, column in (("status", "status"), ("task_type", "task_type"), ("integration_id", "marketplace_integration_id")):
            value = request.args.get(param)
            if value:
                query = query.eq(column, int(value) if column == "marketplace_integration_id" else value)
        if request.args.get("task_name"):
            query = query.ilike("task_name", f"%{request.args['task_name'][:100]}%")
        if request.args.get("origin"):
            query = query.eq("execution_origin", request.args["origin"][:40])
        if request.args.get("order_id"):
            order_id = request.args["order_id"][:100]
            query = query.eq("metadata->>entity_id", order_id)
        if request.args.get("batch_id"):
            query = query.eq("metadata->>batch_id", request.args["batch_id"][:100])
        result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
        return {"success": True, "data": _sanitize(result.data or []), "count": getattr(result, "count", None),
                "limit": limit, "offset": offset, "hours": hours}
    except Exception as exc:
        return {"success": False, "error": "Não foi possível consultar as execuções.", "detail": str(exc)[:300]}, 503


@task_center_bp.get("/api/v2/admin/task-center/executions/<task_log_id>")
@admin_required
def execution_detail(task_log_id):
    try:
        rows = (supabase_db.table("task_execution_logs").select("*")
                .eq("id", task_log_id).limit(1).execute().data or [])
        if not rows:
            return {"success": False, "error": "Execução não encontrada."}, 404
        return {"success": True, "data": _sanitize(rows[0])}
    except Exception as exc:
        return {"success": False, "error": "Não foi possível consultar a execução.", "detail": str(exc)[:300]}, 503


@task_center_bp.get("/api/v2/admin/task-center/queues")
@admin_required
def queues():
    return {"success": True, "data": _queue_signals(), "measured_at": _now().isoformat()}


@task_center_bp.get("/api/v2/admin/task-center/processes")
@admin_required
def processes():
    data = _process_signals()
    return ({"success": True, "data": data} if data.get("status") == "available"
            else ({"success": False, "data": data}, 503))


@task_center_bp.get("/api/v2/admin/task-center/schedules")
@admin_required
def schedules():
    from nistiprint_shared.services.app_config_service import app_config_service
    data = app_config_service.get_config("celery_task_schedules") or {}
    tasks = data.get("task_schedules", {}) if isinstance(data, dict) else {}
    celery_revision = data.get("revision") if isinstance(data, dict) else None
    applied_revision = None
    try:
        import redis
        client = redis.Redis.from_url(os.getenv("CELERY_BROKER_URL", "redis://redis-celery:6379/0"),
                                      decode_responses=True, socket_connect_timeout=1, socket_timeout=1)
        applied_revision = client.get("np:taskcenter:celery_schedules_revision")
    except Exception:
        pass
    restart_required = bool(celery_revision and applied_revision and str(applied_revision) != str(celery_revision))
    restart_state = "pending" if restart_required else "applied" if celery_revision and applied_revision else "unknown"
    enriched = {}
    for name, config in tasks.items():
        task_name = config.get("task_name", name)
        try:
            latest = (supabase_db.table("task_execution_logs").select("id,status,started_at,finished_at,duration_ms")
                      .eq("task_name", task_name).order("created_at", desc=True).limit(1).execute().data or [])
            successful = (supabase_db.table("task_execution_logs").select("id,status,finished_at")
                          .eq("task_name", task_name).eq("status", "COMPLETED")
                          .order("created_at", desc=True).limit(1).execute().data or [])
        except Exception:
            latest, successful = [], []
        enriched[name] = {**config, "last_execution": latest[0] if latest else None,
                          "last_success": successful[0] if successful else None,
                          "restart_state": restart_state}
    try:
        from nistiprint_shared.services.mercadolivre_personalization_service import available_integrations
        meli = [{"task_name": f"mercadolivre.personalization.process_due.{row['integration_id']}",
                 "marketplace": "mercadolivre", "integration_id": row["integration_id"], "name": row["name"],
                 "enabled": row.get("schedule_enabled", True), "hour": row.get("schedule_hour", 9),
                 "minute": row.get("schedule_minute", 0), "timezone": "America/Sao_Paulo",
                 "last_scheduled_run_date": row.get("last_scheduled_run_date"),
                 "last_execution": None, "last_success": None}
                for row in available_integrations()]
        for item in meli:
            task_name = item["task_name"]
            item["last_execution"] = (supabase_db.table("task_execution_logs")
                .select("id,status,started_at,finished_at,duration_ms")
                .eq("task_name", task_name).order("created_at", desc=True).limit(1).execute().data or [None])[0]
            item["last_success"] = (supabase_db.table("task_execution_logs")
                .select("id,status,finished_at")
                .eq("task_name", task_name).eq("status", "COMPLETED")
                .order("created_at", desc=True).limit(1).execute().data or [None])[0]
        local_now = _now().astimezone(ZoneInfo("America/Sao_Paulo"))
        for item in meli:
            if not item["enabled"]:
                item["next_run_at"] = None
                continue
            next_run = local_now.replace(hour=int(item["hour"]), minute=int(item["minute"]), second=0, microsecond=0)
            if next_run <= local_now or item.get("last_scheduled_run_date") == local_now.date().isoformat():
                next_run = next_run + timedelta(days=1)
            item["next_run_at"] = next_run.isoformat()
    except Exception:
        meli = []
    return {"success": True, "data": {"celery": enriched, "mercadolivre": meli,
            "celery_revision": celery_revision, "applied_revision": applied_revision,
            "restart_required": restart_required, "restart_state": restart_state}}


@task_center_bp.put("/api/v2/admin/task-center/schedules/mercadolivre/<int:integration_id>")
@admin_required
def update_mercadolivre_schedule(integration_id):
    try:
        body = request.get_json(silent=True) or {}
        if not isinstance(body.get("enabled"), bool):
            return {"success": False, "error": "enabled precisa ser booleano"}, 400
        from nistiprint_shared.services.mercadolivre_personalization_service import update_settings
        values = {"schedule_enabled": body["enabled"]}
        for key, low, high in (("hour", 0, 23), ("minute", 0, 59)):
            if key in body:
                try:
                    value = int(body[key])
                except (TypeError, ValueError):
                    return {"success": False, "error": f"{key} inválido"}, 400
                if not low <= value <= high:
                    return {"success": False, "error": f"{key} fora do intervalo permitido"}, 400
                values["schedule_hour" if key == "hour" else "schedule_minute"] = value
        result = update_settings(integration_id, values)
        return {"success": True, "data": {"integration_id": integration_id,
                "enabled": result.get("schedule_enabled", body["enabled"]),
                "hour": result.get("schedule_hour", 9), "minute": result.get("schedule_minute", 0)}}
    except (ValueError, LookupError) as exc:
        return {"success": False, "error": str(exc)}, 400
    except Exception as exc:
        return {"success": False, "error": "Não foi possível atualizar a tarefa Mercado Livre.", "detail": str(exc)[:300]}, 500
