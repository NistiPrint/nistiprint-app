"""Asynchronous NF-e emission for production demands."""

import logging

from celery import shared_task

from nistiprint_shared.services.async_operation_service import async_operation_service
from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
from nistiprint_shared.services.order_erp_reference_service import order_erp_reference_service

logger = logging.getLogger(__name__)


def _order_context(pedido):
    return {
        "id": pedido.get("bling_order_id"),
        "numero": pedido.get("bling_numero") or pedido.get("numero_pedido"),
        "numeroLoja": pedido.get("codigo_pedido_externo"),
        "contato": {"nome": pedido.get("cliente_nome")},
    }


def _store_progress(operation_id, total, processed, results, failed):
    message = f"{processed} de {total} pedidos verificados"
    if failed:
        message += f" · {failed} com falha"
    async_operation_service.update_operation(
        operation_id,
        status="EM_ANDAMENTO",
        mensagem=message,
        etapa="Emitindo NF-e",
        progresso_atual=processed,
        progresso_total=total,
        dados_adicionais={
            "falhas": failed,
            "sucesso": processed - failed,
            "resultados": results,
        },
    )


@shared_task(name="nistiprint_shared.services.nfe_emission_service.emitir_nfes_demanda", bind=True)
def emitir_nfes_demanda(self, operation_id, demanda_id, requested_instance_id=None):
    """Generate each NF-e independently and persist user-visible progress."""
    try:
        async_operation_service.update_operation(
            operation_id,
            status="EM_ANDAMENTO",
            etapa="Validando pedidos e contas emissoras",
        )
        demanda = demanda_producao_service.get_demanda_with_itens(demanda_id)
        if not demanda:
            raise RuntimeError("Demanda não encontrada.")
        pedidos_origem = demanda.get("pedidos_origem") or []
        if not pedidos_origem:
            raise RuntimeError("A demanda não possui pedidos relacionados.")

        grupos = {}
        resultados = []
        bloqueados = []
        for pedido in pedidos_origem:
            resolution = order_erp_reference_service.resolve_order(
                pedido.get("pedido_id"), allow_remote=True
            )
            if resolution.get("status") != "ready":
                bloqueados.append({
                    "pedido": pedido,
                    "order": {
                        "id": None,
                        "numero": pedido.get("numero_pedido"),
                        "numeroLoja": pedido.get("codigo_pedido_externo"),
                    },
                    "error": resolution.get("message") or resolution.get("status") or "Pedido sem referência no ERP.",
                })
                continue
            pedido["bling_integration_id"] = resolution.get("erp_integration_id")
            pedido["bling_order_id"] = resolution.get("erp_order_id")
            pedido["bling_numero"] = resolution.get("erp_order_number")
            integration_id = pedido.get("bling_integration_id")
            if requested_instance_id and str(integration_id) != str(requested_instance_id):
                continue
            grupos.setdefault(integration_id, []).append(pedido)

        elegiveis = sum(len(items) for items in grupos.values())
        total = elegiveis + len(bloqueados)
        if not grupos and not bloqueados:
            raise RuntimeError("Nenhum pedido da demanda corresponde à conta Bling selecionada.")

        for blocked in bloqueados:
            resultados.append({
                "status": "error",
                "success": False,
                "order": blocked["order"],
                "error": blocked["error"],
            })
        processed = len(bloqueados)
        failed = len(bloqueados)
        if processed:
            _store_progress(operation_id, total, processed, resultados, failed)

        from nistiprint_shared.services.installed_integration_service import installed_integration_service
        from nistiprint_shared.services.bling.bling_client_updated import BlingClient

        for integration_id, pedidos in grupos.items():
            integration = installed_integration_service.get_installed_by_id(str(integration_id)) if integration_id else None
            if not integration:
                for pedido in pedidos:
                    resultados.append({
                        "status": "error",
                        "success": False,
                        "order": _order_context(pedido),
                        "error": f"Conta Bling {integration_id or 'não informada'} não encontrada.",
                    })
                    processed += 1
                    failed += 1
                    _store_progress(operation_id, total, processed, resultados, failed)
                continue

            account = integration.to_dict()
            account["id"] = integration.id
            if getattr(integration, "access_token", None):
                account["access_token"] = integration.access_token
            if getattr(integration, "refresh_token", None):
                account["refresh_token"] = integration.refresh_token
            bling_client = BlingClient(account)

            for pedido in pedidos:
                order = _order_context(pedido)
                if not order.get("id"):
                    result_row = {
                        "status": "error",
                        "success": False,
                        "order": order,
                        "error": "Pedido sem ID interno do Bling para gerar NF.",
                    }
                else:
                    try:
                        result = bling_client.generate_nfe(order)
                        result_row = {
                            "status": "processing",
                            "success": not result.get("error"),
                            "order": {**order, "nfe_id": result.get("nfe_id")},
                            "bling_integration_id": integration_id,
                            "account_label": pedido.get("bling_account_label"),
                        }
                        if result.get("error"):
                            result_row["status"] = "error"
                            result_row["error"] = result.get("error_message") or "Erro ao gerar NF-e."
                    except Exception as exc:
                        logger.exception("Falha ao gerar NF-e do pedido %s", order.get("id"))
                        result_row = {
                            "status": "error",
                            "success": False,
                            "order": order,
                            "bling_integration_id": integration_id,
                            "error": str(exc),
                        }
                resultados.append(result_row)
                processed += 1
                if not result_row.get("success"):
                    failed += 1
                _store_progress(operation_id, total, processed, resultados, failed)

        summary = f"{processed - failed} NF-e(s) emitida(s)"
        if failed:
            summary += f" · {failed} pedido(s) com falha"
        async_operation_service.update_operation(
            operation_id,
            status="ERRO" if failed else "CONCLUIDO",
            mensagem=summary,
            etapa="Concluído" if not failed else "Concluído com falhas",
            progresso_atual=processed,
            progresso_total=total,
            erro_resumo=f"{failed} pedido(s) precisam de atenção." if failed else None,
            dados_adicionais={
                "falhas": failed,
                "sucesso": processed - failed,
                "resultados": resultados,
            },
        )
    except Exception as exc:
        logger.exception("Falha no processo de NF-e da demanda %s", demanda_id)
        async_operation_service.update_operation(
            operation_id,
            status="ERRO",
            etapa="Falhou",
            mensagem="Não foi possível concluir a emissão de NF-e.",
            erro_resumo=str(exc)[:500],
        )
        raise
