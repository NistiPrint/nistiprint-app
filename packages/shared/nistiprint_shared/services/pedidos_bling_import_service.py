"""
Importação de pedidos 'Em Andamento' via API Bling (listagem + detalhe + OrderSyncService).
Usado pelo worker (Celery) e pode ser chamado de forma síncrona pela API (import manual).

FLUXO DE PROCESSAMENTO:
1. FASE 1 (Obrigatória): Importa TODOS os pedidos do Bling e salva na base
   - Independente de plataforma (Shopee, Amazon, MercadoLivre, Shein, etc.)
   - Dados do Bling são a fonte primária
   - Persistência ocorre ANTES de qualquer enriquecimento

2. FASE 2 (Opcional): Enriquecimento com dados do marketplace
   - Executado APÓS a persistência dos dados do Bling
   - Falha no enriquecimento NÃO afeta os dados já persistidos
   - Pode ser executado independentemente em outros pontos do sistema
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from nistiprint_shared.services.bling.bling_client import BlingClient
from nistiprint_shared.services.integracao_canal_service import integracao_canal_service
from nistiprint_shared.services.order_sync_service import order_sync_service

logger = logging.getLogger(__name__)


def _iso_date(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def _enrich_from_marketplace(full_order: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    FASE 2: Enriquece pedido com dados adicionais do marketplace.
    
    Este processo é:
    - OPCIONAL: Falha não afeta dados já persistidos do Bling
    - INDEPENDENTE: Pode ser executado em outros pontos do sistema
    - POSTERIOR: Executado APÓS persistência dos dados do Bling
    
    Args:
        full_order: Dados completos do pedido no Bling
        cfg: Configuração do vínculo com dados da integração
        
    Returns:
        Dict com status do enriquecimento
    """
    result = {"enriched": False, "platform": None, "error": None}
    
    order_sn = full_order.get("numeroLoja")
    if not order_sn:
        logger.debug("Pedido sem numeroLoja - pulando enriquecimento")
        return result

    mp_id = cfg.get("marketplace_integration_id")
    plataforma = (cfg.get("plataforma_nome") or "").lower()
    
    if not mp_id:
        logger.debug("Sem marketplace_integration_id para %s - usando apenas dados do Bling", order_sn)
        return result
    
    result["platform"] = plataforma
    
    # Atualmente apenas Shopee tem enriquecimento implementado
    if plataforma == "shopee":
        try:
            order_sync_service.sync_shopee_order(str(order_sn), instance_id=str(mp_id))
            logger.info("✓ Enriquecimento Shopee realizado para %s", order_sn)
            result["enriched"] = True
        except Exception as e:
            # Falha no enriquecimento NÃO deve bloquear - dados do Bling já estão persistidos
            logger.warning(
                "⚠ Enriquecimento Shopee falhou para %s: %s (dados do Bling permanecem válidos)",
                order_sn, e
            )
            result["error"] = str(e)
    else:
        logger.debug("Plataforma %s não possui enriquecimento implementado - usando dados do Bling", plataforma)
    
    return result


def _sync_bling_order_phase1(full_order: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    FASE 1: Sincroniza pedido do Bling na base de dados.
    
    Este processo é:
    - OBRIGATÓRIO: Todos os pedidos devem ser persistidos
    - INDEPENDENTE DE PLATAFORMA: Funciona para qualquer marketplace
    - PRIORITÁRIO: Ocorre antes do enriquecimento
    
    Args:
        full_order: Dados completos do pedido no Bling
        cfg: Configuração do vínculo
        
    Returns:
        Resultado da sincronização
    """
    bling_id = full_order.get("id")
    order_sn = full_order.get("numeroLoja")
    
    logger.info(
        "FASE 1: Sincronizando pedido Bling %s (numeroLoja=%s)",
        bling_id,
        order_sn or "N/A"
    )
    
    result = order_sync_service.sync_bling_order(full_order)
    
    if result.get("error"):
        logger.error("✗ FASE 1 falhou para pedido %s: %s", bling_id, result["error"])
    else:
        logger.info(
            "✓ FASE 1 concluída: pedido %s persistido com sucesso",
            bling_id
        )
    
    return result


def _bling_client_for_config(cfg: Dict[str, Any]) -> BlingClient:
    """
    Cria cliente Bling para uma configuração específica.
    Prioriza bling_integration_id se disponível, caso contrário usa a plataforma.
    """
    bling_iid = cfg.get("bling_integration_id")
    if bling_iid:
        return BlingClient.create_client_for_integration_id(int(bling_iid))
    
    # Usar a plataforma real da configuração (sem fallback para shopee)
    plataforma_nome = cfg.get("plataforma_nome")
    canal_venda_id = cfg.get("canal_venda_id")
    
    if plataforma_nome:
        return BlingClient.create_client_for_platform(
            plataforma_nome.lower(),
            channel_id=canal_venda_id,
            function_name="ORDER_IMPORT",
        )
    
    # Fallback: tentar obter a plataforma do canal_venda
    if canal_venda_id:
        canal_info = integracao_canal_service.get_integration_by_canal(canal_venda_id, expected_module='bling')
        if canal_info and canal_info.get("plataforma_nome"):
            return BlingClient.create_client_for_platform(
                canal_info["plataforma_nome"].lower(),
                channel_id=canal_venda_id,
                function_name="ORDER_IMPORT",
            )
    
    # Último fallback: usar shopee (legado)
    logger.warning("Configuração sem plataforma definida - usando fallback shopee")
    return BlingClient.create_client_for_platform(
        "shopee",
        channel_id=canal_venda_id,
        function_name="ORDER_IMPORT",
    )


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

                    # ===========================================
                    # FASE 1: Persistir dados do Bling (OBRIGATÓRIO)
                    # ===========================================
                    phase1_result = _sync_bling_order_phase1(full, cfg)
                    
                    if phase1_result.get("error"):
                        raise RuntimeError(phase1_result["error"])

                    # ===========================================
                    # FASE 2: Enriquecimento marketplace (OPCIONAL)
                    # ===========================================
                    # Executado APÓS persistência - falha não afeta dados do Bling
                    phase2_result = _enrich_from_marketplace(full, cfg)
                    
                    loja_stat["synced"] += 1
                    stats["totals"]["orders_synced"] += 1
                    
                    # Log do resultado das duas fases
                    if phase2_result.get("enriched"):
                        logger.info(
                            "  → Pedido %s: FASE 1 ✓ | FASE 2 ✓ (%s)",
                            order_id,
                            phase2_result.get("platform", "unknown")
                        )
                    elif phase2_result.get("error"):
                        logger.info(
                            "  → Pedido %s: FASE 1 ✓ | FASE 2 ⚠ (enriquecimento falhou, dados do Bling válidos)",
                            order_id
                        )
                    else:
                        logger.info(
                            "  → Pedido %s: FASE 1 ✓ | FASE 2 - (sem enriquecimento para %s)",
                            order_id,
                            plataforma_nome or "N/A"
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
