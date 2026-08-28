import logging
from datetime import datetime, timedelta
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.auditoria_service import auditoria_service
from nistiprint_shared.services.estoque_service import estoque_service
from nistiprint_shared.services.system_log_service import system_log_service
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.bom_service import bom_service
from nistiprint_shared.services.order_tracker_service import order_tracker_service
from nistiprint_shared.services.daily_production_log_service import daily_production_log_service
from nistiprint_shared.services.app_config_service import app_config_service
from nistiprint_shared.services.system_events_log_service import system_events_log_service
from nistiprint_shared.services.previsao_consumo_service import previsao_consumo_service
from nistiprint_shared.services.unit_of_work import UnitOfWork
from typing import List, Dict, Any, Optional
import uuid
from nistiprint_shared.utils.date_utils import get_now, get_now_iso
from .core import demanda_core_service


class DemandaCollectionsService:
    def __init__(self):
        self.demandas_table = supabase_db.table('demandas_producao')
        self.itens_table = supabase_db.table('itens_demanda')

    def get_demanda_with_itens(self, demanda_id: str) -> Optional[Dict[str, Any]]:
        """Busca demanda com seus itens (delega para core service)."""
        return demanda_core_service.get_demanda_with_itens(demanda_id)

    def _enrich_demanda_with_collection_totals(self, demanda: Dict[str, Any]) -> Dict[str, Any]:
        """Enriquece demanda com totais de coleta (delega para core service)."""
        return demanda_core_service._enrich_demanda_with_collection_totals(demanda)

    def get_coletas_da_demanda(self, demanda_id: str) -> List[Dict[str, Any]]:
        """Busca o histórico de coletas para uma demanda específica."""
        try:
            # Garante que estamos usando o ID inteiro (PK) para a consulta
            demanda_res = self.demandas_table.select("id").eq('id', demanda_id).execute()
            if not demanda_res.data:
                demanda_res = self.demandas_table.select("id").eq('demanda_id', demanda_id).execute()
                if not demanda_res.data:
                    return [] # Demanda não encontrada

            internal_pk = demanda_res.data[0]['id']

            res = supabase_db.execute_with_retry(
                supabase_db.table('entrega_producao')
                .select('*')
                .eq('demanda_id', internal_pk)
                .order('created_at', desc=True)
            )
            return res.data
        except Exception as e:
            print(f"Erro ao buscar histórico de coletas para demanda {demanda_id}: {e}")
            return []

    def get_historico_coletas_global(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Busca o histórico global de coletas (entrega_producao)."""
        try:
            # Join with demandas_producao to get demand name/number
            res = supabase_db.execute_with_retry(
                supabase_db.table('entrega_producao')
                .select('*, demandas_producao(descricao, pedido_numero, canal_venda:canais_venda(nome))')
                .order('created_at', desc=True)
                .limit(limit)
            )
            return res.data or []
        except Exception as e:
            print(f"Erro ao buscar histórico global de coletas: {e}")
            return []

    def marcar_como_coletado(self, demanda_id, user_id='System'):
        from pytz import timezone
        from ..constants import APP_TIMEZONE
        tz = timezone(APP_TIMEZONE)
        now_local = datetime.now(tz)
        current_time = now_local.strftime('%H:%M:%S')

        res = self.update_demanda_details(demanda_id, {
            'status': 'COLETADO',
            'data_conclusao': get_now_iso(),
            'horario_coleta': current_time # Atualiza para a hora real do evento
        }, user_id)

        # QA-5: a saida do produto acabado acontece aqui, na coleta completa.
        # Antes isto enfileirava 'DEMANDA_TOTAL' em fila_processamento_estoque,
        # mas o processador so trata RECONCILIACAO_ITEM, ITEM_TOTAL_BOM_PROCESS,
        # CONSUMO_BOM e ESTORNO_BOM — 'DEMANDA_TOTAL' caia num print de debug e
        # era descartado. Nenhuma saida jamais foi registrada.
        self._registrar_saida_por_coleta(demanda_id, user_id)
        return res

    def registrar_coleta_parcial(self, demanda_id: str, quantidade_coletar: int, user_id: str = 'System') -> Dict[str, Any]:
        """
        Registra a coleta parcial ou total de itens de uma demanda de forma consolidada.
        """
        demanda = self.get_demanda_with_itens(demanda_id)
        if not demanda:
            raise ValueError(f"Demanda {demanda_id} não encontrada.")

        if quantidade_coletar <= 0:
            raise ValueError("Quantidade a coletar deve ser maior que zero.")

        total_itens_pedido = sum(i['quantidade'] for i in demanda['itens'])
        ja_coletado = demanda.get('quantidade_coletada_total', 0)
        saldo_restante = total_itens_pedido - ja_coletado

        if quantidade_coletar > saldo_restante:
            raise ValueError(f"Quantidade a coletar ({quantidade_coletar}) excede o saldo disponível ({saldo_restante}).")

        # 1. Registrar em entrega_producao
        entrega_payload = {
            'id': str(uuid.uuid4()),
            'item_demanda_id': None,  # Para coletas consolidadas, não associamos a um item específico
            'data_entrega': get_now().date().isoformat(),
            'quantidade': quantidade_coletar,
            'demanda_id': demanda['id'],
            'user_id': user_id,
            'created_at': get_now_iso()
        }
        supabase_db.execute_with_retry(supabase_db.table('entrega_producao').insert(entrega_payload))

        # Auditoria
        auditoria_service.log_event('COLETA_CONSOLIDADA', {
            'demanda_id': demanda_id,
            'quantidade_coletada': quantidade_coletar,
            'descricao': f"Coleta consolidada de {quantidade_coletar} itens da demanda {demanda.get('pedido_numero')}."
        }, user_id)

        # 2. Reavaliar o status da demanda
        return self._atualizar_status_demanda_apos_coleta(demanda_id, user_id)

    def _atualizar_status_demanda_apos_coleta(self, demanda_id: str, user_id: str = 'System') -> Dict[str, Any]:
        """
        Verifica o estado total da demanda para determinar o status após coleta consolidada.
        """
        demanda = self.get_demanda_with_itens(demanda_id)
        if not demanda:
            raise ValueError(f"Demanda {demanda_id} não encontrada.")

        total_itens_demandados = sum(i['quantidade'] for i in demanda['itens'])

        # Recarregar totais para garantir precisão
        demanda = self._enrich_demanda_with_collection_totals(demanda)
        total_itens_coletados = demanda.get('quantidade_coletada_total', 0)

        novo_status = demanda['status']

        if total_itens_coletados == 0:
            if all(item.get('status_item') == 'Pendente' for item in demanda['itens']):
                novo_status = 'AGUARDANDO'
            else:
                novo_status = 'EM_PRODUCAO'
        elif total_itens_coletados >= total_itens_demandados:
            novo_status = 'COLETADO'
            data_conclusao = get_now_iso()
            if demanda.get('data_conclusao') is None:
                supabase_db.execute_with_retry(self.demandas_table.update({'data_conclusao': data_conclusao}).eq('id', demanda['id']))
        else:
            novo_status = 'COLETA_PARCIAL'

        # Atualizar status se mudou
        if demanda['status'] != novo_status:
            supabase_db.execute_with_retry(self.demandas_table.update({'status': novo_status, 'updated_at': get_now_iso()}).eq('id', demanda['id']))
            auditoria_service.log_event('STATUS_DEMANDA_ATUALIZADO', {
                'demanda_id': demanda_id,
                'status_antigo': demanda['status'],
                'status_novo': novo_status,
                'descricao': f"Status atualizado para {novo_status} após coleta consolidada."
            }, user_id)

        # QA-5: coleta parcial nao movimenta nada. So quando a demanda fecha
        # por completo o produto acabado sai do estoque — e o momento em que a
        # mercadoria deixa fisicamente a empresa.
        if novo_status == 'COLETADO':
            self._registrar_saida_por_coleta(demanda_id, user_id)

        return self.get_demanda_with_itens(demanda_id)

    def _registrar_saida_por_coleta(self, demanda_id, user_id='System'):
        """
        Fecha a demanda coletada: finaliza os itens e baixa o produto acabado.

        A RPC faz duas coisas distintas, nessa ordem:
          1. Finaliza TODOS os itens da demanda, com ou sem produto mapeado.
             A coleta e um fato operacional — a mercadoria saiu, o item acabou.
          2. Baixa o estoque apenas dos itens com produto mapeado. Item sem
             produto nao tem o que movimentar.

        A RPC e idempotente e recusa demanda que nao esteja em COLETADO, entao
        chamar duas vezes — ou por um caminho que ainda nao fechou a coleta —
        nao duplica baixa. Falha aqui nao derruba o registro da coleta: a
        coleta e o fato operacional, a baixa e consequencia.
        """
        try:
            resposta = supabase_db.rpc('registrar_saida_coleta_demanda', {
                'p_demanda_id': int(demanda_id),
                'p_user_id': str(user_id),
            }).execute()
            resultado = resposta.data or {}
            if not resultado.get('ok'):
                logging.warning(
                    f"Saida por coleta nao registrada para a demanda {demanda_id}: {resultado}"
                )
            else:
                # ok=true nao significa que tudo foi contabilizado. Item sem
                # produto_id e finalizado mas nao movimenta estoque, e ate aqui
                # isso passava despercebido: a demanda 139 fechou com 20 de 21
                # itens sem baixa e ninguem foi avisado.
                sem_produto = int(resultado.get('itens_sem_produto_mapeado') or 0)
                if sem_produto > 0:
                    logging.warning(
                        f"Demanda {demanda_id}: {sem_produto} item(ns) finalizados sem "
                        f"movimentacao de estoque por falta de produto mapeado. "
                        f"Baixados: {resultado.get('itens_baixados')}, "
                        f"finalizados agora: {resultado.get('itens_finalizados')}. "
                        f"Cadastre o SKU em produtos para que o estoque seja contabilizado."
                    )
                    system_log_service.log(
                        category='ESTOQUE',
                        message=(
                            f"Coleta da demanda {demanda_id} finalizou {sem_produto} "
                            f"item(ns) sem produto mapeado — sem movimentacao de estoque."
                        ),
                        severity='WARNING',
                        action='registrar_saida_por_coleta',
                        reference_id=str(demanda_id),
                        metadata=resultado,
                    )
            return resultado
        except Exception as e:
            logging.error(f"Falha ao registrar saida por coleta da demanda {demanda_id}: {e}")
            return None

    def marcar_lote_como_coletado(self, demanda_ids, user_id='System'):
        results = []
        for d_id in demanda_ids:
            try:
                res = self.marcar_como_coletado(d_id, user_id)
                results.append(res)
            except Exception as e:
                print(f"Erro ao coletar demanda {d_id} no lote: {e}")
        return results


demanda_collections_service = DemandaCollectionsService()
