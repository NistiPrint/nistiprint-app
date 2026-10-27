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
# from nistiprint_shared.services.stock_reconciliation_service import stock_reconciliation_service

from nistiprint_shared.services.unit_of_work import UnitOfWork
from typing import List, Dict, Any, Optional
import uuid
from nistiprint_shared.utils.date_utils import get_now, get_now_iso

# Importar core service para métodos de processamento de dicionários
from .core import demanda_core_service
from .status import demanda_status_service
from ..demanda_alocacao.estoque import demanda_alocacao_estoque_service
from ..demanda_alocacao.queue import demanda_alocacao_queue_service



class DemandaItemsService:
    def __init__(self):
        self.demandas_table = supabase_db.table('demandas_producao')
        self.itens_table = supabase_db.table('itens_demanda')
        # Referências a serviços especializados para delegação
        self._core = demanda_core_service
        self._status = demanda_status_service
        self._alocacao_estoque = demanda_alocacao_estoque_service
        self._alocacao_queue = demanda_alocacao_queue_service

    def _persistir_intencao_eventos(self, item: Dict[str, Any], updates: Dict[str, Any],
                                    eventos: List[Dict[str, Any]], user_id='System',
                                    correlation_id: Optional[str] = None,
                                    bom_version_id: Optional[str] = None) -> Dict[str, Any]:
        """Grava em uma única transação o estado visual e os eventos duráveis.

        A identidade determinística transforma retries HTTP em no-ops idempotentes,
        sem deixar uma atualização visual órfã da fila de reconciliação.
        """
        import hashlib
        import json

        permitido = {
            'capas_impressas_qtd', 'capas_produzidas_qtd',
            'capas_prontas_retirada_qtd', 'miolos_prontos_retirada_qtd',
            'expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd',
            'finalizados_qtd', 'status_item',
        }
        updates_db = {k: v for k, v in updates.items() if k in permitido}
        if not eventos:
            if updates_db:
                raise ValueError('Intenção de produção requer ao menos um evento')
            return item

        bom_version_id = bom_version_id or item.get('bom_version_id')
        if not bom_version_id and item.get('produto_id'):
            published_bom = bom_service.publish_effective_version(
                int(item['produto_id']),
                actor_id=user_id,
            )
            bom_version_id = published_bom['id']

        semantic = {
            'item_id': int(item['id']),
            'updates': updates_db,
            'bom_version_id': bom_version_id,
            'eventos': [{k: e[k] for k in ('estagio', 'quantidade_reportada', 'tipo_evento')}
                        for e in eventos],
        }
        canonical = json.dumps(semantic, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        operation_key = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        namespace = uuid.UUID('b6016e1e-d5b4-4e49-9d6c-88df94a6ca62')
        correlation_base = (uuid.uuid5(namespace, f"{int(item['id'])}:{correlation_id}")
                            if correlation_id else uuid.uuid5(namespace, operation_key))
        user_numeric = int(user_id) if str(user_id).isdigit() else None
        eventos_db = []
        for event in semantic['eventos']:
            eventos_db.append({
                **event,
                'correlation_id': str(uuid.uuid5(correlation_base, event['estagio'])),
                'usuario_id': user_numeric,
            })

        response = supabase_db.rpc('gravar_intencao_eventos_producao', {
            'p_item_id': int(item['id']),
            'p_expected_revision': int(item.get('operational_revision') or 0),
            'p_updates': updates_db,
            'p_eventos': eventos_db,
            'p_bom_version_id': bom_version_id,
        }).execute()
        data = response.data
        if isinstance(data, list):
            data = data[0] if data else None
        if not isinstance(data, dict) or not data.get('success'):
            raise RuntimeError(f'Falha ao persistir intenção de produção: {data!r}')
        return data.get('item') or {**item, **updates_db,
                                    'operational_revision': data.get('revision'),
                                    'bom_version_id': bom_version_id or item.get('bom_version_id')}

    def registrar_producao_incremental(self, demanda_id, item_id, producao_incremental, user_id='System',
                                      origem_tipo=1, retroactive_date=None, correlation_id=None):
        """Registra producao incremental pelo caminho unico de estoque.

        O contrato com o frontend continua sendo em deltas. A conversao para valor
        absoluto acontece aqui, contra o valor vigente no banco (e nao contra o que
        a tela tinha em memoria), e a gravacao segue por atualizar_progresso_item ->
        eventos_producao_v2 -> ConsolidadorDeEstoque, que e o unico motor que
        alimenta o ledger demanda_estoque_processado.
        """
        item = self.get_item_by_id(item_id)
        if correlation_id:
            root = uuid.uuid5(uuid.UUID('b6016e1e-d5b4-4e49-9d6c-88df94a6ca62'),
                              f"{int(item['id'])}:{correlation_id}")
            event_id = str(uuid.uuid5(root, 'progresso_item_atualizado'))
            replay = supabase_db.table('eventos_producao_v2').select('id').eq(
                'correlation_id', event_id).limit(1).execute()
            if replay.data:
                return self._process_item_dict(self.get_item_by_id(item_id))

        absolutos = {}
        for campo, delta in (producao_incremental or {}).items():
            if campo not in item:
                continue
            try:
                valor_delta = float(delta or 0)
            except (TypeError, ValueError):
                raise ValueError(f"Delta invalido para o campo {campo}: {delta}")
            if valor_delta == 0:
                continue
            valor_atual = float(item.get(campo) or 0)
            novo_valor = self._calcular_progresso_visual(valor_atual, valor_delta)
            if novo_valor < valor_atual:
                raise ValueError(
                    f'RECONCILIACAO_REDUCAO_REQUER_COMPENSACAO:{campo}. '
                    'A redução foi bloqueada até existir compensação física rastreável.'
                )
            absolutos[campo] = novo_valor

        if not absolutos:
            return self._process_item_dict(item)

        return self.atualizar_progresso_item(
            demanda_id, item_id, absolutos, user_id, correlation_id=correlation_id)

    def registrar_producao_lote(self, demanda_id: str, updates: List[Dict[str, Any]], user_id: str = 'System',
                                origem_tipo: int = 1, retroactive_date: str = None,
                                correlation_id: str = None) -> Dict[str, Any]:
        """Registra producao para multiplos itens, um a um, pelo mesmo caminho unico."""
        results = []
        for update in updates:
            item_id = update.get('item_id')
            # O frontend envia 'producao_incremental' como um dict de deltas
            deltas = update.get('producao_incremental', {})
            if not item_id or not deltas:
                continue

            results.append(self.registrar_producao_incremental(
                demanda_id, item_id, deltas, user_id,
                origem_tipo=origem_tipo,
                retroactive_date=retroactive_date,
                correlation_id=correlation_id
            ))

        return {"success": True, "results": results}

    def _process_item_dict(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Adiciona aliases e processa campos para o frontend."""
        return self._core._process_item_dict(item)

    def _calcular_progresso_visual(self, valor_atual, delta):
        """Aplica delta no progresso visual sem permitir resultado final negativo."""
        valor_atual = float(valor_atual or 0)
        delta = float(delta or 0)
        return max(0, valor_atual + delta)

    def _verificar_e_finalizar_demanda_automatica(self, demanda_id, user_id='System'):
        """Verifica e finaliza demanda automaticamente."""
        return self._status._verificar_e_finalizar_demanda_automatica(demanda_id, user_id)

    def processar_alocacao_de_demanda(self, item_id, campo, incremento, user_id, skip_visual_update=False, origem_tipo=None, retroactive_date=None, correlation_id=None):
        """Processa alocação de estoque com base no estágio de produção."""
        return self._alocacao_estoque.processar_alocacao_de_demanda(
            item_id, campo, incremento, user_id, skip_visual_update,
            origem_tipo, retroactive_date, correlation_id
        )

    def agendar_processamento_estoque(self, demanda_id, item_id, campo, incremento, user_id='System', correlation_id=None, created_at=None, produto_id=None, forcar_sincrono=False):
        """Agenda processamento de estoque na fila."""
        return self._alocacao_queue.agendar_processamento_estoque(
            demanda_id, item_id, campo, incremento, user_id,
            correlation_id, created_at, produto_id, forcar_sincrono
        )



    def get_item_by_id(self, item_id):
        """Função auxiliar para buscar um item de demanda pelo ID."""
        if not item_id or item_id == 'None':
            raise ValueError(f"ID de item inválido: {item_id}")

        # Garante que item_id seja inteiro para a consulta .eq()
        try:
            clean_id = int(item_id)
        except (ValueError, TypeError):
            raise ValueError(f"ID de item deve ser numérico: {item_id}")

        response = supabase_db.execute_with_retry(self.itens_table.select("*").eq('id', clean_id))
        if not response.data:
            raise ValueError(f"Item {clean_id} não encontrado")
        return response.data[0]

    def atualizar_progresso_item(self, demanda_id: str, item_id: str, quantities_to_update: Dict[str, float], user_id: str = 'System', correlation_id=None):
        """
        Atualiza o progresso de um item e dispara a Reconciliação Determinística de Estoque.
        """
        response = supabase_db.execute_with_retry(self.itens_table.select("*").eq('id', item_id))
        if not response.data: raise ValueError(f"Item {item_id} não encontrado")

        item = response.data[0]
        updates = {'updated_at': get_now_iso()}

        # 1. Preparar atualizações visuais
        for key, new_value in quantities_to_update.items():
            if key not in item: continue
            normalized_value = max(0, float(new_value or 0))
            if normalized_value < float(item.get(key) or 0):
                raise ValueError(
                    f'RECONCILIACAO_REDUCAO_REQUER_COMPENSACAO:{key}. '
                    'A redução foi bloqueada até existir compensação física rastreável.'
                )
            updates[key] = normalized_value

        # 2. Persistir a Intenção no Banco
        if updates.get('expedicao_capas_retiradas_qtd', 0) > 0 or updates.get('expedicao_miolos_retirados_qtd', 0) > 0:
            updates['status_item'] = 'Em Andamento'

        try:
            item_atualizado = self._persistir_intencao_eventos(item, updates, [{
                'estagio': 'progresso_item_atualizado',
                'quantidade_reportada': float(updates.get('finalizados_qtd', item.get('finalizados_qtd', 0)) or 0),
                'tipo_evento': 'LIQUIDACAO',
            }], user_id, correlation_id=correlation_id)
        except Exception as e:
            import traceback
            print(f"ERRO CRÍTICO na reconciliação de estoque do item {item_id}: {e}")
            traceback.print_exc()
            system_log_service.log(
                category='PRODUCAO',
                message=f"Falha na reconciliação de estoque: {str(e)}",
                severity='ERROR',
                action='atualizar_progresso_item',
                reference_id=item_id,
                metadata={'item_id': item_id, 'updates': updates, 'demanda_id': demanda_id, 'demanda_id_int': demanda_id_int}
            )
            raise

        # --- AUTOMATIZAÇÃO DE STATUS ---
        if updates.get('status_item') == 'Concluído':
            self._verificar_e_finalizar_demanda_automatica(demanda_id, user_id)

        auditoria_service.log_event('SMART_DELTA_UPDATE', {
            'item_id': item_id,
            'quantities': quantities_to_update,
            'updates_made': updates
        }, user_id)

        return self._process_item_dict({**item_atualizado, **updates})

    def _forcar_finalizacao_estoque_item(self, item_id, total_qty, user_id):
        """
        Legacy: Método descontinuado.
        Agora usa-se eventos_producao_v2 + ConsolidadorDeEstoque.
        """
        # Método descontinuado - usar eventos_producao_v2 diretamente
        pass

    def _resolver_produto_direto(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Resolve o produto principal que deve ter baixa de estoque síncrona.
        Tenta resolver MIOLO ou CAPA.
        """
        # 1. Tenta miolo associado ao item
        id_miolo = item.get('id_produto_miolo')
        if id_miolo:
            res = supabase_db.table('produtos').select('id, nome, sku').eq('id', id_miolo).maybe_single().execute()
            if res.data:
                return res.data
        
        # 2. Se não tem miolo explícito, tenta resolver via BOM do produto pai
        # (simplificação para este refactor: se for agenda/caderno, o produto_id é o produto final)
        # O ideal é buscar na BOM o componente principal.
        produto_id = item.get('produto_id')
        if produto_id:
            res = supabase_db.table('produtos').select('id, nome, sku').eq('id', produto_id).maybe_single().execute()
            if res.data:
                return res.data
        
        return None



    def reverter_finalizacao_item(self, demanda_id, item_id, user_id='System'):
        """Reverte o status de um item de 'Concluído' para 'Em Andamento'."""
        response = supabase_db.execute_with_retry(self.itens_table.select("*").eq('id', item_id))
        if not response.data:
            raise ValueError(f"Item {item_id} não encontrado")

        item_original = response.data[0]

        # Só permite reverter se o status atual for 'Concluído'
        if item_original.get('status_item') != 'Concluído':
            raise ValueError(f"Item {item_id} não está finalizado. Status atual: {item_original.get('status_item')}")

        # Reverter para status 'Em Andamento'
        updates = {
            'status_item': 'Em Andamento',
            'updated_at': get_now_iso()
        }

        supabase_db.execute_with_retry(self.itens_table.update(updates).eq('id', item_id))

        # A reconciliação aqui é tricky. Se mudamos APENAS o status, o effective quantity
        # dos estágios pode não mudar se os contadores (qtd) não mudaram.
        # Mas se o usuário "desfinalizou", talvez ele queira que o sistema pare de considerar como finalizado.
        # Como finalizados_qtd continua igual, a reconciliação não fará nada (o que é correto, o estoque já foi baixado).
        # Se ele quiser estornar o estoque, ele deve reduzir o contador 'finalizados_qtd'.
        
        # Se a demanda pai estava CONCLUIDO ou COLETADO, volta para EM_PRODUCAO para ficar visível novamente
        dem_res = supabase_db.execute_with_retry(self.demandas_table.select("status").eq('id', demanda_id))
        if dem_res.data and dem_res.data[0]['status'] in ['CONCLUIDO', 'COLETADO']:
            supabase_db.execute_with_retry(self.demandas_table.update({
                'status': 'EM_PRODUCAO',
                'updated_at': get_now_iso()
            }).eq('id', demanda_id))

        # Registrar auditoria
        auditoria_service.log_event('ITEM_REVERTIDO_FINALIZACAO', {
            'entidade_tipo': 'demanda',
            'registro_id': demanda_id,
            'demanda_id': demanda_id,
            'item_id': item_id,
            'sku': item_original.get('sku'),
            'descricao': f"Revertida finalização do item {item_original.get('sku')} na demanda {demanda_id}. Status retornou para Em Andamento."
        }, user_id)

        updated_item_res = supabase_db.execute_with_retry(self.itens_table.select("*").eq('id', item_id))
        if updated_item_res.data:
            return self._process_item_dict(updated_item_res.data[0])
        return {**self._process_item_dict(item_original), **updates}



    # Atomic production intent paths. Kept at the end of the class so legacy
    # call signatures remain intact while all public entry points share the RPC.
    def finalizar_item(self, demanda_id, item_id, user_id='System'):
        item = self.get_item_by_id(item_id)
        if item.get('status_item') == 'Concluído':
            self._verificar_e_finalizar_demanda_automatica(demanda_id, user_id)
            return self._process_item_dict(item)
        total = float(item.get('quantidade') or 0)
        updates = {key: total for key in (
            'capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd',
            'miolos_prontos_retirada_qtd', 'expedicao_capas_retiradas_qtd',
            'expedicao_miolos_retirados_qtd', 'finalizados_qtd')}
        updates.update({'status_item': 'Concluído', 'updated_at': get_now_iso()})
        updated = self._persistir_intencao_eventos(item, updates, [{
            'estagio': 'finalizados_qtd', 'quantidade_reportada': total,
            'tipo_evento': 'LIQUIDACAO',
        }], user_id)
        self._verificar_e_finalizar_demanda_automatica(demanda_id, user_id)
        return self._process_item_dict({**updated, **updates})

    def finalizar_item_parcial(self, demanda_id, item_id, quantidade_parcial, user_id='System'):
        item = self.get_item_by_id(item_id)
        total = float(item.get('quantidade') or 0)
        delta = float(quantidade_parcial or 0)
        campos = (
            'capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd',
            'miolos_prontos_retirada_qtd', 'expedicao_capas_retiradas_qtd',
            'expedicao_miolos_retirados_qtd', 'finalizados_qtd')
        updates = {key: max(0, min(total, float(item.get(key) or 0) + delta)) for key in campos}
        delta_real = updates['finalizados_qtd'] - float(item.get('finalizados_qtd') or 0)
        updates['status_item'] = 'Concluído' if updates['finalizados_qtd'] >= total else 'Em Andamento'
        updates['updated_at'] = get_now_iso()
        event = ({'estagio': 'finalizados_qtd', 'quantidade_reportada': abs(delta_real),
                  'tipo_evento': 'LIQUIDACAO'} if delta_real != 0 else
                 {'estagio': 'progresso_parcial_sem_delta',
                  'quantidade_reportada': updates['finalizados_qtd'], 'tipo_evento': 'SINAL'})
        updated = self._persistir_intencao_eventos(item, updates, [event], user_id)
        if updates['status_item'] == 'Concluído':
            self._verificar_e_finalizar_demanda_automatica(demanda_id, user_id)
        return self._process_item_dict({**updated, **updates})

    def registrar_saida_item_distribuida(self, distributions, product_id, user_id='System', transaction=None,
                                         correlation_id=None):
        role = product_service.identify_product_role(str(product_id))
        field = {'MIOLO': 'miolos_prontos_retirada_qtd',
                 'CAPA_IMPRESSAO': 'capas_impressas_qtd',
                 'CAPA_ACABADA': 'capas_produzidas_qtd'}.get(role, 'expedicao_capas_retiradas_qtd')
        for dist in distributions:
            item = self.get_item_by_id(dist['item_id'])
            qty = float(dist['quantidade'])
            stage_qty = float(dist.get('quantidade_estagio', qty))
            total = float(item.get('quantidade') or 0)
            updates = {field: max(0, min(total, float(item.get(field) or 0) + stage_qty)),
                       'status_item': 'Em Andamento', 'updated_at': get_now_iso()}
            if role == 'OUTRO':
                updates['expedicao_miolos_retirados_qtd'] = max(
                    0, min(total, float(item.get('expedicao_miolos_retirados_qtd') or 0) + qty))
                if (updates[field] >= float(item.get('quantidade') or 0)
                    and updates['expedicao_miolos_retirados_qtd'] >= float(item.get('quantidade') or 0)):
                    updates['status_item'] = 'Concluído'
            evento_id = str(correlation_id) if correlation_id else None
            self._persistir_intencao_eventos(item, updates, [{
                'estagio': field, 'quantidade_reportada': abs(stage_qty), 'tipo_evento': 'SINAL'}],
                user_id, correlation_id=evento_id)
            if updates['status_item'] == 'Concluído':
                self._verificar_e_finalizar_demanda_automatica(item['demanda_id'], user_id)
            auditoria_service.log_event('SAIDA_DISTRIBUIDA_ITEM', {
                'item_id': item['id'], 'product_id': product_id, 'role': role,
                'quantidade': qty, 'campo': field, 'novo_valor': updates[field]
            }, user_id)
        return True

    def registrar_retirada_expedicao(self, demanda_id, item_id, quantidade, user_id='System'):
        item = self.get_item_by_id(item_id)
        total = float(item.get('quantidade') or 0)
        qty = float(quantidade)
        if qty <= 0 or qty > total:
            raise ValueError(f'Quantidade inválida para retirada: {quantidade}')
        updates = {
            'expedicao_capas_retiradas_qtd': min(total, float(item.get('expedicao_capas_retiradas_qtd') or 0) + qty),
            'expedicao_miolos_retirados_qtd': min(total, float(item.get('expedicao_miolos_retirados_qtd') or 0) + qty),
            'status_item': 'Em Andamento', 'updated_at': get_now_iso(),
        }
        if updates['expedicao_capas_retiradas_qtd'] >= total and updates['expedicao_miolos_retirados_qtd'] >= total:
            updates['status_item'] = 'Fechando'
        events = [
            {'estagio': 'expedicao_capas_retiradas_qtd', 'quantidade_reportada': qty, 'tipo_evento': 'SINAL'},
            {'estagio': 'expedicao_miolos_retirados_qtd', 'quantidade_reportada': qty, 'tipo_evento': 'SINAL'},
        ]
        updated = self._persistir_intencao_eventos(item, updates, events, user_id)
        auditoria_service.log_event('RETIRADA_EXPEDICAO', {
            'demanda_id': demanda_id, 'item_id': item_id, 'quantidade': quantidade,
            'exp_capas_novo': updates['expedicao_capas_retiradas_qtd'],
            'exp_miolos_novo': updates['expedicao_miolos_retirados_qtd'],
        }, user_id)
        return self._process_item_dict({**updated, **updates})


demanda_items_service = DemandaItemsService()
