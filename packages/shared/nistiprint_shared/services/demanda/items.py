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

    def _atualizar_progresso_simples(self, item_id: str, campo: str, incremento: float):
        """Atualiza apenas o campo de progresso visual no item da demanda."""
        # Ensure item_id is an integer for database compatibility
        try:
            item_id_int = int(item_id)
        except (ValueError, TypeError):
            # If it's a UUID string or something else, logging warning but trying as is might be safer
            # or raising error if we are sure it must be int. Assuming int per schema.
            item_id_int = item_id
            print(f"WARNING: item_id '{item_id}' could not be converted to int.")

        response = supabase_db.execute_with_retry(self.itens_table.select(campo).eq('id', item_id_int))
        if not response.data:
            # Tentar buscar com string se int falhar (fallback)
            response = supabase_db.execute_with_retry(self.itens_table.select(campo).eq('id', str(item_id)))
            if not response.data:
                raise ValueError(f"Item {item_id} não encontrado para atualização de progresso")
            item_id_int = str(item_id) # Use string if that's what worked

        item = response.data[0]
        valor_atual = float(item.get(campo, 0) or 0)
        novo_valor = self._calcular_progresso_visual(valor_atual, incremento)

        updates = {campo: novo_valor, 'updated_at': get_now_iso()}
        res = supabase_db.execute_with_retry(self.itens_table.update(updates).eq('id', item_id_int))
        print(f"DEBUG: _atualizar_progresso_simples item={item_id_int} campo={campo} novo_valor={novo_valor} res.data={res.data}")

        if not res.data:
            # Se o update retornou vazio, algo deu errado (permissão ou ID mismatch silencioso)
            raise RuntimeError(f"Falha ao persistir atualização no item {item_id_int}. Nenhuma linha afetada.")

        return {
            'campo': campo,
            'valor_anterior': valor_atual,
            'incremento': incremento,
            'incremento_aplicado': novo_valor - valor_atual,
            'novo_valor': novo_valor
        }

    def _atualizar_progresso_simples_no_banco(self, item_id, campo, incremento):
        """Atualiza apenas o campo de progresso visual no item da demanda."""
        # Usar uma chamada SQL `UPDATE ... SET campo = campo + X` se possível,
        # pois é uma operação atômica no nível do banco.
        # Se o ORM não suportar, usar a lógica de ler e depois escrever.
        response = supabase_db.execute_with_retry(self.itens_table.select(campo).eq('id', item_id))
        if not response.data:
            raise ValueError(f"Item {item_id} não encontrado para atualização de progresso")

        item = response.data[0]
        valor_atual = float(item.get(campo, 0) or 0)
        novo_valor = self._calcular_progresso_visual(valor_atual, incremento)

        updates = {campo: novo_valor, 'updated_at': get_now_iso()}
        res = supabase_db.execute_with_retry(self.itens_table.update(updates).eq('id', item_id))

        if not res.data:
            # Se o update retornou vazio, algo deu errado (permissão ou ID mismatch silencioso)
            raise RuntimeError(f"Falha ao persistir atualização no item {item_id}. Nenhuma linha afetada.")

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

    def atualizar_progresso_item(self, demanda_id: str, item_id: str, quantities_to_update: Dict[str, float], user_id: str = 'System'):
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
            updates[key] = max(0, float(new_value or 0))

        # 2. Persistir a Intenção no Banco
        if updates.get('expedicao_capas_retiradas_qtd', 0) > 0 or updates.get('expedicao_miolos_retirados_qtd', 0) > 0:
            updates['status_item'] = 'Em Andamento'

        supabase_db.execute_with_retry(self.itens_table.update(updates).eq('id', item_id))

        # 3. Disparar Reconciliação Determinística (Novo Motor)
        # Ao invés de inserir na fila legada, disparamos o evento de reconciliação
        try:
            import uuid
            correlation_id = str(uuid.uuid4())
            
            # Registrar evento de produção para o motor (E7 - Liquidação ou SINAL)
            # Para este caso de atualização de progresso geral, assumimos LIQUIDACAO (ou SINAL, dependendo do estágio)
            evento = {
                'item_demanda_id': item_id,
                'demanda_id': demanda_id,
                'estagio': 'progresso_item_atualizado',
                'quantidade_reportada': float(updates.get('finalizados_qtd', item.get('finalizados_qtd', 0))),
                'quantidade_efetiva': float(updates.get('finalizados_qtd', item.get('finalizados_qtd', 0))),
                'tipo_evento': 'LIQUIDACAO',
                'processado': False,
                'correlation_id': correlation_id,
                'created_at': get_now_iso()
            }
            try:
                supabase_db.table('eventos_producao_v2').insert(evento).execute()
            except Exception as event_error:
                # Erros do Realtime (ex: StreamIDTooLowError) não devem interromper o fluxo principal
                # O evento pode não ter sido inserido, mas a atualização visual já foi persistida
                error_str = str(event_error)
                if 'StreamID' in error_str or 'Realtime' in error_str:
                    print(f"AVISO: Erro do Realtime ao inserir evento (não crítico): {event_error}")
                    system_log_service.log(
                        category='PRODUCAO',
                        message=f"Erro do Realtime ao inserir evento (ignorado): {error_str}",
                        severity='WARNING',
                        action='atualizar_progresso_item',
                        reference_id=item_id,
                        metadata={'item_id': item_id, 'error_type': 'Realtime'}
                    )
                else:
                    # Outros erros devem ser tratados como críticos
                    raise event_error

            # NOTA: O processamento do estoque é feito assincronamente pelo ConsolidadorDeEstoque
            # via Celery (tasks.eventos_tasks.process_eventos_producao)
        except Exception as e:
            print(f"ERRO CRÍTICO na reconciliação de estoque do item {item_id}: {e}")
            system_log_service.log(
                category='PRODUCAO',
                message=f"Falha na reconciliação de estoque: {str(e)}",
                severity='ERROR',
                action='atualizar_progresso_item',
                reference_id=item_id,
                metadata={'item_id': item_id, 'updates': updates}
            )

        # --- AUTOMATIZAÇÃO DE STATUS ---
        if updates.get('status_item') == 'Concluído':
            self._verificar_e_finalizar_demanda_automatica(demanda_id, user_id)

        auditoria_service.log_event('SMART_DELTA_UPDATE', {
            'item_id': item_id,
            'quantities': quantities_to_update,
            'updates_made': updates
        }, user_id)

        return self._process_item_dict({**item, **updates})

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

    def finalizar_item(self, demanda_id, item_id, user_id='System'):
        response = supabase_db.execute_with_retry(self.itens_table.select("*").eq('id', item_id))
        if not response.data:
            raise ValueError(f"Item {item_id} não encontrado")

        item_original = response.data[0]
        
        # Check if already finalized to avoid duplicate work/events
        if item_original.get('status_item') == 'Concluído':
             self._verificar_e_finalizar_demanda_automatica(demanda_id, user_id)
             return self._process_item_dict(item_original)

        total_qty = item_original['quantidade']

        # 1. VISIBILIDADE IMEDIATA: Atualizar todas as colunas no dashboard para o Total
        updates = {
            'capas_impressas_qtd': total_qty,
            'capas_produzidas_qtd': total_qty,
            'capas_prontas_retirada_qtd': total_qty,
            'miolos_prontos_retirada_qtd': total_qty,
            'expedicao_capas_retiradas_qtd': total_qty,
            'expedicao_miolos_retirados_qtd': total_qty,
            'finalizados_qtd': total_qty,
            'status_item': 'Concluído',
            'updated_at': get_now_iso()
        }

        supabase_db.execute_with_retry(self.itens_table.update(updates).eq('id', item_id))

        # 2. ESTOQUE SYNC (Produtos Diretos: Miolo/Capa)
        produto_direto = self._resolver_produto_direto(item_original)
        if produto_direto:
            try:
                estoque_service.movimentar_por_delta(
                    produto_id=produto_direto['id'],
                    delta=-float(total_qty),
                    demanda_id=demanda_id,
                    item_id=item_id,
                    idempotency_key=f"direto:finalizar:{item_id}"
                )
                logger.info(f"Baixa síncrona de estoque realizada para produto {produto_direto['id']} (item {item_id})")
            except Exception as e:
                logger.error(f"Erro na baixa síncrona de estoque (produto_direto): {e}")

        # 3. ESTOQUE ASYNC (Restante da BOM recursiva)
        # O ConsolidadorDeEstoque processará assincronamente via Celery
        try:
            import uuid
            correlation_id = str(uuid.uuid4())
            try:
                supabase_db.table('eventos_producao_v2').insert({
                    'item_demanda_id': item_id,
                    'demanda_id': demanda_id,
                    'estagio': 'finalizados_qtd',
                    'quantidade_reportada': float(total_qty),
                    'tipo_evento': 'BOM_RECURSIVO_APOS_DIRETO',
                    'skip_produto_id': produto_direto['id'] if produto_direto else None,
                    'processado': False,
                    'correlation_id': correlation_id,
                    'usuario_id': user_id if isinstance(user_id, int) else None,
                    'created_at': get_now_iso()
                }).execute()
            except Exception as event_error:
                error_str = str(event_error)
                if 'StreamID' in error_str or 'Realtime' in error_str:
                    print(f"AVISO: Erro do Realtime ao inserir evento de finalização (não crítico): {event_error}")
                else:
                    raise event_error
        except Exception as e:
            print(f"ERRO ao registrar evento de finalização do item {item_id}: {e}")

        self._verificar_e_finalizar_demanda_automatica(demanda_id, user_id)

        return self._process_item_dict({**item_original, **updates})

    def finalizar_item_parcial(self, demanda_id, item_id, quantidade_parcial, user_id='System'):
        response = supabase_db.execute_with_retry(self.itens_table.select("*").eq('id', item_id))
        if not response.data:
            raise ValueError(f"Item {item_id} não encontrado")

        item_original = response.data[0]
        total_qty = item_original['quantidade']

        # 1. VISIBILIDADE IMEDIATA (Atualização das colunas visuais)
        def get_new_val(field):
            curr = item_original.get(field, 0) or 0
            return max(0, min(total_qty, curr + quantidade_parcial))

        new_finalizados = get_new_val('finalizados_qtd')
        delta_real = new_finalizados - (item_original.get('finalizados_qtd', 0) or 0)

        updates = {
            'capas_impressas_qtd': get_new_val('capas_impressas_qtd'),
            'capas_produzidas_qtd': get_new_val('capas_produzidas_qtd'),
            'capas_prontas_retirada_qtd': get_new_val('capas_prontas_retirada_qtd'),
            'miolos_prontos_retirada_qtd': get_new_val('miolos_prontos_retirada_qtd'),
            'expedicao_capas_retiradas_qtd': get_new_val('expedicao_capas_retiradas_qtd'),
            'expedicao_miolos_retirados_qtd': get_new_val('expedicao_miolos_retirados_qtd'),
            'finalizados_qtd': new_finalizados,
            'updated_at': get_now_iso()
        }

        if updates.get('finalizados_qtd', 0) >= total_qty:
            updates['status_item'] = 'Concluído'
        else:
            updates['status_item'] = 'Em Andamento'

        supabase_db.execute_with_retry(self.itens_table.update(updates).eq('id', item_id))

        # 2. ESTOQUE SYNC (Produtos Diretos: Miolo/Capa)
        if delta_real > 0:
            produto_direto = self._resolver_produto_direto(item_original)
            if produto_direto:
                try:
                    estoque_service.movimentar_por_delta(
                        produto_id=produto_direto['id'],
                        delta=-float(delta_real),
                        demanda_id=demanda_id,
                        item_id=item_id,
                        idempotency_key=f"direto:finalizar_parcial:{item_id}:{new_finalizados}"
                    )
                except Exception as e:
                    logger.error(f"Erro na baixa síncrona de estoque parcial: {e}")

        # 3. ESTOQUE ASYNC (Restante da BOM)
        try:
            import uuid
            correlation_id = str(uuid.uuid4())
            try:
                supabase_db.table('eventos_producao_v2').insert({
                    'item_demanda_id': item_id,
                    'demanda_id': demanda_id,
                    'estagio': 'finalizados_qtd',
                    'quantidade_reportada': float(delta_real),
                    'tipo_evento': 'BOM_RECURSIVO_APOS_DIRETO',
                    'skip_produto_id': produto_direto['id'] if produto_direto else None,
                    'processado': False,
                    'correlation_id': correlation_id,
                    'usuario_id': user_id if isinstance(user_id, int) else None,
                    'created_at': get_now_iso()
                }).execute()
            except Exception as event_error:
                error_str = str(event_error)
                if 'StreamID' in error_str or 'Realtime' in error_str:
                    print(f"AVISO: Erro do Realtime ao inserir evento de finalização parcial (não crítico): {event_error}")
                else:
                    raise event_error
        except Exception as e:
            print(f"ERRO ao registrar evento de finalização parcial do item {item_id}: {e}")

        if updates.get('status_item') == 'Concluído':
            self._verificar_e_finalizar_demanda_automatica(demanda_id, user_id)

        return self._process_item_dict({**item_original, **updates})

        if updates.get('status_item') == 'Concluído':
            self._verificar_e_finalizar_demanda_automatica(demanda_id, user_id)

        return self._process_item_dict({**item_original, **updates})

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

    def registrar_saida_item_distribuida(self, distributions, product_id, user_id='System', transaction=None):
        """
        Processa a distribuição de uma quantidade de saída entre itens de demandas.
        Identifica o papel do produto para atualizar o campo de progresso correto no dashboard.
        """
        role = product_service.identify_product_role(str(product_id))

        # Mapeamento de Role para Campo do Dashboard
        role_field_map = {
            'MIOLO': 'miolos_prontos_retirada_qtd',
            'CAPA_IMPRESSAO': 'capas_impressas_qtd',
            'CAPA_ACABADA': 'capas_produzidas_qtd'
        }

        # Default para produtos finais ou kits é a retirada na expedição
        campo_a_atualizar = role_field_map.get(role, 'expedicao_capas_retiradas_qtd')

        for dist in distributions:
            item_id = dist['item_id']
            qty = float(dist['quantidade'])

            # Busca item atual
            item_res = supabase_db.execute_with_retry(self.itens_table.select("*").eq('id', item_id))
            if not item_res.data: continue
            item = item_res.data[0]

            old_val = float(item.get(campo_a_atualizar) or 0)
            new_val = max(0, old_val + qty)
            updates = {
                campo_a_atualizar: new_val,
                'updated_at': get_now_iso(),
                'status_item': 'Em Andamento'
            }

            # Se for saída final (Produto acabado ou kit), também sensibiliza a retirada do miolo
            if role == 'OUTRO':
                updates['expedicao_miolos_retirados_qtd'] = max(
                    0,
                    float(item.get('expedicao_miolos_retirados_qtd') or 0) + qty
                )

            supabase_db.execute_with_retry(self.itens_table.update(updates).eq('id', item_id))

            # Automação de status: Apenas se for a saída final (Expedição)
            if role == 'OUTRO' and new_val >= float(item['quantidade']):
                # Verifica se todas as saídas finais (capa e miolo) foram atingidas
                exp_miolo = updates.get('expedicao_miolos_retirados_qtd') or item.get('expedicao_miolos_retirados_qtd', 0)
                if float(exp_miolo) >= float(item['quantidade']):
                    supabase_db.execute_with_retry(self.itens_table.update({'status_item': 'Concluído'}).eq('id', item_id))
                    self._verificar_e_finalizar_demanda_automatica(item['demanda_id'], user_id)

            # DISPARAR EVENTO DE SAÍDA DISTRIBUÍDA (Event Sourcing)
            # O ConsolidadorDeEstoque processará assincronamente via Celery
            try:
                import uuid
                correlation_id = str(uuid.uuid4())
                try:
                    supabase_db.table('eventos_producao_v2').insert({
                        'item_demanda_id': item_id,
                        'demanda_id': item.get('demanda_id'),
                        'estagio': campo_a_atualizar,
                        'quantidade_reportada': float(qty),
                        'tipo_evento': 'SINAL',
                        'processado': False,
                        'correlation_id': correlation_id,
                        'usuario_id': user_id if isinstance(user_id, int) else None,
                        'created_at': get_now_iso()
                    }).execute()
                except Exception as event_error:
                    # Erros do Realtime não devem interromper o fluxo principal
                    error_str = str(event_error)
                    if 'StreamID' in error_str or 'Realtime' in error_str:
                        print(f"AVISO: Erro do Realtime ao inserir evento de saída distribuída (não crítico): {event_error}")
                    else:
                        raise event_error
            except Exception as e:
                print(f"ERRO ao registrar evento de saída distribuída do item {item_id}: {e}")

            auditoria_service.log_event('SAIDA_DISTRIBUIDA_ITEM', {
                'item_id': item_id,
                'product_id': product_id,
                'role': role,
                'quantidade': qty,
                'campo': campo_a_atualizar,
                'novo_valor': new_val
            }, user_id)

        return True

    def registrar_retirada_expedicao(self, demanda_id: str, item_id: str, quantidade: int, user_id: str = 'System') -> Dict[str, Any]:
        """
        Registra a retirada de capas e miolos na expedição para um item de demanda.

        Atualiza simultaneamente os campos expedicao_capas_retiradas_qtd e expedicao_miolos_retirados_qtd,
        pois na expedição o produto final (capa + miolo) é retirado junto.

        Args:
            demanda_id: ID da demanda
            item_id: ID do item da demanda
            quantidade: Quantidade a retirar (unidades completas capa+miolo)
            user_id: ID do usuário

        Returns:
            Item atualizado com os novos valores de expedição

        Raises:
            ValueError: Se o item não for encontrado ou quantidade for inválida
        """
        # Buscar item
        response = supabase_db.execute_with_retry(self.itens_table.select("*").eq('id', item_id))
        if not response.data:
            raise ValueError(f"Item {item_id} não encontrado")

        item = response.data[0]
        total_qty = item['quantidade']

        # Validar quantidade
        if quantidade <= 0:
            raise ValueError("Quantidade deve ser maior que zero")

        if quantidade > total_qty:
            raise ValueError(f"Quantidade ({quantidade}) excede a quantidade total do item ({total_qty})")

        # Calcular novos valores
        exp_capas_atual = float(item.get('expedicao_capas_retiradas_qtd', 0) or 0)
        exp_miolos_atual = float(item.get('expedicao_miolos_retirados_qtd', 0) or 0)

        nova_exp_capas = min(total_qty, exp_capas_atual + quantidade)
        nova_exp_miolos = min(total_qty, exp_miolos_atual + quantidade)

        # Atualizar item
        updates = {
            'expedicao_capas_retiradas_qtd': nova_exp_capas,
            'expedicao_miolos_retirados_qtd': nova_exp_miolos,
            'status_item': 'Em Andamento',
            'updated_at': get_now_iso()
        }

        # Se atingiu a quantidade total, marcar como "Fechando" (não mais Concluído)
        # Itens só serão marcados como Concluído quando explicitamente finalizados via botão no dashboard
        if nova_exp_capas >= total_qty and nova_exp_miolos >= total_qty:
            updates['status_item'] = 'Fechando'

        supabase_db.execute_with_retry(self.itens_table.update(updates).eq('id', item_id))

        # DISPARAR EVENTO DE EXPEDIÇÃO (Event Sourcing)
        # O ConsolidadorDeEstoque processará assincronamente via Celery
        try:
            import uuid
            correlation_id = str(uuid.uuid4())
            
            # Registrar evento para expedição de capas
            try:
                supabase_db.table('eventos_producao_v2').insert({
                    'item_demanda_id': item_id,
                    'demanda_id': demanda_id,
                    'estagio': 'expedicao_capas_retiradas_qtd',
                    'quantidade_reportada': float(quantidade),
                    'tipo_evento': 'SINAL',
                    'processado': False,
                    'correlation_id': correlation_id,
                    'usuario_id': user_id if isinstance(user_id, int) else None,
                    'created_at': get_now_iso()
                }).execute()
            except Exception as event_error:
                # Erros do Realtime não devem interromper o fluxo principal
                error_str = str(event_error)
                if 'StreamID' in error_str or 'Realtime' in error_str:
                    print(f"AVISO: Erro do Realtime ao inserir evento de expedição de capas (não crítico): {event_error}")
                else:
                    raise event_error

            # Registrar evento para expedição de miolos
            try:
                supabase_db.table('eventos_producao_v2').insert({
                    'item_demanda_id': item_id,
                    'demanda_id': demanda_id,
                    'estagio': 'expedicao_miolos_retirados_qtd',
                    'quantidade_reportada': float(quantidade),
                    'tipo_evento': 'SINAL',
                    'processado': False,
                    'correlation_id': correlation_id,
                    'usuario_id': user_id if isinstance(user_id, int) else None,
                    'created_at': get_now_iso()
                }).execute()
            except Exception as event_error:
                # Erros do Realtime não devem interromper o fluxo principal
                error_str = str(event_error)
                if 'StreamID' in error_str or 'Realtime' in error_str:
                    print(f"AVISO: Erro do Realtime ao inserir evento de expedição de miolos (não crítico): {event_error}")
                else:
                    raise event_error
        except Exception as e:
            print(f"ERRO ao registrar evento de expedição do item {item_id}: {e}")

        # Verificar se a demanda deve ser finalizada automaticamente
        if updates.get('status_item') == 'Concluído':
            self._verificar_e_finalizar_demanda_automatica(demanda_id, user_id)

        # Registrar auditoria
        auditoria_service.log_event('RETIRADA_EXPEDICAO', {
            'demanda_id': demanda_id,
            'item_id': item_id,
            'sku': item.get('sku'),
            'quantidade': quantidade,
            'exp_capas_anterior': exp_capas_atual,
            'exp_capas_novo': nova_exp_capas,
            'exp_miolos_anterior': exp_miolos_atual,
            'exp_miolos_novo': nova_exp_miolos
        }, user_id)

        return self._process_item_dict({**item, **updates})


demanda_items_service = DemandaItemsService()
