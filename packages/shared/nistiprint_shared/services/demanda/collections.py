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


class DemandaCollectionsService:
    def __init__(self):
        self.demandas_table = supabase_db.table('demandas_producao')
        self.itens_table = supabase_db.table('itens_demanda')

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

        # Agendar baixa final de estoque
        self.agendar_processamento_estoque(demanda_id, None, 'DEMANDA_TOTAL', 1, user_id)
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

        return self.get_demanda_with_itens(demanda_id)

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
