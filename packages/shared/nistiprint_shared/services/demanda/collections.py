import hashlib
import json
import logging
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.auditoria_service import auditoria_service
from typing import List, Dict, Any, Optional
import uuid
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
        demanda = self.get_demanda_with_itens(demanda_id)
        if not demanda:
            raise ValueError(f"Demanda {demanda_id} não encontrada.")
        internal_id = int(demanda['id'])
        operation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nistiprint:coleta-total:{internal_id}"))
        self._registrar_coleta_transacional(
            internal_id, None, user_id, operation_id, finalizar_total=True
        )
        return self.get_demanda_with_itens(demanda_id)

    def registrar_coleta_parcial(self, demanda_id: str, quantidade_coletar: int,
                                 user_id: str = 'System', operation_id: str = None) -> Dict[str, Any]:
        """
        Registra a coleta parcial ou total de itens de uma demanda de forma consolidada.
        """
        if quantidade_coletar <= 0:
            raise ValueError("Quantidade a coletar deve ser maior que zero.")
        if not operation_id:
            raise ValueError("A coleta exige uma chave operation_id estável.")
        demanda = self.get_demanda_with_itens(demanda_id)
        if not demanda:
            raise ValueError(f"Demanda {demanda_id} não encontrada.")
        self._registrar_coleta_transacional(
            int(demanda['id']), int(quantidade_coletar), user_id, operation_id
        )
        try:
            auditoria_service.log_event('COLETA_CONSOLIDADA', {
                'demanda_id': demanda_id, 'quantidade_coletada': quantidade_coletar,
                'operation_id': operation_id,
                'descricao': f"Coleta consolidada de {quantidade_coletar} itens da demanda {demanda.get('pedido_numero')}."
            }, user_id)
        except Exception:
            logging.getLogger(__name__).exception("Falha na auditoria complementar da coleta %s", operation_id)
        return self.get_demanda_with_itens(demanda_id)

    def _registrar_coleta_transacional(self, internal_id, quantity, user_id, operation_id,
                                       finalizar_total=False):
        from uuid import UUID
        try:
            operation_id = str(UUID(str(operation_id)))
        except (TypeError, ValueError) as exc:
            raise ValueError("operation_id deve ser um UUID válido.") from exc
        payload = {
            'demanda_id': int(internal_id), 'quantidade': quantity,
            'finalizar_total': bool(finalizar_total),
        }
        content_hash = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False
        ).encode('utf-8')).hexdigest()
        result = supabase_db.rpc('registrar_coleta_demanda_transacional', {
            'p_operation_id': operation_id, 'p_content_hash': content_hash,
            'p_demanda_id': int(internal_id), 'p_quantidade': quantity,
            'p_user_id': str(user_id or 'System'), 'p_finalizar_total': bool(finalizar_total),
        }).execute().data
        result = result[0] if isinstance(result, list) and result else result
        if not isinstance(result, dict) or result.get('status') != 'CONFIRMADO':
            raise RuntimeError(f"O banco não confirmou a coleta: {result}")
        return result

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
