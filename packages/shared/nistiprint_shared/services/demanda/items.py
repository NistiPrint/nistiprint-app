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


class DemandaItemsService:
    def __init__(self):
        self.demandas_table = supabase_db.table('demandas_producao')
        self.itens_table = supabase_db.table('itens_demanda')

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
        novo_valor = valor_atual + incremento

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
        novo_valor = valor_atual + incremento

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

    def atualizar_progresso_item(self, demanda_id, item_id, quantities_to_update, user_id='System'):
        """
        Atualiza o progresso de um item e dispara movimentações de estoque (Smart Delta).
        """
        response = supabase_db.execute_with_retry(self.itens_table.select("*").eq('id', item_id))
        if not response.data: raise ValueError(f"Item {item_id} não encontrado")

        item = response.data[0]
        produto_pai_id = item.get('produto_id')
        updates = {'updated_at': get_now_iso()}

        # 1. Processar Deltas e Movimentar Estoque (Híbrido)
        for key, new_value in quantities_to_update.items():
            if key not in item: continue

            old_value = float(item.get(key, 0) or 0)
            delta = float(new_value) - old_value

            if delta == 0: continue

            # Disparar a lógica de estoque híbrida para este campo
            # Usamos skip_visual_update=True pois faremos o bulk update no final
            try:
                self.processar_alocacao_de_demanda(
                    item_id=item_id,
                    campo=key,
                    incremento=delta,
                    user_id=user_id,
                    skip_visual_update=True
                )
            except Exception as e:
                print(f"Erro ao processar estoque para campo {key} no Smart Delta: {e}")

            # Aplica a atualização no DB da demanda
            updates[key] = float(new_value)

        # 2. Atualizar Status e Salvar
        total_qty = item['quantidade']
        exp_capas = updates.get('expedicao_capas_retiradas_qtd', item.get('expedicao_capas_retiradas_qtd', 0))
        exp_miolos = updates.get('expedicao_miolos_retirados_qtd', item.get('expedicao_miolos_retirados_qtd', 0))

        if exp_capas > 0 or exp_miolos > 0:
            updates['status_item'] = 'Em Andamento'

        # Fallback para triggers legadas
        updates['updated_at'] = get_now_iso()

        supabase_db.execute_with_retry(self.itens_table.update(updates).eq('id', item_id))

        # --- AUTOMATIZAÇÃO DE STATUS DA DEMANDA ---
        if updates.get('status_item') == 'Concluído':
            self._verificar_e_finalizar_demanda_automatica(demanda_id, user_id)
        # ------------------------------------------

        auditoria_service.log_event('SMART_DELTA_UPDATE', {
            'item_id': item_id,
            'quantities': quantities_to_update,
            'updates_made': updates
        }, user_id)

        return self._process_item_dict({**item, **updates})

    def _forcar_finalizacao_estoque_item(self, item_id, total_qty, user_id):
        """
        Garante que todas as etapas de produção do item sejam preenchidas e processadas
        pela lógica de alocação de estoque, garantindo integridade.
        """
        from ..config.production_stages import ESTAGIOS_PRODUCAO

        response = supabase_db.execute_with_retry(self.itens_table.select("*").eq('id', item_id))
        if not response.data: return
        item = response.data[0]

        # Ordem lógica de produção (idealmente do início para o fim)
        # 1. Impressão -> 2. Produção Capa -> 3. Retirada Capa -> 4. Retirada Miolo
        ordem_etapas = [
            'capas_impressas_qtd',
            'capas_produzidas_qtd',
            'capas_prontas_retirada_qtd',
            'miolos_prontos_retirada_qtd'
        ]

        for campo in ordem_etapas:
            if campo not in item: continue

            atual = float(item.get(campo, 0) or 0)
            delta = total_qty - atual

            if delta > 0:
                try:
                    # Usamos o processar_alocacao_de_demanda que já lida com
                    # recursividade de componentes e logs de produção diária.
                    self.processar_alocacao_de_demanda(item_id, campo, delta, user_id)
                except Exception as e:
                    print(f"Erro ao processar etapa {campo} na finalização forçada: {e}")

    def finalizar_item(self, demanda_id, item_id, user_id='System'):
        response = supabase_db.execute_with_retry(self.itens_table.select("*").eq('id', item_id))
        if not response.data:
            raise ValueError(f"Item {item_id} não encontrado")

        item_original = response.data[0]
        total_qty = item_original['quantidade']

        # 1. GATILHO DE EXPLOSÃO DE BOM CONSOLIDADA (ASYNC via Celery)
        # Este é o único momento onde o sistema calculará o consumo de todos os insumos (papel, wire-o, etc)
        # para a quantidade total finalizada do item.
        # O processamento será feito pelo worker Celery ou fallback síncrono se Celery falhar
        self.agendar_processamento_estoque(
            demanda_id=demanda_id,
            item_id=item_id,
            campo='ITEM_TOTAL_BOM_PROCESS',
            incremento=total_qty,
            user_id=user_id
        )

        # 2. VISIBILIDADE IMEDIATA: Atualizar todas as colunas no dashboard
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
        self._verificar_e_finalizar_demanda_automatica(demanda_id, user_id)

        return self._process_item_dict({**item_original, **updates})

    def finalizar_item_parcial(self, demanda_id, item_id, quantidade_parcial, user_id='System'):
        response = supabase_db.execute_with_retry(self.itens_table.select("*").eq('id', item_id))
        if not response.data:
            raise ValueError(f"Item {item_id} não encontrado")

        item_original = response.data[0]
        total_qty = item_original['quantidade']

        # 1. GATILHO DE EXPLOSÃO DE BOM PARCIAL (ASYNC via Celery)
        # O processamento será feito pelo worker Celery ou fallback síncrono se Celery falhar
        self.agendar_processamento_estoque(
            demanda_id=demanda_id,
            item_id=item_id,
            campo='ITEM_TOTAL_BOM_PROCESS',
            incremento=float(quantidade_parcial),
            user_id=user_id
        )

        # 2. VISIBILIDADE IMEDIATA (Atualização das colunas visuais)
        def get_new_val(field):
            curr = item_original.get(field, 0) or 0
            return min(total_qty, curr + quantidade_parcial)

        updates = {
            'capas_impressas_qtd': get_new_val('capas_impressas_qtd'),
            'capas_produzidas_qtd': get_new_val('capas_produzidas_qtd'),
            'capas_prontas_retirada_qtd': get_new_val('capas_prontas_retirada_qtd'),
            'miolos_prontos_retirada_qtd': get_new_val('miolos_prontos_retirada_qtd'),
            'expedicao_capas_retiradas_qtd': get_new_val('expedicao_capas_retiradas_qtd'),
            'expedicao_miolos_retirados_qtd': get_new_val('expedicao_miolos_retirados_qtd'),
            'finalizados_qtd': get_new_val('finalizados_qtd'),
            'updated_at': get_now_iso()
        }

        if updates.get('finalizados_qtd', 0) >= total_qty:
            updates['status_item'] = 'Concluído'
        else:
            updates['status_item'] = 'Em Andamento'

        supabase_db.execute_with_retry(self.itens_table.update(updates).eq('id', item_id))
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
            new_val = old_val + qty
            updates = {
                campo_a_atualizar: new_val,
                'updated_at': get_now_iso(),
                'status_item': 'Em Andamento'
            }

            # Se for saída final (Produto acabado ou kit), também sensibiliza a retirada do miolo
            if role == 'OUTRO':
                updates['expedicao_miolos_retirados_qtd'] = float(item.get('expedicao_miolos_retirados_qtd') or 0) + qty

            supabase_db.execute_with_retry(self.itens_table.update(updates).eq('id', item_id))

            # Automação de status: Apenas se for a saída final (Expedição)
            if role == 'OUTRO' and new_val >= float(item['quantidade']):
                # Verifica se todas as saídas finais (capa e miolo) foram atingidas
                exp_miolo = updates.get('expedicao_miolos_retirados_qtd') or item.get('expedicao_miolos_retirados_qtd', 0)
                if float(exp_miolo) >= float(item['quantidade']):
                    supabase_db.execute_with_retry(self.itens_table.update({'status_item': 'Concluído'}).eq('id', item_id))
                    self._verificar_e_finalizar_demanda_automatica(item['demanda_id'], user_id)

            auditoria_service.log_event('SAIDA_DISTRIBUIDA_ITEM', {
                'item_id': item_id,
                'product_id': product_id,
                'role': role,
                'quantidade': qty,
                'campo': campo_a_atualizar,
                'novo_valor': new_val
            }, user_id)

        return True


demanda_items_service = DemandaItemsService()
