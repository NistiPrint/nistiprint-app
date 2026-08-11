"""
Importação de pedidos 'Em Andamento' via API Bling.
Fluxo: lista pedidos -> processa via pipeline única (bling_order_processing).

DEPRECATED: As funções _sync_bling_order_phase1 e _enrich_from_marketplace
foram substituídas pelo pipeline unificado em bling_order_processing_service.

NOTA sobre o fluxo: este módulo enfileirava em `bling:webhooks:pendentes`, fila
consumida por `redis_queue_tasks.consumir_fila_bling`. Essa task foi aposentada
— `celery_config` a filtra explicitamente do beat como obsoleta — quando o
ingest migrou para as filas `np:ingest:*` do `reliable_ingest_worker`. O
enfileiramento continuava "funcionando" no sentido de não levantar erro, e por
isso a importação parecia bem-sucedida enquanto nada era processado.

A correção não foi apontar para a fila nova. O envelope do ingest é deduplicado
por `provider_event_id`, que para o Bling é o id do pedido: reimportar o mesmo
pedido seria descartado como duplicata, que é exatamente o oposto do que uma
reimportação quer. Como o pedido completo já foi buscado aqui, chama-se
`process_webhook` direto — a mesma função que o worker de ingest chama.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from nistiprint_shared.services.bling_client_resolver_service import bling_client_resolver_service
from nistiprint_shared.services.integracao_canal_service import integracao_canal_service

logger = logging.getLogger(__name__)


def _iso_date(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def _enrich_from_marketplace(full_order: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    DEPRECATED: O enriquecimento agora é feito automaticamente dentro do
    process_webhook em bling_order_processing_service. Esta função retorna
    apenas um stub para compatibilidade.
    """
    logger.debug("_enrich_from_marketplace é deprecated - enriquecimento no pipeline unificado")
    return {"enriched": False, "platform": None, "error": None, "deprecated": True}


