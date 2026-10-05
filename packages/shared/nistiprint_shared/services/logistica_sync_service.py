"""Agenda por conta e reconciliacao de envios ativos pela pipeline de ingest."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from celery import shared_task
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.logistica_manutencao_service import normalize_schedule, retry_at, rpc_data
from nistiprint_shared.services.platform_drivers import mercadolivre as driver

logger = logging.getLogger(__name__)


def _integration(integration_id):
    from nistiprint_shared.services.credential_resolver_service import credential_resolver_service
    rows = supabase_db.table('installed_integrations').select('*').eq('id', integration_id).execute().data or []
    if not rows or rows[0].get('module_id') != 'mercadolivre' or rows[0].get('is_active') is False:
        raise ValueError('Conta Mercado Livre nao encontrada')
    return credential_resolver_service.hydrate_integration(rows[0])


def _call(integration, method, *args):
    result = method(integration, *args)
    if result.get('status_code') == 401:
        from nistiprint_shared.services.installed_integration_service import installed_integration_service
        installed_integration_service.renew_integration_token(str(integration['id']), execution_mode='logistica_401')
        integration.update(_integration(integration['id']))
        result = method(integration, *args)
    return result


def sincronizar_agendas(integration_id=None):
    query = supabase_db.table('regras_logisticas_integracao').select('marketplace_integration_id,logistic_type') \
        .eq('ativo', True).eq('fonte_agenda', 'MARKETPLACE')
    if integration_id is not None:
        query = query.eq('marketplace_integration_id', integration_id)
    groups = {}
    for row in query.execute().data or []:
        groups.setdefault(row['marketplace_integration_id'], set()).add(row['logistic_type'])
    report = {'atualizadas': 0, 'erros': 0, 'ignoradas': 0}
    for iid, types in groups.items():
        # Lease atomica no banco, tambem usada pelo botao manual.
        if not rpc_data('logistica_reservar_agenda', {'p_integration_id': iid}):
            report['ignoradas'] += len(types)
            continue
        user = {}
        try:
            integration = _integration(iid)
            user = _call(integration, driver.get_shipping_user)
            if user.get('error'):
                if user.get('status_code') == 429:
                    supabase_db.table('logistica_sync_cursores').update({'proxima_tentativa_em': retry_at(user)}).eq('nome', f'agenda:{iid}').execute()
                raise ValueError(user['error'])
            if 'warehouse_management' in (user.get('tags') or []):
                raise ValueError('Conta com multiplas origens: mantenha a agenda manual')
            seller_id = user.get('id')
            for kind in sorted(types):
                old = supabase_db.table('logistica_agendas').select('*').eq('integration_id', iid).eq('logistic_type', kind).execute().data or []
                now = datetime.now(timezone.utc)
                if old and old[0].get('proxima_tentativa_em') and datetime.fromisoformat(old[0]['proxima_tentativa_em'].replace('Z', '+00:00')) > now:
                    report['ignoradas'] += 1
                    continue
                result = _call(integration, driver.get_shipping_schedule, str(seller_id), kind)
                row = {'integration_id': iid, 'logistic_type': kind, 'tentativa_em': now.isoformat()}
                try:
                    if result.get('error'):
                        raise ValueError(result['error'])
                    row.update(agenda=normalize_schedule(result), consultada_em=now.isoformat(), erro=None, proxima_tentativa_em=None)
                    report['atualizadas'] += 1
                except ValueError as exc:
                    row.update(erro=str(exc), proxima_tentativa_em=retry_at(result, now))
                    report['erros'] += 1
                # Campos agenda/consultada_em sao omitidos em falha, preservando o ultimo sucesso.
                supabase_db.table('logistica_agendas').upsert(row, on_conflict='integration_id,logistic_type').execute()
                if result.get('status_code') == 429:
                    supabase_db.table('logistica_sync_cursores').update({'proxima_tentativa_em': retry_at(result)}).eq('nome', f'agenda:{iid}').execute()
                    break
            rpc_data('logistica_atualizar_dependentes', {'p_integration_id': iid})
        except Exception as exc:
            logger.exception('Falha na agenda da integracao %s', iid)
            for kind in types:
                supabase_db.table('logistica_agendas').upsert({'integration_id': iid, 'logistic_type': kind,
                    'tentativa_em': datetime.now(timezone.utc).isoformat(), 'erro': str(exc),
                    'proxima_tentativa_em': retry_at(user)}, on_conflict='integration_id,logistic_type').execute()
            report['erros'] += len(types)
        finally:
            supabase_db.table('logistica_sync_cursores').update({'bloqueado_ate': None}).eq('nome', f'agenda:{iid}').execute()
    return report


@shared_task(name='nistiprint_shared.services.logistica_sync_service.sincronizar_agendas', soft_time_limit=240, time_limit=270)
def sincronizar_agendas_task(integration_id=None):
    return sincronizar_agendas(integration_id)


def reconciliar_envios():
    from nistiprint_shared.services.marketplace_webhook_ingest_service import marketplace_webhook_ingest_service
    ids = rpc_data('logistica_reservar_sync', {'p_nome': 'envios-ativos', 'p_limite': 40})
    if ids is None:
        return {'status': 'ignorado'}
    report = {'pedidos': 0, 'envios': 0, 'erros': 0}
    last = min(ids)-1 if ids else 0
    seen = set()
    try:
        if not ids:
            return report
        rows = supabase_db.table('pedidos').select('id,marketplace_integration_id,marketplace_order_id') \
            .in_('id', ids).order('id').execute().data or []
        for row in rows:
            user = {}
            try:
                iid = row.get('marketplace_integration_id')
                mirror = supabase_db.table('pedidos_mercadolivre').select('shipment_id').eq('marketplace_integration_id', iid) \
                    .eq('codigo_pedido', row['marketplace_order_id']).execute().data or []
                sid = (mirror or [{}])[0].get('shipment_id')
                key = (iid, str(sid or row['marketplace_order_id']))
                if key in seen:
                    last = row['id']
                    continue
                seen.add(key)
                integration = _integration(iid)
                config = integration.get('config') or {}
                seller = (config.get('account_identifiers') or {}).get('primary') or config.get('user_id') or config.get('seller_id')
                if not seller:
                    user = _call(integration, driver.get_shipping_user)
                    seller = user.get('id')
                topic = 'shipments' if sid else 'orders_v2'
                result = (user if user.get('error') else marketplace_webhook_ingest_service.process('mercadolivre', {
                    'topic': topic, 'resource': f'/shipments/{sid}' if sid else f"/orders/{row['marketplace_order_id']}",
                    'user_id': seller, 'sent': datetime.now(timezone.utc).isoformat(),
                })) or {}
                if result.get('retry_after') or result.get('status_code') == 429 or result.get('error_type') == 'provider_rate_limited':
                    supabase_db.table('logistica_sync_cursores').update({'proxima_tentativa_em': retry_at(result)}) \
                        .eq('nome', 'envios-ativos').execute()
                    break
                if result.get('error') or result.get('status') not in ('success', 'skipped'):
                    report['erros'] += 1
                else:
                    report['envios'] += 1
                    updated_ids = list(set((result.get('pedido_ids') or []) + [row['id']]))
                    report['pedidos'] += len(updated_ids)
                    supabase_db.table('pedidos').update({'logistica_consultada_em': datetime.now(timezone.utc).isoformat()}) \
                        .in_('id', updated_ids).execute()
                last = row['id']
            except Exception:
                report['erros'] += 1
                last = row['id']
                logger.exception('Falha ao reconciliar pedido %s', row['id'])
        for iid in {r['marketplace_integration_id'] for r in rows if r.get('marketplace_integration_id')}:
            rpc_data('logistica_atualizar_dependentes', {'p_integration_id': iid})
    finally:
        supabase_db.table('logistica_sync_cursores').update({'ultimo_id': last, 'bloqueado_ate': None}) \
            .eq('nome', 'envios-ativos').execute()
    return report


@shared_task(name='nistiprint_shared.services.logistica_sync_service.reconciliar_envios', soft_time_limit=780, time_limit=840)
def reconciliar_envios_task():
    return reconciliar_envios()
