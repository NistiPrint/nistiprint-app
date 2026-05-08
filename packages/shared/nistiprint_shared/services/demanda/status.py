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

# Importar core service para métodos auxiliares
from .core import demanda_core_service


class DemandaStatusService:
    def __init__(self):
        self.demandas_table = supabase_db.table('demandas_producao')
        self.itens_table = supabase_db.table('itens_demanda')
        # Referência ao core service para métodos auxiliares
        self._core = demanda_core_service

    def get_demanda_with_itens(self, demanda_id: str) -> Dict[str, Any]:
        """Busca demanda com seus itens."""
        return self._core.get_demanda_with_itens(demanda_id)

    def _verificar_e_finalizar_demanda_automatica(self, demanda_id, user_id='System'):
        """Verifica se todos os itens de uma demanda estão concluídos e a finaliza se sim."""
        try:
            # Check if demand is already concluded to prevent infinite loops
            demanda_res = supabase_db.execute_with_retry(self.demandas_table.select("status").eq('id', demanda_id))
            if demanda_res.data and demanda_res.data[0]['status'] in ['CONCLUIDO', 'CANCELADO']:
                return

            itens_res = supabase_db.execute_with_retry(self.itens_table.select("status_item").eq('demanda_id', demanda_id))
            if itens_res.data:
                # Only auto-finalize if ALL items are 'Concluído' (not 'Fechando')
                todos_concluidos = all(i.get('status_item') == 'Concluído' for i in itens_res.data)
                if todos_concluidos:
                    self.finalizar_demanda_completa(demanda_id, user_id)
        except Exception as e:
            print(f"Erro ao verificar finalização automática da demanda {demanda_id}: {e}")

    def _baixar_estoque_demanda(self, demanda_id: str, user_id: str = 'System'):
        """Efetiva a saída do estoque para todos os itens de uma demanda via motor Waterfall."""
        try:
            # Check for existing movements to prevent double deduction
            ref_motive = f"Saída Automática - Demanda {demanda_id}"
            existing = supabase_db.execute_with_retry(
                estoque_service.movimentacoes_table.select("id").ilike('motivo', f"{ref_motive}%")
            )
            if existing.data:
                return

            demanda = self.get_demanda_with_itens(demanda_id)
            if not demanda: return

            correlation_id = f"DEM-{demanda_id}-{uuid.uuid4().hex[:6]}"

            for item in demanda.get('itens', []):
                if not item.get('produto_id'):
                    continue

                produto_id_demanda = int(item['produto_id'])

                # PROTEÇÃO CONTRA BAIXA DUPLA:
                # Subtraímos o que já foi baixado via coleta parcial
                quantidade_ja_baixada = item.get('expedicao_capas_retiradas_qtd', 0)
                quantidade_a_baixar = item['quantidade'] - quantidade_ja_baixada

                if quantidade_a_baixar <= 0:
                    continue

                # Chama o processamento recursivo que agora implementa a lógica Waterfall completa
                self.processar_insumos_por_bom_recursivo(
                    produto_id=produto_id_demanda,
                    quantidade=quantidade_a_baixar,
                    correlation_id=correlation_id,
                    user_id=user_id,
                    tipo_operacao='CONSUMO_BOM'
                )

                # Liberar a reserva do produto final (que foi feita na criação da demanda)
                try:
                    estoque_service.liberar_reserva(
                        produto_id=produto_id_demanda,
                        quantidade=quantidade_a_baixar
                    )
                except: pass

            auditoria_service.log_event('ESTOQUE_BAIXADO_DEMANDA', {
                'demanda_id': demanda_id,
                'status': 'Sucesso',
                'correlation_id': correlation_id
            }, user_id)
        except Exception as e:
            print(f"Erro ao baixar estoque da demanda {demanda_id}: {e}")

    # Status válidos (canônicos) e seus aliases legados
    _STATUS_VALIDOS = {
        'AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL', 'CONCLUIDO', 'CANCELADO',
        'Pendente', 'Em Produção', 'Em Andamento', 'Concluído', 'Cancelado',
    }

    def transicionar_status(self, demanda_id: str, novo_status: str, user_id: str = 'System') -> Dict[str, Any]:
        """
        Altera o status de uma demanda com validação básica.
        Não valida o grafo de transições (qualquer status válido é aceito);
        para transições mais rígidas, ver auto_atualizar_status_demanda.
        """
        if novo_status not in self._STATUS_VALIDOS:
            raise ValueError(f"Status inválido: {novo_status}. Válidos: {sorted(self._STATUS_VALIDOS)}")

        updates = {'status': novo_status}
        if novo_status in ('CONCLUIDO', 'Concluído'):
            updates['data_conclusao'] = get_now_iso()

        return self._core.update_demanda_details(demanda_id, updates, user_id)

    def auto_atualizar_status_demanda(self, demanda_id: str) -> str:
        """
        Avalia o estado dos itens e atualiza o status da demanda automaticamente.
        Retorna o novo status aplicado (ou o atual se nenhuma mudança foi necessária).
        """
        try:
            demanda_res = supabase_db.execute_with_retry(
                self.demandas_table.select("status").eq('id', demanda_id)
            )
            if not demanda_res.data:
                return ''
            status_atual = demanda_res.data[0]['status']
            if status_atual in ('CONCLUIDO', 'Concluído', 'CANCELADO', 'Cancelado'):
                return status_atual

            itens_res = supabase_db.execute_with_retry(
                self.itens_table.select("status_item, finalizados_qtd, quantidade_total")
                .eq('demanda_id', demanda_id)
            )
            itens = itens_res.data or []
            if not itens:
                return status_atual

            todos_concluidos = all(i.get('status_item') == 'Concluído' for i in itens)
            algum_progresso = any(
                (i.get('finalizados_qtd') or 0) > 0
                or i.get('status_item') in ('Em Andamento', 'Fechando', 'EM_PRODUCAO')
                for i in itens
            )
            algum_finalizado_parcial = any(
                0 < (i.get('finalizados_qtd') or 0) < (i.get('quantidade_total') or 0)
                for i in itens
            )

            if todos_concluidos:
                novo = 'CONCLUIDO'
            elif algum_finalizado_parcial:
                novo = 'COLETA_PARCIAL'
            elif algum_progresso:
                novo = 'EM_PRODUCAO'
            else:
                novo = status_atual

            if novo != status_atual:
                self.transicionar_status(demanda_id, novo, 'System')
                return novo
            return status_atual
        except Exception as e:
            print(f"Erro em auto_atualizar_status_demanda({demanda_id}): {e}")
            return ''

    def finalizar_demanda_completa(self, demanda_id, user_id='System'):
        # 1. Finalizar cada item individualmente (isso dispara estoque, cascatas e logs)
        try:
            from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
            itens_res = supabase_db.execute_with_retry(self.itens_table.select("id, status_item").eq('demanda_id', demanda_id))
            if itens_res.data:
                for item in itens_res.data:
                    # Only finalize if NOT already concluded to avoid loops and duplicate events
                    if item.get('status_item') != 'Concluído':
                        demanda_producao_service.finalizar_item(demanda_id, item['id'], user_id)
        except Exception as e:
            print(f"Erro ao finalizar itens da demanda {demanda_id} no processo completo: {e}")

        # 2. Atualizar status para CONCLUIDO
        # Usando o método do core se disponível ou via update direto
        res = self._core.update_demanda_details(demanda_id, {'status': 'CONCLUIDO', 'data_conclusao': get_now_iso()}, user_id)

        # 3. AGENDAR BAIXA FINAL: Enviar para a fila para baixar estoque do produto vendido em background
        self._core.agendar_processamento_estoque(demanda_id, None, 'DEMANDA_TOTAL', 1, user_id)

        return res


demanda_status_service = DemandaStatusService()