def _processar_pedido_bling(full_order: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Processa o pedido pela pipeline unificada de webhook do Bling.

    Args:
        full_order: Dados completos do pedido no Bling
        cfg: Configuração do vínculo com bling_integration_id

    Returns:
        Resultado do processamento
    """
    from nistiprint_shared.services.bling_order_processing_service import process_webhook

    bling_id = full_order.get("id")
    order_sn = full_order.get("numeroLoja")
    bling_company_id = cfg.get("bling_company_id")
    bling_integration_id = cfg.get("bling_integration_id")

    logger.info(
        "Processando pedido Bling %s (numeroLoja=%s)",
        bling_id,
        order_sn or "N/A"
    )

    try:
        # O pedido completo ja veio da API; o payload nao e reduzido em nenhum
        # ponto porque `loja.id` identifica a origem/marketplace.
        resultado = process_webhook(
            full_order,
            bling_integration_hint=bling_integration_id,
            company_id=bling_company_id,
        )
        status = (resultado or {}).get("status")

        if status in ("success", "skipped"):
            logger.info("✓ Pedido %s processado (%s)", bling_id, status)
            return {"success": True, "bling_id": bling_id, "resultado": resultado}

        erro = (resultado or {}).get("message") or (resultado or {}).get("reason") or status
        logger.warning("✗ Pedido %s nao processado: %s", bling_id, erro)
        return {"success": False, "error": str(erro), "bling_id": bling_id}

    except Exception as e:
        logger.error("✗ Falha ao processar pedido %s: %s", bling_id, e)
        return {"success": False, "error": str(e), "bling_id": bling_id}


def _bling_client_for_config(cfg: Dict[str, Any]):
    """
    Cria cliente Bling para uma configuracao especifica.
    Prioriza bling_integration_id e usa o mesmo resolver compartilhado da consolidacao.
    """
    return bling_client_resolver_service.resolve_client(
        bling_integration_id=cfg.get('bling_integration_id'),
        platform_name=(cfg.get('plataforma_nome') or '').lower() or None,
        channel_id=cfg.get('canal_venda_id'),
        function_name='ORDER_IMPORT',
    )[0]


def run_fetch_pedidos_em_andamento(
    dias: Optional[int] = None,
    situacao_id: int = 15,
    config_id: Optional[str] = None,
    config_ids: Optional[List[str]] = None,
    only_plataformas: Optional[List[str]] = None,
    limit_pedidos: Optional[int] = None,
    data_inicial: Optional[str] = None,
    data_final: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Busca pedidos no Bling por loja configurada e sincroniza no core.

    - Se config_id ou config_ids forem informados, processa apenas esses vínculos.
    - Caso contrário, processa todos os vínculos ativos (uso avançado).
    """
    if not data_inicial or not data_final:
        try:
            dias_val = int(dias or 7)
            if dias_val < 1:
                dias_val = 1
        except Exception:
            dias_val = 7

        start = datetime.utcnow() - timedelta(days=dias_val)
        end = datetime.utcnow()
        data_inicial = _iso_date(start)
        data_final = _iso_date(end)
    else:
        # Se datas foram fornecidas, ignorar 'dias'
        pass

    plataformas_filter = None
    if only_plataformas:
        plataformas_filter = {str(p).lower() for p in only_plataformas if p}

    if config_id:
        row = integracao_canal_service.get_config_by_id(config_id)
        if not row or not row.get("is_active", True):
            return {"status": "SKIPPED", "reason": "Configuração não encontrada ou inativa."}
        configs = [row]
    elif config_ids:
        configs = []
        for cid in config_ids:
            row = integracao_canal_service.get_config_by_id(cid)
            if row and row.get("is_active", True):
                configs.append(row)
    else:
        configs = integracao_canal_service.listar_configuracoes(include_inactive=False)

    if not configs:
        return {"status": "SKIPPED", "reason": "Nenhuma configuração de vínculo ativa para processar."}

    stats: Dict[str, Any] = {
        "status": "SUCCESS",
        "dias": dias,
        "situacao_id": situacao_id,
        "data_inicial": data_inicial,
        "data_final": data_final,
        "lojas": [],
        "totals": {"orders_listed": 0, "orders_fetched": 0, "orders_synced": 0, "errors": 0},
    }

    hard_limit = int(os.environ.get("FETCH_PEDIDOS_EM_ANDAMENTO_LIMIT", "0") or 0)
    if limit_pedidos is None and hard_limit > 0:
        limit_pedidos = hard_limit

    for cfg in configs:
        plataforma_nome = (cfg.get("plataforma_nome") or "").lower()
        if plataformas_filter and plataforma_nome and plataforma_nome not in plataformas_filter:
            continue

        bling_loja_id = cfg.get("bling_loja_id")
        canal_venda_id = cfg.get("canal_venda_id")

        if not bling_loja_id:
            logger.warning("Configuração %s sem bling_loja_id - pulando", cfg.get("id"))
            continue

        logger.info(
            "Processando pedidos da plataforma %s (bling_loja_id=%s, canal_venda_id=%s)",
            plataforma_nome or "N/A",
            bling_loja_id,
            canal_venda_id
        )

        loja_stat = {
            "config_id": cfg.get("id"),
            "plataforma_nome": plataforma_nome,
            "bling_loja_id": bling_loja_id,
            "canal_venda_id": canal_venda_id,
            "listed": 0,
            "fetched": 0,
            "synced": 0,
            "errors": 0,
        }

        try:
            bling_client = _bling_client_for_config(cfg)

            orders = bling_client.get_orders_by_status(
                status_id=situacao_id,
                store_id=int(bling_loja_id),
                start_date=data_inicial,
                end_date=data_final,
            )

            if not orders:
                stats["lojas"].append(loja_stat)
                continue

            loja_stat["listed"] = len(orders)
            stats["totals"]["orders_listed"] += len(orders)

            for o in orders:
                if limit_pedidos and stats["totals"]["orders_fetched"] >= limit_pedidos:
                    break

                try:
                    order_id = o.get("id")
                    if not order_id:
                        continue

                    full = bling_client.get_order(order_id)
                    loja_stat["fetched"] += 1
                    stats["totals"]["orders_fetched"] += 1

                    if not full:
                        continue

                    # Devolve para o pipeline unificado de webhook do Bling
                    process_result = _processar_pedido_bling(full, cfg)

                    if process_result.get("success"):
                        loja_stat["synced"] += 1
                        stats["totals"]["orders_synced"] += 1
                        logger.info("  → Pedido %s processado ✓", order_id)
                    else:
                        raise RuntimeError(
                            process_result.get("error", "Falha ao processar")
                        )

                except Exception as e:
                    loja_stat["errors"] += 1
                    stats["totals"]["errors"] += 1
                    logger.warning(
                        "Falha ao sync pedido Em Andamento (bling_loja_id=%s): %s",
                        bling_loja_id,
                        str(e),
                        exc_info=True,
                    )

        except Exception as e:
            loja_stat["errors"] += 1
            stats["totals"]["errors"] += 1
            logger.error(
                "Falha no fetch Em Andamento (bling_loja_id=%s, canal=%s): %s",
                bling_loja_id,
                canal_venda_id,
                str(e),
                exc_info=True,
            )

        stats["lojas"].append(loja_stat)

        # Log de resumo por loja
        logger.info(
            "═══════════════════════════════════════════════════════",
        )
        logger.info(
            "RESUMO %s: listados=%d | obtidos=%d | sincronizados=%d | erros=%d",
            (plataforma_nome or "N/A").upper(),
            loja_stat["listed"],
            loja_stat["fetched"],
            loja_stat["synced"],
            loja_stat["errors"]
        )
        logger.info(
            "═══════════════════════════════════════════════════════",
        )

    # Log de resumo geral
    logger.info(
        "███████████████████████████████████████████████████████"
    )
    logger.info(
        "TOTAL GERAL: listados=%d | obtidos=%d | sincronizados=%d | erros=%d",
        stats["totals"]["orders_listed"],
        stats["totals"]["orders_fetched"],
        stats["totals"]["orders_synced"],
        stats["totals"]["errors"]
    )
    logger.info(
        "███████████████████████████████████████████████████████"
    )

    return stats
