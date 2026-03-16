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

class DemandaProducaoService:
    def __init__(self):
        self.demandas_table = supabase_db.table('demandas_producao')
        self.itens_table = supabase_db.table('itens_demanda')

    def _normalize_status(self, status: str) -> str:
        """Converte status legados para o novo padrão Upper Snake Case do banco de dados."""
        if not status: return 'AGUARDANDO'
        
        mapping = {
            'Pendente': 'AGUARDANDO',
            'Rascunho': 'AGUARDANDO',
            'Criada': 'AGUARDANDO',
            'Em Produção': 'EM_PRODUCAO',
            'Em Andamento': 'EM_PRODUCAO',
            'Coleta Parcial': 'COLETA_PARCIAL',
            'Coletado': 'COLETADO',
            'Finalizado': 'CONCLUIDO',
            'Concluído': 'CONCLUIDO',
            'Cancelado': 'CANCELADO'
        }
        
        # Se já estiver no mapeamento, retorna o novo. 
        # Caso contrário, tenta converter para UPPER_SNAKE_CASE ou mantém o original.
        return mapping.get(status, status.upper().replace(' ', '_'))
    
    def _process_demanda_dict(self, demanda: Dict[str, Any], itens: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Adiciona aliases e processa campos para o frontend, incluindo agregações de itens."""
        if not demanda: return None
        d = dict(demanda)
        d['nome'] = d.get('descricao')
        d['manual_priority_score'] = d.get('prioridade_manual', 0)

        if itens is not None:
            # Agregações para o DemandaCard
            d['total_itens'] = sum(i.get('quantidade', 0) for i in itens)
            d['total_quantidade'] = d['total_itens']
            
            # Itens finalizados (incluindo parcial) para lógica de status textual e progresso real
            # Este campo representa a finalização manual e explícita no dashboard (real time).
            d['itens_finalizados_total'] = sum(float(i.get('finalizados_qtd', 0)) for i in itens)

            # Aliase para o frontend (DemandaCard usa itens_fechados ou completed_quantidade para progresso)
            d['itens_finalizados'] = d['itens_finalizados_total']

            # Itens prontos (unidades completas: capa + miolo) - suporte para finalização parcial
            # REGRA: Um item está pronto para retirar quando a CAPA ESTÁ PRONTA (casada com pedido) E o MIOLO ESTÁ PRONTO.
            d['itens_prontos_total'] = sum(min(i.get('capas_prontas_retirada_qtd') or 0, i.get('miolos_prontos_retirada_qtd') or 0) for i in itens)
            # Aliase para o frontend usar o campo itens_concluidos como "unidades prontas"
            d['itens_concluidos'] = d['itens_prontos_total']

            d['capas_impressas_qtd'] = sum(i.get('capas_impressas_qtd', 0) for i in itens)
            d['capas_produzidas_qtd'] = sum(i.get('capas_produzidas_qtd', 0) for i in itens)
            d['capas_prontas_retirada_qtd'] = sum(i.get('capas_prontas_retirada_qtd', 0) for i in itens)
            d['miolos_produzidos_qtd'] = sum(i.get('miolos_prontos_retirada_qtd', 0) for i in itens)
            d['miolos_prontos_retirada_qtd'] = d['miolos_produzidos_qtd']

            # completed_quantidade agora representa o progresso de FINALIZAÇÃO MANUAL para o frontend
            d['completed_quantidade'] = d['itens_finalizados_total']

            # quantidade_coletada_total mantém o valor da tabela entrega_producao (coleta física/faturamento)
            d['quantidade_coletada_total'] = d.get('quantidade_coletada_total', 0)

            # Itens em fechamento: soma do menor valor entre exp. capas e exp. miolos de cada item
            # Representa itens que a expedição está processando em paralelo (READY TO CLOSE)
            d['itens_em_fechamento'] = sum(
                min(i.get('expedicao_capas_retiradas_qtd') or 0, i.get('expedicao_miolos_retirados_qtd') or 0)
                for i in itens
            )

            progresso = 0
            if d['total_itens'] > 0:
                # O progresso percentual da demanda agora é baseado na finalização manual dos itens
                progresso = round((d['itens_finalizados_total'] / d['total_itens']) * 100)
            d['progresso_percentual'] = progresso
            # Cálculo de Prontidão (Readiness Score)
            # Média ponderada de capas impressas e miolos entregues (etapas iniciais)
            if d['total_itens'] > 0:
                d['readiness_score'] = round(((d['capas_impressas_qtd'] + d['miolos_produzidos_qtd']) / (2 * d['total_itens'])) * 100)
            else:
                d['readiness_score'] = 0

            # Lógica para identificar se a demanda está 'travada'
            # Heurística: está em produção, mas o miolo ou capa não avançou para a próxima etapa (produção de capa)
            # Ou se capas impressas > capas produzidas e itens_concluidos está estagnado
            d['is_stuck'] = False
            if d['status'] == 'Em Produção' and d['total_itens'] > 0:
                # Se temos capas impressas mas não temos capas produzidas na mesma proporção (gap de material ou processo)
                gap_capas = d['capas_impressas_qtd'] - d['capas_produzidas_qtd']
                if gap_capas > (d['total_itens'] * 0.5) and d['itens_concluidos'] < (d['total_itens'] * 0.2):
                    d['is_stuck'] = True
            
            # Adiciona informações do miolo do primeiro item ao cabeçalho para facilitar exibição
            if itens:
                first_item = itens[0]
                d['id_produto_miolo'] = first_item.get('id_produto_miolo')
                d['produto_miolo_nome'] = first_item.get('produto_miolo_nome') or first_item.get('miolo_nome')
        
        # Extract empresa-specific fields from dados_adicionais if they exist
        if d.get('dados_adicionais'):
            dados_adicionais = d['dados_adicionais']
            if isinstance(dados_adicionais, dict):
                # Extract empresa fields from dados_adicionais
                empresa_fields = [
                    'empresa_cliente_nome', 'empresa_wire_o_cor', 'empresa_elastico_cor',
                    'empresa_interacao_status', 'empresa_pedido_plataforma_numero',
                    'empresa_responsavel_id', 'empresa_responsavel_nome'
                ]

                for field in empresa_fields:
                    if field in dados_adicionais:
                        d[field] = dados_adicionais[field]

            # Merge legado de dados_adicionais
            for k, v in dados_adicionais.items():
                if k not in d or d[k] is None:
                    d[k] = v
        return d

    def _enrich_demanda_with_collection_totals(self, demanda_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enriquece o dicionário da demanda com o somatório total de coletas da tabela entrega_producao.
        Agora a coleta é consolidada por demanda, não por item.
        """
        demanda_id = demanda_dict['id']
        try:
            res = supabase_db.execute_with_retry(
                supabase_db.table('entrega_producao')
                .select('quantidade')
                .eq('demanda_id', demanda_id)
            )
            total_coletado = sum(row['quantidade'] for row in res.data) if res.data else 0
            demanda_dict['quantidade_coletada_total'] = total_coletado
        except Exception as e:
            print(f"Erro ao buscar totais de coleta para demanda {demanda_id}: {e}")
            demanda_dict['quantidade_coletada_total'] = 0
            
        return demanda_dict

    def _enrich_items_with_stock(self, itens: List[Dict[str, Any]], deposito_id: Any = None) -> List[Dict[str, Any]]:
        """
        Adiciona informações de saldo de estoque (miolo e capas) aos itens em lote.
        """
        if not itens: return []
        
        # (A coleta real por item foi removida para suportar o modelo consolidado)

        # Se não for fornecido um depósito, obter o padrão para produção
        if deposito_id is None:
            from nistiprint_shared.services.app_config_service import app_config_service
            deposito_id = app_config_service.get_config('default_production_deposit_id')

        # 1. Coletar IDs de Miolos e Produtos Pais
        miolo_ids = []
        try:
            # Filtra apenas IDs válidos (não nulos e não vazios)
            raw_ids = [i.get('id_produto_miolo') for i in itens]
            miolo_ids = list(set([str(rid) for rid in raw_ids if rid]))
        except Exception as e:
            print(f"Erro ao extrair IDs de miolo: {e}")

        produto_pai_ids = []
        try:
            raw_pai_ids = [i.get('produto_id') for i in itens]
            produto_pai_ids = list(set([str(rid) for rid in raw_pai_ids if rid]))
        except:
            pass

        # 2. Buscar saldos de Miolos
        saldos_miolos = {}
        if miolo_ids:
            try:
                saldos_miolos = estoque_service.get_saldos_em_lote(miolo_ids, deposito_id)
            except Exception as e:
                print(f"Erro não fatal ao buscar estoque de miolos: {e}")
                system_log_service.log(
                    category='ESTOQUE',
                    message=f"Falha ao buscar estoque de miolos durante atualização da demanda: {str(e)}",
                    action='enrich_items_with_stock',
                    reference_id=str(deposito_id),
                    metadata={"miolo_ids": miolo_ids, "error": str(e)}
                )

        # 3. Para Capas, precisamos primeiro achar o ID do componente Capa na BOM de cada pai
        capa_ids_map = {} # produto_pai_id -> id_produto_capa
        impressao_ids_map = {} # produto_pai_id -> id_produto_impressao
        all_target_ids = []

        for p_id in produto_pai_ids:
            try:
                # Busca rápida na BOM
                comps = self.get_bom_components(p_id)
                for c in comps:
                    role = product_service.identify_product_role(str(c.componente_id))
                    if role == 'CAPA_ACABADA':
                        capa_ids_map[p_id] = str(c.componente_id)
                        all_target_ids.append(str(c.componente_id))
                    elif role == 'CAPA_IMPRESSAO':
                        impressao_ids_map[p_id] = str(c.componente_id)
                        all_target_ids.append(str(c.componente_id))
            except: continue

        saldos_extra = {}
        if all_target_ids:
            try:
                saldos_extra = estoque_service.get_saldos_em_lote(list(set(all_target_ids)), deposito_id)
            except Exception as e:
                print(f"Erro não fatal ao buscar estoque de capas: {e}")
                system_log_service.log(
                    category='ESTOQUE',
                    message=f"Falha ao buscar estoque de capas/impressão durante atualização da demanda: {str(e)}",
                    action='enrich_items_with_stock',
                    reference_id=str(deposito_id),
                    metadata={"target_ids": all_target_ids, "error": str(e)}
                )

        # 4. Injetar nos itens
        for item in itens:
            # Miolo
            m_id = str(item.get('id_produto_miolo'))
            item['estoque_disponivel_miolo'] = saldos_miolos.get(m_id, {}).get('quantidade_disponivel', 0) if m_id in saldos_miolos else 0

            # Capa e Impressão
            p_id = str(item.get('produto_id'))

            c_id = capa_ids_map.get(p_id)
            item['estoque_disponivel_capa'] = saldos_extra.get(c_id, {}).get('quantidade_disponivel', 0) if c_id else 0

            i_id = impressao_ids_map.get(p_id)
            item['estoque_disponivel_impressao'] = saldos_extra.get(i_id, {}).get('quantidade_disponivel', 0) if i_id else 0

        return itens

    def _process_item_dict(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Adiciona aliases e processa campos para o frontend."""
        if not item: return None
        i = dict(item)
        i['item_descricao'] = i.get('descricao')
        i['quantidade_total'] = i.get('quantidade')
        i['miolo_name'] = i.get('miolo_nome')
        
        # Garante que o nome do miolo esteja disponível se tiver o id
        if i.get('id_produto_miolo') and not i.get('miolo_nome'):
            try:
                p = product_service.get_by_id(str(i['id_produto_miolo']))
                if p:
                    i['miolo_nome'] = p.get('nome')
                    i['miolo_name'] = p.get('nome')
            except: pass

        # Merge legado de dados_adicionais
        if i.get('dados_adicionais'):
            for k, v in i['dados_adicionais'].items():
                if k not in i or i[k] is None:
                    i[k] = v
        return i

    def _get_aggregated_demandas(self, response_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not response_data: return []
        
        demanda_ids = [row['id'] for row in response_data]
        # Busca itens para todas as demandas da página de uma vez
        itens_res = supabase_db.execute_with_retry(self.itens_table.select("*").in_('demanda_id', demanda_ids))
        
        # Agrupa itens por demanda_id
        itens_by_demanda = {}
        for item in itens_res.data:
            did = item['demanda_id']
            if did not in itens_by_demanda: itens_by_demanda[did] = []
            itens_by_demanda[did].append(item)
            
        # Buscar totais de coleta para todas as demandas de uma vez
        coletas_res = supabase_db.execute_with_retry(
            supabase_db.table('entrega_producao')
            .select('demanda_id, quantidade')
            .in_('demanda_id', demanda_ids)
        )
        coleta_totals_map = {}
        for row in coletas_res.data:
            did = row['demanda_id']
            coleta_totals_map[did] = coleta_totals_map.get(did, 0) + row['quantidade']

        result = []
        for row in response_data:
            canal_nome = row.get('canal_venda', {}).get('nome') if row.get('canal_venda') else None
            canal_color = row.get('canal_venda', {}).get('color') if row.get('canal_venda') else None
            canal_plataforma = row.get('canal_venda', {}).get('plataformas', {}).get('nome') if row.get('canal_venda') else None
            
            # Injetar o total coletado na row antes de processar
            row['quantidade_coletada_total'] = coleta_totals_map.get(row['id'], 0)

            processed = self._process_demanda_dict(
                {
                    **row, 
                    'canal_venda_nome': canal_nome, 
                    'canal_venda_color': canal_color,
                    'canal_venda_plataforma': canal_plataforma
                }, 
                itens_by_demanda.get(row['id'], [])
            )
            result.append(processed)
        return result

    def get_all_demandas(self) -> List[Dict[str, Any]]:
        response = supabase_db.execute_with_retry(
            self.demandas_table.select("*, canal_venda:canais_venda(nome, color, plataformas(nome))").order('created_at', desc=True)
        )
        return self._get_aggregated_demandas(response.data)

    def get_demandas_by_ids(self, demanda_ids: List[str]) -> List[Dict[str, Any]]:
        """Busca múltiplas demandas em lote."""
        if not demanda_ids: return []
        response = supabase_db.execute_with_retry(
            self.demandas_table.select("*, canal_venda:canais_venda(nome, color, plataformas(nome))").in_('id', demanda_ids)
        )
        return self._get_aggregated_demandas(response.data)

    def get_items_for_multiple_demandas(self, demanda_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Busca itens de múltiplas demandas em uma única chamada e retorna mapeado por demanda_id."""
        if not demanda_ids: return {}
        response = supabase_db.execute_with_retry(
            self.itens_table.select("*").in_('demanda_id', demanda_ids)
        )
        
        mapping = {}
        for item in response.data:
            did = str(item['demanda_id'])
            if did not in mapping: mapping[did] = []
            mapping[did].append(self._process_item_dict(item))
        return mapping

    def get_demanda_with_itens(self, demanda_id: str) -> Dict[str, Any]:
        # Tenta buscar pelo ID (PK)
        response = supabase_db.execute_with_retry(self.demandas_table.select("*, canal_venda:canais_venda(nome, color, plataformas(nome))").eq('id', demanda_id))
        if not response.data:
            response = supabase_db.execute_with_retry(self.demandas_table.select("*, canal_venda:canais_venda(nome, color, plataformas(nome))").eq('demanda_id', demanda_id))
            if not response.data:
                return None
        
        raw_demanda = response.data[0]
        internal_id = raw_demanda['id']
        itens_response = supabase_db.execute_with_retry(self.itens_table.select("*").eq('demanda_id', internal_id).order('id'))
        
        # Obter o depósito padrão para produção
        from nistiprint_shared.services.app_config_service import app_config_service
        deposito_id = app_config_service.get_config('default_production_deposit_id')

        # Enriquecer itens com dados de estoque (Smart Delta Support)
        processed_itens = [self._process_item_dict(item) for item in itens_response.data]
        processed_itens = self._enrich_items_with_stock(processed_itens, deposito_id)
        
        # Enriquecer cabeçalho da demanda com totais de coleta
        raw_demanda = self._enrich_demanda_with_collection_totals(raw_demanda)
        
        canal_venda = raw_demanda.get('canal_venda') or {}
        plataforma = canal_venda.get('plataformas') or {}

        demanda = self._process_demanda_dict(
            {
                **raw_demanda, 
                'canal_venda_nome': canal_venda.get('nome'),
                'canal_venda_color': canal_venda.get('color'),
                'canal_venda_plataforma': plataforma.get('nome')
            }, 
            processed_itens
        )
        demanda['itens'] = processed_itens
        
        return demanda

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

    def create_from_order(self, order_data: Dict[str, Any], user_id='System') -> Dict[str, Any]:
        # Determine Platform and ID based on payload
        # Priority: order_sn (Shopee), order_id (ML), numeroLoja (Bling)
        plataforma = order_data.get('plataforma', 'Bling')
        
        external_id = None
        if 'order_sn' in order_data:
            external_id = str(order_data['order_sn'])
            if 'plataforma' not in order_data: plataforma = 'Shopee'
        elif 'order_id' in order_data:
            external_id = str(order_data['order_id'])
            if 'plataforma' not in order_data: plataforma = 'MercadoLivre'
        elif 'AmazonOrderId' in order_data:
            external_id = str(order_data['AmazonOrderId'])
            if 'plataforma' not in order_data: plataforma = 'Amazon'
        else:
            # Fallback to Bling standard
            external_id = str(order_data.get('numeroLoja') or order_data.get('numero'))

        if not external_id:
            raise ValueError("Pedido sem número identificador (numeroLoja, order_sn, etc)")

        # Prepare list for deduplication check
        items_for_check = []
        for item in order_data.get('itens', []):
            qty = int(float(item.get('quantidade', 1)))
            sku = str(item.get('codigo') or item.get('sku') or '')
            # Try to get specific item ID if available (e.g. from Shopee line item id)
            item_ext_id = str(item.get('id') or item.get('order_item_id') or sku)
            
            items_for_check.append({
                'sku_externo': sku,
                'item_externo_id': item_ext_id,
                'quantidade': qty
            })

        orders_list = [{
            'pedido_externo_id': external_id,
            'items': items_for_check,
            'plataforma': plataforma
        }]

        # 1. Filter Deduplication
        filtered_orders = order_tracker_service.filter_processed_items(orders_list, plataforma)
        if not filtered_orders:
            # All items processed
            existing = self.demandas_table.select("id").eq('demanda_id', external_id).execute()
            if existing.data:
                return self.get_demanda_with_itens(existing.data[0]['id'])
            # If no demand exists but items are processed, maybe they were processed in a consolidated batch?
            # Return None to indicate no *new* demand created.
            return None

        # 2. Process Remaining Items
        # We take the first order from filtered list (since we passed only one)
        remaining_items = filtered_orders[0]['items']
        
        # Prepare content for new demand
        contato_nome = order_data.get('contato', {}).get('nome', 'Cliente Desconhecido')
        nome_demanda = f"Pedido {order_data.get('numero') or external_id} - {contato_nome}"
        
        data_entrega = order_data.get('dataPrevista') or order_data.get('data') or get_now().strftime('%Y-%m-%d')
        if isinstance(data_entrega, str) and 'T' in data_entrega:
            data_entrega = data_entrega.split('T')[0]

        itens_demanda = []
        
        # We iterate over original items to preserve metadata (desc), but check against remaining
        # OR just use remaining items if we carried enough metadata.
        # Since 'items_for_check' was lightweight, we should match back to full 'order_data' items
        # or simply rely on the fact that if it's in 'remaining', we process it.
        # But 'remaining' lacks description if we didn't put it in 'items_for_check'.
        
        # Better approach: map remaining item keys to allow lookup
        remaining_map = {(i['sku_externo'], i['item_externo_id']): i['quantidade'] for i in remaining_items}
        
        for item in order_data.get('itens', []):
            sku = str(item.get('codigo') or item.get('sku') or '')
            item_ext_id = str(item.get('id') or item.get('order_item_id') or sku)
            
            key = (sku, item_ext_id)
            if key in remaining_map:
                qty_to_process = remaining_map[key]
                
                # Resolve Variation
                nome_externo = item.get('descricao') or item.get('name')
                resolved_prod = product_service.resolve_variation(sku, plataforma, nome_externo)
                
                prod_id = resolved_prod['id'] if resolved_prod else None
                
                itens_demanda.append({
                    'sku': sku,
                    'descricao': nome_externo,
                    'quantidade': qty_to_process,
                    'produto_id': prod_id,
                    # Pass external ID to persist in tracking later
                    '_item_externo_id': item_ext_id 
                })

        if not itens_demanda:
            return None

        observacoes = f"Importado automaticamente. ID Externo: {external_id}"
        if 'observacoes' in order_data:
             observacoes += f"\nObs Pedido: {order_data['observacoes']}"

        # --- NOVO: BUSCAR PEDIDO_ID UNIFICADO ---
        pedido_id_vincular = None
        try:
            # Tenta achar o pedido centralizado pelo codigo_pedido_externo
            # external_id aqui é o numeroLoja/order_sn/etc
            pedido_res = supabase_db.table('pedidos')\
                .select('id')\
                .eq('codigo_pedido_externo', str(external_id))\
                .execute()
            
            if pedido_res.data:
                pedido_id_vincular = pedido_res.data[0]['id']
        except Exception as find_err:
            print(f"Erro ao buscar pedido unificado para vínculo: {find_err}")
        # ----------------------------------------

        # 3. Create Demand
        new_demanda = self.criar_demanda_direta(
            nome_demanda=nome_demanda,
            canal_venda_id=None,
            data_entrega_str=data_entrega,
            lista_de_itens=itens_demanda,
            demanda_id=external_id, 
            pedido_numero=str(order_data.get('numero') or external_id),
            pedido_id=pedido_id_vincular, # Passando o ID unificado
            observacoes=observacoes,
            user_id=user_id,
            tipo_demanda='PLATAFORMA'
        )

        # 4. Register Processed Items
        # Reconstruct orders_list with the items we actually processed (itens_demanda)
        # to ensure tracker is accurate on what was done.
        
        items_processed_for_tracker = []
        for iditem in itens_demanda:
            items_processed_for_tracker.append({
                'sku_externo': iditem['sku'],
                'item_externo_id': iditem.get('_item_externo_id'),
                'quantidade': iditem['quantidade'],
                'produto_id': iditem['produto_id']
            })
            
        final_orders_list = [{
            'pedido_externo_id': external_id,
            'plataforma': plataforma,
            'items': items_processed_for_tracker
        }]
        
        if new_demanda:
            order_tracker_service.register_processed_items(new_demanda['id'], final_orders_list, plataforma)

        return new_demanda

    def criar_demanda_direta(self, nome_demanda, canal_venda_id, data_entrega_str, lista_de_itens,
                             horario_coleta_especifico=None, data_finalizacao_prevista=None,
                             observacoes=None, user_id='System', tipo_demanda='PLATAFORMA',
                             status='EM_PRODUCAO', pedido_id=None, **kwargs) -> Dict[str, Any]:
        # ... (uuid logic remains)
        provided_id = kwargs.pop('demanda_id', None)

        if provided_id:
            # Check existence
            exists = supabase_db.execute_with_retry(self.demandas_table.select("id").eq('demanda_id', provided_id))
            if exists.data:
                # Collision. Append suffix.
                provided_id = f"{provided_id}_{int(get_now().timestamp())}"
        else:
            provided_id = str(uuid.uuid4())

        # Normalizar status
        status = self._normalize_status(status)

        # Determinar os valores para os novos campos com base nos antigos (Backward Compatibility)
        # ...
        is_flex = kwargs.pop('is_flex', False)
        fulfillment = kwargs.pop('fulfillment', False)

        # Mapeamento default para modalidade_logistica se não vier explícito
        if not kwargs.get('modalidade_logistica'):
            if is_flex:
                modalidade_logistica = 'EXPRESS'
            elif fulfillment:
                modalidade_logistica = 'FULFILLMENT'
            else:
                modalidade_logistica = 'STANDARD'
        else:
            modalidade_logistica = kwargs.pop('modalidade_logistica')

        # Mapeamento default para classificacao_cliente se não vier explícito
        if not kwargs.get('classificacao_cliente'):
            if tipo_demanda == 'B2B':
                classificacao_cliente = 'B2B'
            elif tipo_demanda == 'ESTOQUE_INTERNO':
                classificacao_cliente = 'INTERNO'
            else:
                classificacao_cliente = 'B2C'
        else:
            classificacao_cliente = kwargs.pop('classificacao_cliente')

        # Adicionar data_finalizacao_prevista aos dados_adicionais se fornecido
        if data_finalizacao_prevista:
            kwargs['data_finalizacao_prevista'] = data_finalizacao_prevista.isoformat() if hasattr(data_finalizacao_prevista, 'isoformat') else data_finalizacao_prevista

        demanda_payload = {
            'demanda_id': provided_id,
            'descricao': nome_demanda,
            'data_entrega': data_entrega_str,
            'status': status,
            'canal_venda_id': canal_venda_id,
            'horario_coleta': horario_coleta_especifico,
            'tipo_demanda': tipo_demanda,
            'observacoes': observacoes,
            'pedido_id': pedido_id,
            'prioridade_manual': kwargs.pop('manual_priority_score', 0),
            'pedido_numero': kwargs.pop('pedido_numero', None),
            'is_flex': is_flex or modalidade_logistica == 'EXPRESS',
            'fulfillment': fulfillment or modalidade_logistica == 'FULFILLMENT',
            'modalidade_logistica': modalidade_logistica,
            'classificacao_cliente': classificacao_cliente,
            'dados_adicionais': kwargs,
            'created_at': get_now_iso(),
            'updated_at': get_now_iso()
        }
        response = supabase_db.execute_with_retry(self.demandas_table.insert(demanda_payload))
        if not response.data: raise Exception("Falha ao inserir cabeçalho da demanda")
        
        new_demanda_id = response.data[0]['id']

        itens_payload = []
        for item in lista_de_itens:
            # Resolve miolo se necessário
            item = self._resolve_miolo_for_item(item)
            
            # Adicionando logs para debugar a associação de miolos
            import logging
            logging.info(f'[DEBUG MIOLO BACKEND] Processando item: {item}')
            logging.info(f'[DEBUG MIOLO BACKEND] Produto ID: {item.get("produto_id")}, Miolo Nome: {item.get("miolo_name") or item.get("miolo_nome")}, ID Produto Miolo: {item.get("id_produto_miolo")}')

            itens_payload.append({
                'demanda_id': new_demanda_id,
                'produto_id': item.get('produto_id'),
                'sku': item.get('sku'),
                'descricao': item.get('descricao', 'Item sem descrição'),
                'quantidade': int(item.get('quantidade', 1)),
                'capas_impressas_qtd': item.get('capas_impressas_qtd', 0),
                'capas_produzidas_qtd': item.get('capas_produzidas_qtd', 0),
                'capas_prontas_retirada_qtd': item.get('capas_prontas_retirada_qtd', 0),
                'miolos_prontos_retirada_qtd': item.get('miolos_prontos_retirada_qtd', 0),
                'expedicao_capas_retiradas_qtd': item.get('expedicao_capas_retiradas_qtd', 0),
                'expedicao_miolos_retirados_qtd': item.get('expedicao_miolos_retirados_qtd', 0),
                'status_item': item.get('status_item', 'Pendente'),
                'miolo_nome': item.get('miolo_name') or item.get('miolo_nome'),
                'id_produto_miolo': item.get('id_produto_miolo'),
                'variacao': item.get('variacao') or item.get('item_variacao'),
                'created_at': get_now_iso(),
                'updated_at': get_now_iso()
            })

        if itens_payload:
            res_itens = supabase_db.execute_with_retry(self.itens_table.insert(itens_payload))
            if res_itens.data:
                # Map inserted item IDs back to the original item data to handle order_refs
                inserted_items = res_itens.data
                
                # --- NOVO: REGISTRO DE ORIGEM DOS PEDIDOS ---
                all_order_registrations = []
                plataforma = kwargs.get('plataforma') or 'Desconhecida'
                
                for i, item_data in enumerate(lista_de_itens):
                    order_refs = item_data.get('order_refs')
                    if order_refs and i < len(inserted_items):
                        inserted_item_id = inserted_items[i]['id']
                        sku_externo = item_data.get('sku')
                        
                        # order_refs is a list of external order IDs
                        for ext_order_id in order_refs:
                            all_order_registrations.append({
                                'pedido_externo_id': ext_order_id,
                                'items': [{
                                    'sku_externo': sku_externo,
                                    'quantidade': 1, # Na consolidação, tratamos como 1 atendimento por ref na lista? 
                                    # Se a lista tiver duplicatas, somamos.
                                    'produto_id': item_data.get('produto_id')
                                }]
                            })
                
                if all_order_registrations:
                    try:
                        order_tracker_service.register_processed_items(new_demanda_id, all_order_registrations, plataforma)
                    except Exception as e:
                        logging.error(f"Erro ao registrar origens dos pedidos para demanda {new_demanda_id}: {e}")
                # --------------------------------------------

            # --- INTEGRAÇÃO COM ESTOQUE (RESERVAS EM CASCATA & PREVISÃO) ---
            try:
                # 1. Gerar a Previsão de Consumo na nova tabela dedicada
                previsao_consumo_service.gerar_previsao_para_demanda(new_demanda_id, itens_payload)

                # 2. Gera o snapshot de consumo legado e efetiva as reservas (Waterfall)
                snapshot_consumo = self._processar_reserva_inteligente_demanda(new_demanda_id, itens_payload, user_id)
                
                # Atualiza a demanda com o snapshot para consulta futura
                self.update_demanda_details(new_demanda_id, {
                    'dados_adicionais': {'snapshot_consumo_previsto': snapshot_consumo}
                }, user_id)
                
            except Exception as e:
                print(f"Erro ao processar reserva inteligente para demanda {new_demanda_id}: {e}")
                # Fallback: Se falhar a cascata, tenta reserva simples para não deixar sem nada
                try:
                    itens_reserva = [{'produto_id': i['produto_id'], 'quantidade': i['quantidade']} for i in itens_payload if i.get('produto_id')]
                    estoque_service.reservar_estoque_em_lote(itens_reserva, allow_backorder=True)
                except: pass
            # --------------------------------------------------

        auditoria_service.log_event('DEMANDA_CRIADA', {'demanda_id': new_demanda_id}, user_id)
        return self.get_demanda_with_itens(new_demanda_id)

    def _processar_reserva_inteligente_demanda(self, demanda_id, itens_payload, user_id):
        """
        Calcula e executa a reserva de estoque seguindo lógica Waterfall:
        1. Tenta reservar produto acabado.
        2. Se faltar, explode BOM e reserva componentes.
        3. Retorna um snapshot detalhado do que foi planejado.
        """
        from nistiprint_shared.services.app_config_service import app_config_service
        deposito_id = app_config_service.get_config('default_production_deposit_id')
        
        snapshot = {
            'calculado_em': get_now_iso(),
            'demanda_id': demanda_id,
            'itens': []
        }

        # Cache local para evitar múltiplas chamadas de saldo/BOM no loop
        # (Otimização para demandas grandes)
        # Nota: Idealmente seria passado como argumento para a recursão
        
        for item in itens_payload:
            produto_id = item.get('produto_id')
            if not produto_id: continue
            
            qtd_necessaria = float(item.get('quantidade', 0))
            
            # Estrutura do item no snapshot
            item_report = {
                'item_id': item.get('id'), # Pode ser None se ainda não commitou, mas itens_payload veio do insert
                'produto_id': produto_id,
                'sku': item.get('sku'),
                'qtd_necessaria': qtd_necessaria,
                'reservas_realizadas': [] # Lista de {produto_id, qtd, tipo: 'PAI'|'COMPONENTE'}
            }
            
            # Inicia recursão
            self._reservar_recursivo(
                produto_id=int(produto_id),
                quantidade=qtd_necessaria,
                deposito_id=deposito_id,
                report_list=item_report['reservas_realizadas'],
                nivel=0
            )
            
            snapshot['itens'].append(item_report)
            
        return snapshot

    def _reservar_recursivo(self, produto_id, quantidade, deposito_id, report_list, nivel=0):
        """
        Motor recursivo de reserva.
        """
        # 1. Verificar Saldo Disponível do Produto Atual
        # TODO: Otimizar get_saldo_atual para cache se necessário
        saldo_info = estoque_service.get_saldo_atual(produto_id, deposito_id)
        disponivel = float(saldo_info.get('quantidade_disponivel', 0))
        
        # 2. Tentar reservar do próprio produto (Estoque Acabado ou Componente Puro)
        # Se for nível 0 (Produto Final), queremos consumir o que tiver pronto.
        # Se for nível > 0 (Componente), queremos consumir o que tiver.
        qtd_reservar = min(max(0, disponivel), quantidade)
        
        if qtd_reservar > 0:
            estoque_service.reservar_estoque(produto_id, qtd_reservar, deposito_id)
            report_list.append({
                'produto_id': produto_id,
                'quantidade': qtd_reservar,
                'tipo': 'ESTOQUE_EXISTENTE',
                'nivel': nivel
            })
            
        # 3. Calcular Falta
        falta = quantidade - qtd_reservar
        
        if falta > 0:
            # Precisa produzir ou comprar. Verifica BOM.
            bom = bom_service.get_bom_for_produto(produto_id)
            
            if not bom:
                # Não tem BOM (é matéria prima ou produto sem ficha).
                # Reserva a falta gerando Backorder (Risco de Ruptura)
                estoque_service.reservar_estoque(produto_id, falta, deposito_id, allow_backorder=True)
                report_list.append({
                    'produto_id': produto_id,
                    'quantidade': falta,
                    'tipo': 'BACKORDER' if nivel > 0 else 'A_PRODUZIR_SEM_BOM', # Se for pai, é "A Produzir", se for filho, é falta de insumo
                    'nivel': nivel
                })
            else:
                # Tem BOM (é produzível). Explode e desce o nível.
                # Não reservamos o pai "em backorder" aqui, pois a reserva será feita nos filhos.
                # Apenas registramos no report que será produzido.
                report_list.append({
                    'produto_id': produto_id,
                    'quantidade': falta,
                    'tipo': 'A_PRODUZIR', # Indica que esta qtd será gerada por produção
                    'nivel': nivel
                })
                
                for comp in bom:
                    qtd_comp_necessaria = falta * float(comp.quantidade)
                    self._reservar_recursivo(
                        produto_id=comp.componente_id,
                        quantidade=qtd_comp_necessaria,
                        deposito_id=deposito_id,
                        report_list=report_list,
                        nivel=nivel + 1
                    )

    def criar_demanda_empresas(self, nome_demanda, canal_venda_id, data_entrega_str, lista_de_itens,
                             horario_coleta_especifico=None, data_finalizacao_prevista=None,
                             observacoes=None, user_id='System', tipo_demanda='B2B',
                             status='Em Produção', **kwargs) -> Dict[str, Any]:
        
        # Garante a classificação como B2B e modalidade padrão se não informadas
        if 'classificacao_cliente' not in kwargs:
            kwargs['classificacao_cliente'] = 'B2B'
        if 'modalidade_logistica' not in kwargs:
            kwargs['modalidade_logistica'] = 'STANDARD'

        return self.criar_demanda_direta(
            nome_demanda=nome_demanda,
            canal_venda_id=canal_venda_id,
            data_entrega_str=data_entrega_str,
            lista_de_itens=lista_de_itens,
            horario_coleta_especifico=horario_coleta_especifico,
            data_finalizacao_prevista=data_finalizacao_prevista,
            observacoes=observacoes,
            user_id=user_id,
            tipo_demanda=tipo_demanda,
            status=status,
            **kwargs
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

    # ========================================================================
    # CONTROLE DE ALOCAÇÕES DE ESTOQUE POR DEMANDA
    # ========================================================================
    
    def _registrar_alocacao_estoque(
        self,
        demanda_id: str,
        item_id: str,
        produto_id: str,
        correlation_id: str,
        quantidade: float,
        tipo_alocacao: str,
        processo_origem: str,
        metadata: dict = None
    ):
        """
        Registra alocação de estoque na tabela demanda_alocacoes_estoque.
        Usado para controle de idempotência e cálculo de delta na finalização.
        
        NOTA: demanda_id, item_id, produto_id podem ser UUIDs ou IDs numéricos (int).
        A tabela foi criada com UUID, mas Postgres faz cast automático de int para UUID
        se o formato for válido. Para IDs numéricos, armazenamos como string mesmo.
        """
        import uuid as uuid_lib
        
        print(f"DEBUG [_registrar_alocacao_estoque] INICIO: item={item_id}, produto={produto_id}, qtd={quantidade}, tipo={tipo_alocacao}")
        try:
            # Verificar se já existe (idempotência)
            existing = supabase_db.table('demanda_alocacoes_estoque')\
                .select('id', 'status')\
                .eq('correlation_id', correlation_id)\
                .neq('status', 'CANCELADA')\
                .execute()

            if existing.data:
                print(f"DEBUG [_registrar_alocacao_estoque] Alocação {correlation_id} já existe, ignorando registro duplicado")
                return existing.data[0]

            # Manter IDs originais como string (funciona com UUID ou int)
            # O Postgres faz cast quando necessário
            demanda_uuid = str(demanda_id)
            item_uuid = str(item_id)
            produto_uuid = str(produto_id)

            payload = {
                'demanda_id': demanda_uuid,
                'item_id': item_uuid,
                'produto_id': produto_uuid,
                'correlation_id': correlation_id,
                'quantidade_alocada': float(quantidade),
                'tipo_alocacao': tipo_alocacao,
                'processo_origem': processo_origem,
                'status': 'PENDENTE',
                'metadata': metadata or {}
            }

            print(f"DEBUG [_registrar_alocacao_estoque] Insert payload: {payload}")
            result = supabase_db.table('demanda_alocacoes_estoque').insert(payload).execute()
            print(f"DEBUG [_registrar_alocacao_estoque] Result: {result.data is not None}")
            return result.data[0] if result.data else None

        except Exception as e:
            print(f"ERRO [_registrar_alocacao_estoque] {correlation_id}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _marcar_alocacao_processada(self, correlation_id: str):
        """Marca alocação como processada após consumo de estoque realizado."""
        try:
            supabase_db.table('demanda_alocacoes_estoque')\
                .update({'status': 'PROCESSADA', 'processed_at': get_now_iso()})\
                .eq('correlation_id', correlation_id)\
                .execute()
        except Exception as e:
            print(f"ERRO ao marcar alocação {correlation_id} como processada: {e}")
    
    def _marcar_alocacao_cancelada(self, correlation_id: str, motivo: str = None):
        """Cancela alocação (ex: em caso de estorno)."""
        try:
            metadata_update = {'motivo_cancelamento': motivo} if motivo else {}
            supabase_db.table('demanda_alocacoes_estoque')\
                .update({
                    'status': 'CANCELADA',
                    'cancelled_at': get_now_iso(),
                    'metadata': supabase_db.table('demanda_alocacoes_estoque')\
                        .select('metadata')\
                        .eq('correlation_id', correlation_id)\
                        .execute().data[0].get('metadata', {}) | metadata_update if supabase_db.table('demanda_alocacoes_estoque').select('metadata').eq('correlation_id', correlation_id).execute().data else metadata_update
                })\
                .eq('correlation_id', correlation_id)\
                .execute()
        except Exception as e:
            print(f"ERRO ao cancelar alocação {correlation_id}: {e}")
    
    def _buscar_alocacoes_por_item(self, item_id: str, produto_id: str = None) -> List[Dict[str, Any]]:
        """Busca todas as alocações ativas (não canceladas) para um item."""
        try:
            # Buscar todas alocações não canceladas e filtrar manualmente
            # Isso evita problemas de comparação entre string e UUID
            result = supabase_db.table('demanda_alocacoes_estoque')\
                .select('*')\
                .neq('status', 'CANCELADA')\
                .execute()
            
            if not result.data:
                return []
            
            # Filtrar manualmente por item_id e produto_id (comparação flexível)
            alocacoes_filtradas = []
            for aloc in result.data:
                # Comparar como string para funcionar com UUID ou int
                if str(aloc.get('item_id')) == str(item_id):
                    if produto_id is None or str(aloc.get('produto_id')) == str(produto_id):
                        alocacoes_filtradas.append(aloc)
            
            print(f"DEBUG [_buscar_alocacoes_por_item] item={item_id}, prod={produto_id}, encontradas={len(alocacoes_filtradas)}")
            return alocacoes_filtradas
            
        except Exception as e:
            print(f"ERRO ao buscar alocações para item {item_id}: {e}")
            return []
    
    def _calcular_total_alocado(self, item_id: str, produto_id: str) -> float:
        """Calcula total já alocado para um item+produto (soma de todas alocações ativas)."""
        try:
            # Buscar alocações manualmente (sem RPC)
            alocacoes = self._buscar_alocacoes_por_item(item_id, produto_id)
            total = sum(float(a.get('quantidade_alocada', 0)) for a in alocacoes)
            print(f"DEBUG [_calcular_total_alocado] item={item_id}, prod={produto_id}, total={total} ({len(alocacoes)} alocações)")
            for aloc in alocacoes[:5]:
                print(f"  - {aloc.get('quantidade_alocada')} ({aloc.get('tipo_alocacao')}, status={aloc.get('status')})")
            return total
        except Exception as e:
            print(f"ERRO ao calcular total alocado: {e}")
            return 0.0

    def _calcular_saldo_a_processar(self, item_id: str, produto_id: str, quantidade_necessaria: float) -> float:
        """
        Calcula quanto ainda precisa ser processado (diferença entre necessário e já alocado).
        Retorna 0 se tudo já foi alocado.
        
        NOTA: item_id e produto_id podem ser UUIDs ou IDs numéricos.
        """
        try:
            # Usar busca direta com IDs originais (string)
            # Evita RPC que espera UUIDs
            print(f"DEBUG [_calcular_saldo_a_processar] item={item_id}, produto={produto_id}, necessario={quantidade_necessaria}")
            total_alocado = self._calcular_total_alocado(item_id, produto_id)
            saldo = float(quantidade_necessaria) - total_alocado
            print(f"DEBUG [_calcular_saldo_a_processar] alocado={total_alocado}, saldo={saldo}")
            return max(saldo, 0.0)
        except Exception as e:
            print(f"ERRO [_calcular_saldo_a_processar]: {e}")
            import traceback
            traceback.print_exc()
            # Em caso de erro, retorna quantidade completa para não bloquear processamento
            return float(quantidade_necessaria)

    def _verificar_alocacao_existente(self, correlation_id: str) -> bool:
        """Verifica se alocação com correlation_id já existe (para idempotência)."""
        try:
            result = supabase_db.rpc('verificar_alocacao_existente', {
                'p_correlation_id': str(correlation_id)  # TEXT é compatível com string
            }).execute()

            if result.data is not None:
                return bool(result.data)

            # Fallback
            existing = supabase_db.table('demanda_alocacoes_estoque')\
                .select('id')\
                .eq('correlation_id', correlation_id)\
                .neq('status', 'CANCELADA')\
                .limit(1)\
                .execute()
            return len(existing.data) > 0
        except Exception as e:
            print(f"ERRO ao verificar alocação {correlation_id}: {e}")
            return False


    def processar_alocacao_de_demanda(self, item_id: str, campo: str, incremento: float, user_id: str, skip_visual_update: bool = False, origem_tipo: Optional[int] = None, retroactive_date: Optional[str] = None, correlation_id: Optional[str] = None):
        """
        Processa a alocação de estoque com base no estágio de produção.
        Implementa o cenário misto: uso de estoque existente + produção JIT.
        Suporta data retroativa e Correlation ID para rastreabilidade.
        """
        from nistiprint_shared.config.production_stages import ESTAGIOS_PRODUCAO
        from nistiprint_shared.services.unit_of_work import UnitOfWork
        from nistiprint_shared.services.bom_service import bom_service
        from nistiprint_shared.services.app_config_service import app_config_service

        # --- GESTÃO DE CORRELAÇÃO E DATA ---
        cid = correlation_id or f"DASH-{uuid.uuid4().hex[:8]}"
        mov_date = retroactive_date or get_now_iso()
        # -----------------------------------

        # Validação básica de entrada para evitar erros de SQL
        if not item_id or item_id == 'None':
            raise ValueError(f"ID do item inválido para processamento de estoque: {item_id}")

        # ETAPA 1: VALIDAÇÃO E IDENTIFICAÇÃO
        if campo not in ESTAGIOS_PRODUCAO:
            # Se o campo (ex: 'expedicao_capas_retiradas_qtd') não é um estágio de produção,
            # ele apenas registra o avanço visualmente, sem movimentar estoque de componentes.
            progresso_result = None
            if not skip_visual_update:
                progresso_result = self._atualizar_progresso_simples(item_id, campo, incremento)
            
            # Registro de log diário para progresso visual (Expedição, etc)
            try:
                item_demanda = self.get_item_by_id(item_id)
                daily_production_log_service.create_log(
                    log_date=datetime.fromisoformat(mov_date[:10]).date() if mov_date else datetime.now().date(),
                    product_id=str(item_demanda.get('produto_id')),
                    product_name="Progresso Visual",
                    quantity=incremento,
                    production_order_id=None,
                    component_stock_snapshot=[],
                    user_email=user_id,
                    metadata={'demanda_id': item_demanda.get('demanda_id'), 'item_id': item_id, 'campo': campo, 'correlation_id': cid}
                )
            except: pass

            return {
                'campo': campo,
                'incremento': incremento,
                'status': 'VISUAL_ONLY',
                'message': f"Atualização visual apenas para campo {campo}, não requer movimentação de estoque",
                'progresso_atualizacao': progresso_result,
                'correlation_id': cid
            }

        estagio = ESTAGIOS_PRODUCAO[campo]
        item_demanda = self.get_item_by_id(item_id)
        produto_final_id = item_demanda['produto_id']

        # Usando a BOM do produto final, encontra o ID do produto intermediário deste estágio
        produto_intermediario = bom_service.get_component_by_role(produto_final_id, estagio['role_produto_gerado'])

        if not produto_intermediario:
            progresso_result = self._atualizar_progresso_simples(item_id, campo, incremento)
            return {
                'campo': campo,
                'incremento': incremento,
                'status': 'WARNING',
                'message': f"Alocação para item {item_id} não processada: Produto com role '{estagio['role_produto_gerado']}' não encontrado na BOM do produto final {produto_final_id}.",
                'progresso_atualizacao': progresso_result,
                'correlation_id': cid
            }

        produto_intermediario_id = int(produto_intermediario['id'])
        config_deposito = app_config_service.get_config('default_production_deposit_id')
        
        if not config_deposito:
            raise ValueError("Configuração 'default_production_deposit_id' não encontrada no sistema.")
        
        deposito_id = int(config_deposito)

        # ETAPA 2: LÓGICA DE DECISÃO HÍBRIDA
        config_deposito = app_config_service.get_config('default_production_deposit_id')
        if not config_deposito:
            raise ValueError("Configuração 'default_production_deposit_id' não encontrada.")
        deposito_id = int(config_deposito)

        # Obter informações da demanda
        demanda_id = item_demanda.get('demanda_id')
        demanda_ref = f"da demanda {demanda_id}" if demanda_id else "de demanda desconhecida"

        # ETAPA 3: EXECUÇÃO
        with UnitOfWork() as uow:
            mensagem_acoes = []
            
            if incremento > 0:
                # 3.1. Verificar estoque disponível atual
                saldo_info = estoque_service.get_saldo_atual(produto_intermediario_id, deposito_id)
                saldo_disponivel = float(saldo_info.get('quantidade_disponivel', 0) or 0)
                
                # O que podemos tirar do estoque agora?
                qtd_do_estoque = min(max(0.0, saldo_disponivel), incremento)
                # O que precisamos mandar para a fila de produção?
                qtd_a_produzir = incremento - qtd_do_estoque

                # 3.1.1. Consumir do Estoque Existente (Síncrono)
                if qtd_do_estoque > 0:
                    estoque_service.registrar_saida(
                        produto_id=produto_intermediario_id,
                        deposito_id=deposito_id,
                        quantidade=qtd_do_estoque,
                        motivo=f"Alocação Síncrona Dashboard - Item {item_id} {demanda_ref}",
                        user_context={'user_id': user_id},
                        documento_referencia=demanda_id,
                        correlation_id=cid,
                        data_movimento=mov_date,
                        origem_tipo=0 # Simples
                    )
                    mensagem_acoes.append(f"Alocadas {qtd_do_estoque} unidades do estoque")

                # 3.1.2. Agendar Produção do Restante (Assíncrono)
                if qtd_a_produzir > 0:
                    permite_jit = estagio.get('permite_producao_jit', True)
                    if not permite_jit:
                        mensagem_acoes.append(f"Estoque insuficiente: {qtd_a_produzir} unidades não alocadas (sem JIT)")
                    else:
                        self.agendar_processamento_estoque(
                            demanda_id=demanda_id,
                            item_id=item_id,
                            campo=campo,
                            incremento=qtd_a_produzir,
                            user_id=user_id,
                            correlation_id=cid,
                            created_at=mov_date,
                            produto_id=produto_intermediario_id
                        )
                        mensagem_acoes.append(f"Agendada produção de {qtd_a_produzir} unidades na fila")
            else:
                # 3.2. Estorno (incremento negativo) - Entrada Síncrona
                estoque_service.registrar_entrada(
                    produto_id=produto_intermediario_id,
                    deposito_id=deposito_id,
                    quantidade=abs(incremento),
                    observacao=f"Estorno Síncrono Dashboard - Item {item_id} {demanda_ref}",
                    user_context={'user_id': user_id},
                    correlation_id=cid,
                    data_movimento=mov_date,
                    origem_tipo=0
                )
                mensagem_acoes.append(f"Estornadas {abs(incremento)} unidades para o estoque")

            # 3.3. Registro no Log de Produção Diária
            try:
                daily_production_log_service.create_log(
                    log_date=datetime.fromisoformat(mov_date[:10]).date() if mov_date else datetime.now().date(),
                    product_id=str(produto_intermediario_id),
                    product_name=produto_intermediario.get('nome') or produto_intermediario.get('name', 'Produto'),
                    quantity=abs(incremento),
                    production_order_id=None,
                    component_stock_snapshot=[],
                    user_email=user_id,
                    metadata={'demanda_id': demanda_id, 'item_id': item_id, 'campo': campo, 'correlation_id': cid}
                )
            except Exception as log_error:
                print(f"Erro ao registrar log diário de produção: {log_error}")

            # 3.4. Atualização do Progresso Visual
            progresso_result = None
            if not skip_visual_update:
                progresso_result = self._atualizar_progresso_simples(item_id, campo, incremento)
                # Agendar processamento de insumos assíncronos se houve incremento
                if incremento != 0:
                    self.agendar_processamento_estoque(demanda_id, item_id, campo, incremento, user_id, correlation_id=cid, created_at=mov_date)

        return {
            'campo': campo,
            'incremento': incremento,
            'status': 'SUCCESS',
            'message': f"Processamento concluído: {', '.join(mensagem_acoes) if mensagem_acoes else 'Apenas atualização visual'}",
            'detalhes': {
                'qtd_do_estoque': qtd_do_estoque,
                'qtd_a_produzir': qtd_a_produzir,
                'saldo_disponivel': saldo_disponivel
            },
            'progresso_atualizacao': progresso_result,
            'correlation_id': cid
        }

    def associar_saida_a_demanda(self, demanda_id: str, product_id: str, quantity: float, user_id: str = 'System'):
        """
        Associa uma saída de estoque manual a uma demanda específica, 
        identificando o item correspondente e atualizando seu progresso.
        """
        try:
            # 1. Identificar o item da demanda que usa este produto (como capa ou miolo)
            demanda = self.get_demanda_with_itens(demanda_id)
            if not demanda: return False

            target_item = None
            campo_atualizar = 'expedicao_capas_retiradas_qtd' # Default
            
            for item in demanda.get('itens', []):
                # Se o produto for o produto principal do item (Capa/Acabado)
                if str(item.get('produto_id')) == str(product_id):
                    target_item = item
                    campo_atualizar = 'expedicao_capas_retiradas_qtd'
                    break
                # Se o produto for o miolo do item
                if str(item.get('id_produto_miolo')) == str(product_id):
                    target_item = item
                    campo_atualizar = 'expedicao_miolos_retirados_qtd'
                    break
            
            if target_item:
                # 2. Atualizar o progresso do item
                self.processar_alocacao_de_demanda(
                    item_id=target_item['id'],
                    campo=campo_atualizar,
                    incremento=float(quantity),
                    user_id=user_id,
                    skip_visual_update=False
                )
                return True
            return False
        except Exception as e:
            print(f"Erro ao associar saída à demanda {demanda_id}: {e}")
            return False

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

    def registrar_producao_incremental(self, demanda_id, item_id, producao_absoluta, user_id='System', origem_tipo=None, retroactive_date=None, correlation_id=None):
        """
        Registra a produção aceitando valores ABSOLUTOS do dashboard.
        Calcula o delta automaticamente e evita duplicações por cascata no mesmo lote.
        """
        # 1. Pré-carregar o item para cálculo de deltas
        item_original = self.get_item_by_id(item_id)
        itens_dict = {str(item_id): dict(item_original)}
        
        # 2. Ordem de produção (Esquerda para a Direita)
        ORDEM_ETAPAS = [
            'capas_impressas_qtd',
            'capas_produzidas_qtd',
            'capas_prontas_retirada_qtd',
            'miolos_prontos_retirada_qtd',
            'expedicao_capas_retiradas_qtd',
            'expedicao_miolos_retirados_qtd'
        ]
        
        campos_ordenados = sorted(
            producao_absoluta.keys(), 
            key=lambda k: ORDEM_ETAPAS.index(k) if k in ORDEM_ETAPAS else 99
        )

        # 3. Preparar dados para processamento otimizado (Simulando um lote de 1 item)
        # Buscar saldos e BOMs necessários
        deposito_id = app_config_service.get_config('default_production_deposit_id')
        produto_ids = set()
        if item_original.get('produto_id'): produto_ids.add(str(item_original['produto_id']))
        if item_original.get('id_produto_miolo'): produto_ids.add(str(item_original['id_produto_miolo']))
        
        saldos_produtos = estoque_service.get_saldos_em_lote(list(produto_ids), deposito_id) if produto_ids else {}
        boms_produtos = {} # Será carregado sob demanda no otimizado se necessário

        resultados_alocacao = []
        for campo in campos_ordenados:
            valor_novo_absoluto = float(producao_absoluta[campo])
            valor_atual_no_item = float(itens_dict[str(item_id)].get(campo, 0) or 0)
            
            # CALCULO DO DELTA (Evita o problema de somar 10 + 5)
            delta = valor_novo_absoluto - valor_atual_no_item
            
            if delta == 0: continue

            resultado = self.processar_alocacao_de_demanda_otimizado(
                item_id=item_id,
                campo=campo,
                incremento=delta,
                user_id=user_id,
                itens_dict=itens_dict,
                saldos_produtos=saldos_produtos,
                boms_produtos=boms_produtos,
                origem_tipo=origem_tipo,
                retroactive_date=retroactive_date,
                correlation_id=correlation_id
            )
            resultados_alocacao.append(resultado)

        # 4. Atualizar status e auditoria
        updated_item_res = supabase_db.execute_with_retry(self.itens_table.select("*").eq('id', item_id))
        item_final = updated_item_res.data[0]

        if item_final.get('status_item') == 'Concluído':
            self._verificar_e_finalizar_demanda_automatica(demanda_id, user_id)

        auditoria_service.log_event('PRODUCAO_DASHBOARD_UPDATE', {
            'demanda_id': demanda_id,
            'item_id': item_id,
            'valores_absolutos_enviados': producao_absoluta,
            'correlation_id': correlation_id
        }, user_id)

        return self._process_item_dict(item_final)

    def _verificar_e_finalizar_demanda_automatica(self, demanda_id, user_id='System'):
        """Verifica se todos os itens de uma demanda estão concluídos e a finaliza se sim."""
        try:
            itens_res = supabase_db.execute_with_retry(self.itens_table.select("status_item").eq('demanda_id', demanda_id))
            if itens_res.data:
                todos_concluidos = all(i.get('status_item') == 'Concluído' for i in itens_res.data)
                if todos_concluidos:
                    self.finalizar_demanda_completa(demanda_id, user_id)
        except Exception as e:
            print(f"Erro ao verificar finalização automática da demanda {demanda_id}: {e}")

    def get_consolidado_producao(self, trilha=None, sku=None):
        """Busca dados da view consolidada com filtros opcionais."""
        query = supabase_db.table('view_consolidado_producao').select("*")
        if trilha:
            query = query.eq('trilha', trilha)
        if sku:
            query = query.eq('sku', sku)
        
        response = supabase_db.execute_with_retry(query)
        return response.data

    def get_consolidado_agrupado_por_sku(self, trilha=None):
        """Busca dados consolidados e agrupa por SKU para telas de produção em lote."""
        dados = self.get_consolidado_producao(trilha=trilha)
        
        agrupado = {}
        for item in dados:
            sku = item['sku']
            if sku not in agrupado:
                agrupado[sku] = {
                    'sku': sku,
                    'item_nome': item['item_nome'],
                    'qtd_total': 0,
                    'capas_impressas': 0,
                    'capas_prontas': 0,
                    'miolos_prontos': 0,
                    'match_disponivel': 0,
                    'demandas_relacionadas': []
                }
            
            agrupado[sku]['qtd_total'] += item['qtd_total']
            agrupado[sku]['capas_impressas'] += item['capas_impressas_qtd']
            agrupado[sku]['capas_prontas'] += item['capas_prontas']
            agrupado[sku]['miolos_prontos'] += item['miolos_prontos']
            agrupado[sku]['match_disponivel'] += item['match_disponivel']
            
            # Adiciona a demanda à lista de relacionadas se ainda não estiver (embora aqui cada linha seja um item_id único)
            agrupado[sku]['demandas_relacionadas'].append({
                'demanda_id': item['demanda_id'],
                'demanda_nome': item['demanda_nome'],
                'data_entrega': item['data_entrega'],
                'horario_coleta': item['horario_coleta'],
                'trilha': item['trilha'],
                'status_sincronia': item['status_sincronia'],
                'match_no_item': item['match_disponivel']
            })
            
        # Ordenar demandas relacionadas por prioridade (Principal primeiro, depois data/hora)
        for sku in agrupado:
            agrupado[sku]['demandas_relacionadas'].sort(
                key=lambda x: (x['trilha'] != 'PRINCIPAL', x['data_entrega'], x['horario_coleta'] or '23:59')
            )

        return list(agrupado.values())

    def registrar_retirada_expedicao(self, demanda_id, item_id, quantidade, user_id='System'):
        """
        Registra a retirada de itens completos na expedição.
        Garante que 1 unidade retirada consome 1 capa e 1 miolo do buffer de prontos.
        """
        response = supabase_db.execute_with_retry(self.itens_table.select("*").eq('id', item_id))
        if not response.data: raise ValueError(f"Item {item_id} não encontrado")
        
        item = response.data[0]
        
        # Validar buffers
        capas_disponiveis = (item.get('capas_produzidas_qtd') or 0) - (item.get('expedicao_capas_retiradas_qtd') or 0)
        miolos_disponiveis = (item.get('miolos_prontos_retirada_qtd') or 0) - (item.get('expedicao_miolos_retirados_qtd') or 0)
        
        if quantidade > min(capas_disponiveis, miolos_disponiveis):
            raise ValueError(f"Saldo insuficiente para retirada completa. Disponível: {min(capas_disponiveis, miolos_disponiveis)}")

        updates = {
            'expedicao_capas_retiradas_qtd': (item.get('expedicao_capas_retiradas_qtd') or 0) + quantidade,
            'expedicao_miolos_retirados_qtd': (item.get('expedicao_miolos_retirados_qtd') or 0) + quantidade,
            'updated_at': get_now_iso()
        }

        # Atualiza o status para 'Em Andamento' quando há retirada, mas não finaliza automaticamente
        updates['status_item'] = 'Em Andamento'

        supabase_db.execute_with_retry(self.itens_table.update(updates).eq('id', item_id))
        
        # --- AUTOMATIZAÇÃO DE STATUS DA DEMANDA ---
        if updates.get('status_item') == 'Concluído':
            self._verificar_e_finalizar_demanda_automatica(demanda_id, user_id)
        # ------------------------------------------

        auditoria_service.log_event('RETIRADA_EXPEDICAO', {
            'demanda_id': demanda_id,
            'item_id': item_id,
            'quantidade': quantidade,
            'descricao': f"Retirada de {quantidade} unidades completas do item {item.get('sku')}"
        }, user_id)

        return self._process_item_dict({**item, **updates})

    def registrar_producao_lote(self, demanda_id, updates_list, user_id='System', origem_tipo=None, retroactive_date=None, correlation_id=None):
        """
        Processa múltiplos incrementos de produção para itens de uma demanda em lote.
        updates_list: Lista de objetos {item_id, producao_incremental: {campo: incremento}}
        """
        # Pré-carregar todos os dados necessários para o lote inteiro
        print(f"DEBUG: registrar_producao_lote demanda={demanda_id} updates={len(updates_list)}")
        item_ids = [update.get('item_id') for update in updates_list if update.get('item_id')]
        if not item_ids:
            return {'success': True, 'results': []}

        # Buscar todos os itens de demanda de uma vez
        itens_res = supabase_db.execute_with_retry(self.itens_table.select("*").in_('id', item_ids))
        itens_dict = {str(item['id']): item for item in itens_res.data or []}

        # Extrair IDs dos produtos intermediários envolvidos
        produto_ids_intermediarios = set()
        from nistiprint_shared.config.production_stages import ESTAGIOS_PRODUCAO
        from nistiprint_shared.services.bom_service import bom_service
        for update in updates_list:
            item_id = update.get('item_id')
            producao_incremental = update.get('producao_incremental', {})

            for campo in producao_incremental.keys():
                if campo in ESTAGIOS_PRODUCAO:
                    estagio = ESTAGIOS_PRODUCAO[campo]
                    item = itens_dict.get(str(item_id))
                    if item:
                        # Prioridade: usar ID direto se disponível para Miolo
                        if estagio['role_produto_gerado'] == 'MIOLO' and item.get('id_produto_miolo'):
                            produto_ids_intermediarios.add(str(item['id_produto_miolo']))
                        else:
                            # Fallback para buscar na BOM do produto final
                            produto_final_id = item['produto_id']
                            if produto_final_id:
                                produto_intermediario = bom_service.get_component_by_role(produto_final_id, estagio['role_produto_gerado'])
                                if produto_intermediario:
                                    produto_ids_intermediarios.add(str(produto_intermediario['id']))

        # Buscar os saldos de todos os produtos intermediários envolvidos de uma vez
        deposito_id = app_config_service.get_config('default_production_deposit_id')
        saldos_produtos = {}
        if produto_ids_intermediarios:
            saldos_produtos = estoque_service.get_saldos_em_lote(list(produto_ids_intermediarios), deposito_id)

        # Buscar as BOMs de todos os produtos envolvidos de uma vez
        boms_produtos = {}
        for produto_id in produto_ids_intermediarios:
            boms_produtos[produto_id] = bom_service.get_bom_for_produto(produto_id)

        # ORDEM DE PROCESSAMENTO (Esquerda para a Direita)
        ORDEM_ETAPAS = [
            'capas_impressas_qtd',
            'capas_produzidas_qtd',
            'capas_prontas_retirada_qtd',
            'miolos_prontos_retirada_qtd',
            'expedicao_capas_retiradas_qtd',
            'expedicao_miolos_retirados_qtd'
        ]

        # Processar cada atualização com os dados pré-carregados
        results = []
        for update in updates_list:
            item_id = update.get('item_id')
            producao_incremental = update.get('producao_incremental', {})
            if item_id and producao_incremental:
                # Ordena os campos deste item específico antes de processar
                campos_ordenados = sorted(
                    producao_incremental.keys(),
                    key=lambda k: ORDEM_ETAPAS.index(k) if k in ORDEM_ETAPAS else 99
                )

                # --- Início da Estrutura de Resiliência ---
                try:
                    # ETAPA 1 (SECUNDÁRIA): Tentar executar a lógica de estoque.
                    alocacao_resultados = []
                    for campo in campos_ordenados:
                        valor = producao_incremental[campo]
                        resultado_alocacao = self.processar_alocacao_de_demanda_otimizado(
                            item_id, campo, float(valor), user_id,
                            itens_dict, saldos_produtos, boms_produtos,
                            origem_tipo=origem_tipo,
                            retroactive_date=retroactive_date,
                            correlation_id=correlation_id
                        )
                        alocacao_resultados.append(resultado_alocacao)

                        # Atualizar o estado do item em memória para que as próximas etapas
                        # considerem as mudanças de estoque feitas nesta etapa (evitando JIT duplicado)
                        item_in_memory = itens_dict.get(str(item_id))
                        if item_in_memory:
                            # Atualiza o campo atual
                            current_val = float(item_in_memory.get(campo, 0) or 0)
                            item_in_memory[campo] = current_val + float(valor)
                except Exception as e:
                    # ETAPA 2: CAPTURAR E REGISTRAR QUALQUER FALHA DE ESTOQUE.
                    error_details = {'message': str(e), 'demanda_id': demanda_id, 'item_id': item_id, 'producao_incremental': producao_incremental}
                    system_events_log_service.log_event(
                        event_type='ERRO_ALOCACAO_ESTOQUE',
                        details=error_details,
                        user_id=user_id
                    )
                finally:
                    # ETAPA 3 (PRINCIPAL): EXECUTAR A ATUALIZAÇÃO VISUAL.
                    # Esta operação é crítica e deve ter seu próprio try-except para erros fatais.
                    # IMPORTANTE: A atualização visual já é feita dentro de processar_alocacao_de_demanda_otimizado,
                    # então aqui apenas obtemos o item atualizado para retorno, sem duplicar a atualização.
                    try:
                        # Obter o item atualizado para retornar
                        updated_item_res = supabase_db.execute_with_retry(self.itens_table.select("*").eq('id', item_id))
                        if updated_item_res.data:
                            results.append({
                                'item_id': item_id,
                                'status': 'SUCCESS',
                                'message': f"Atualizado com sucesso.",
                                'data': self._process_item_dict(updated_item_res.data[0])
                            })
                    except Exception as final_e:
                        # Se até a atualização mais simples falhar (ex: DB offline), logamos como crítico.
                        system_events_log_service.log_event(
                            event_type='FALHA_CRITICA_ATUALIZACAO_VISUAL_DEMANDA',
                            details={'item_id': item_id, 'error': str(final_e), 'producao_incremental': producao_incremental},
                            user_id=user_id
                        )
                        results.append({
                            'item_id': item_id,
                            'status': 'ERROR',
                            'message': f"Falha crítica na atualização visual: {str(final_e)}"
                        })

        auditoria_service.log_event('PRODUCAO_LOTE', {
            'entidade_tipo': 'demanda',
            'registro_id': demanda_id,
            'demanda_id': demanda_id,
            'updates_count': len(updates_list),
            'descricao': f"Atualização em lote de {len(updates_list)} itens na demanda {demanda_id}"
        }, user_id)

        return {
            'success': True,
            'results': results
        }

    def processar_alocacao_avulsa_otimizado(self, product_id: str, campo: str, quantidade: float, user_id: str, sincrono: bool = False):
        """
        Processa uma produção avulsa (fora de demanda específica) com lógica recursiva e fail-safe.
        Usado principalmente pela tela de Controle de Produção (estoque geral).
        """
        from nistiprint_shared.config.production_stages import ESTAGIOS_PRODUCAO
        
        if campo not in ESTAGIOS_PRODUCAO:
            # Caso simples: apenas log diário
            selected_date = datetime.now().date()
            product = product_service.get_by_id(product_id)
            daily_production_log_service.registrar_producao(
                log_date=selected_date,
                product_id=product_id,
                product_name=product.get('name', 'Produto'),
                quantity=quantidade,
                user_email=user_id
            )
            return {'success': True}

        # SE solicitado síncrono (ex: tela de Controle de Produção), executa agora sem fila
        if sincrono:
            try:
                print(f"DEBUG: Executando PRODUCAO_AVULSA síncrona para {product_id} no campo {campo}")
                # Gerar correlation_id para rastreabilidade
                correlation_id = str(uuid.uuid4())
                # Chama o motor recursivo diretamente. Na produção avulsa, o item FICA no estoque (tipo_operacao='PRODUCAO_AVULSA')
                success = self.processar_insumos_por_bom_recursivo(
                    produto_id=int(product_id),
                    quantidade=quantidade,
                    correlation_id=correlation_id,
                    user_id=user_id,
                    tipo_operacao='PRODUCAO_AVULSA'
                )

                # Registrar no log diário para visualização imediata
                daily_production_log_service.create_log(
                    log_date=datetime.now().date(),
                    product_id=str(product_id),
                    product_name=product_service.get_by_id(product_id).get('nome', 'Produto'),
                    quantity=quantidade,
                    production_order_id=None,
                    component_stock_snapshot=[],
                    user_email=user_id,
                    metadata={'tipo': 'AVULSA_SINCRONA', 'campo': campo, 'correlation_id': correlation_id}
                )

                return {
                    'success': success,
                    'message': "Produção avulsa processada em tempo real.",
                    'queued': False
                }
            except Exception as e:
                print(f"Erro no processamento síncrono de produção avulsa: {e}")
                return {'success': False, 'error': str(e)}

        # EXECUÇÃO ASSÍNCRONA (BACKEND QUEUE) - Padrão para Dashboard
        try:
            # Gerar correlation_id para rastreabilidade
            correlation_id = str(uuid.uuid4())
            
            # Agendar Processamento de Estoque (Assíncrono)
            self.agendar_processamento_estoque(
                demanda_id=None,
                item_id=None,
                campo='PRODUCAO_AVULSA',
                incremento=quantidade,
                user_id=user_id,
                correlation_id=correlation_id,
                produto_id=product_id
            )
            
            # 2. Registrar no log diário para visualização na tela
            selected_date = datetime.now().date()
            product = product_service.get_by_id(product_id)
            daily_production_log_service.create_log(
                log_date=selected_date,
                product_id=product_id,
                product_name=product.get('name', 'Produto'),
                quantity=quantidade,
                production_order_id=None,
                component_stock_snapshot=[],
                user_email=user_id,
                metadata={'correlation_id': correlation_id, 'tipo': 'AVULSA'}
            )
            
            return {'success': True, 'correlation_id': correlation_id}
        except Exception as e:
            print(f"ERRO NA PRODUÇÃO AVULSA ASSÍNCRONA: {e}")
            raise e

    def processar_alocacao_de_demanda_otimizado(self, item_id: str, campo: str, incremento: float, user_id: str,
                                               itens_dict: dict, saldos_produtos: dict, boms_produtos: dict,
                                               origem_tipo: Optional[int] = None, retroactive_date: Optional[str] = None, correlation_id: Optional[str] = None):
        """
        Versão otimizada e evoluída de processar_alocacao_de_demanda que usa dados pré-carregados.
        Implementa recursividade para itens produzíveis na BOM e cascata de estágios.
        """
        print(f"DEBUG: processar_alocacao_otimizado item={item_id} campo={campo} inc={incremento}")
        from nistiprint_shared.config.production_stages import ESTAGIOS_PRODUCAO
        from nistiprint_shared.services.bom_service import bom_service

        # --- GESTÃO DE CORRELAÇÃO E DATA ---
        cid = correlation_id or f"DASH-{uuid.uuid4().hex[:8]}"
        mov_date = retroactive_date or get_now_iso()
        
        # --- OBTER DEPÓSITO PADRÃO PARA MOVIMENTAÇÕES ---
        deposito_id = app_config_service.get_config('default_production_deposit_id') or 'principal'
        # ------------------------------------------------

        # ETAPA 1: VALIDAÇÃO E IDENTIFICAÇÃO
        item_demanda = itens_dict.get(str(item_id))
        if not item_demanda:
            raise ValueError(f"Item {item_id} não encontrado nos dados pré-carregados")

        if campo not in ESTAGIOS_PRODUCAO:
            self._atualizar_progresso_simples(item_id, campo, incremento)
            try:
                daily_production_log_service.create_log(
                    log_date=datetime.fromisoformat(mov_date[:10]).date() if mov_date else datetime.now().date(),
                    product_id=str(item_demanda.get('produto_id')),
                    product_name="Progresso Visual",
                    quantity=incremento,
                    production_order_id=None,
                    component_stock_snapshot=[],
                    user_email=user_id,
                    metadata={'demanda_id': item_demanda.get('demanda_id'), 'item_id': item_id, 'campo': campo, 'correlation_id': cid}
                )
            except: pass
            return {
                'campo': campo,
                'incremento': incremento,
                'status': 'VISUAL_ONLY',
                'message': f"Atualização visual apenas para campo {campo}",
                'correlation_id': cid
            }

        estagio = ESTAGIOS_PRODUCAO[campo]

        # 1.1. LÓGICA DE CASCATA (Preenchimento Automático de Estágios Anteriores)
        dependencia = estagio.get('depende_de')
        if dependencia and dependencia in item_demanda:
            valor_atual_dep = float(item_demanda.get(dependencia, 0) or 0)
            valor_atual_foco = float(item_demanda.get(campo, 0) or 0)
            novo_foco = valor_atual_foco + incremento
            
            if novo_foco > valor_atual_dep:
                diff = novo_foco - valor_atual_dep
                # Chama recursivamente para o estágio dependente
                print(f"DEBUG: Cascata detectada. Campo {campo} depende de {dependencia}. Incrementando {dependencia} em {diff}")
                self.processar_alocacao_de_demanda_otimizado(
                    item_id, dependencia, diff, user_id, itens_dict, saldos_produtos, boms_produtos, 
                    retroactive_date=mov_date, correlation_id=cid
                )
                # Atualiza o dicionário local para refletir a mudança da cascata antes de prosseguir
                item_demanda[dependencia] = novo_foco

        # Se não há produto gerado associado (ex: etapa administrativa), apenas atualiza o visual
        if not estagio.get('role_produto_gerado'):
            self._atualizar_progresso_simples(item_id, campo, incremento)
            try:
                daily_production_log_service.create_log(
                    log_date=datetime.fromisoformat(mov_date[:10]).date() if mov_date else datetime.now().date(),
                    product_id=str(item_demanda.get('produto_id')),
                    product_name="Etapa Administrativa",
                    quantity=incremento,
                    production_order_id=None,
                    component_stock_snapshot=[],
                    user_email=user_id,
                    metadata={'demanda_id': item_demanda.get('demanda_id'), 'item_id': item_id, 'campo': campo, 'correlation_id': cid}
                )
            except: pass
            return {
                'campo': campo,
                'incremento': incremento,
                'status': 'SUCCESS',
                'message': f"Atualização visual de etapa administrativa {campo}",
                'correlation_id': cid
            }

        # ETAPA 2: IDENTIFICAÇÃO DO PRODUTO INTERMEDIÁRIO
        produto_intermediario = None
        if estagio['role_produto_gerado'] == 'MIOLO' and item_demanda.get('id_produto_miolo'):
            produto_intermediario = product_service.get_by_id(str(item_demanda['id_produto_miolo']))
        
        if not produto_intermediario:
            produto_final_id = item_demanda['produto_id']
            if produto_final_id:
                produto_intermediario = bom_service.get_component_by_role(produto_final_id, estagio['role_produto_gerado'])

        if not produto_intermediario:
            self._atualizar_progresso_simples(item_id, campo, incremento)
            return {
                'campo': campo,
                'incremento': incremento,
                'status': 'WARNING',
                'message': f"Produto com role '{estagio['role_produto_gerado']}' não encontrado na BOM.",
                'correlation_id': cid
            }

        # ETAPA 3: EXECUÇÃO HÍBRIDA (SYNC 1º NÍVEL / ASYNC BOM)
        # Verifica se este estágio permite produção JIT
        permite_jit = estagio.get('permite_producao_jit', True)
        
        try:
            # 1. Determinar Origem (Se não fornecido, decide com base no sinal do incremento)
            if not origem_tipo:
                origem_tipo = 1 if incremento > 0 else 2 # 1: INCREMENTAL, 2: ESTORNO

            # 2. Obter saldo disponível (Pré-carregado no lote)
            saldo_info = saldos_produtos.get(str(produto_intermediario['id']), {})
            saldo_disponivel = float(saldo_info.get('quantidade_disponivel', 0))

            # 3. LÓGICA HÍBRIDA (MEIO TERMO): Saída imediata se houver saldo, Fila para Produção se não houver.
            if incremento > 0:
                # 3.1. Consumir o que existe em estoque AGORA (Síncrono)
                qtd_saida_imediata = min(incremento, max(0.0, saldo_disponivel))
                
                # REGISTRAR ALOCAÇÃO MANUAL SEMPRE QUE HOUVER CONSUMO DE ESTOQUE
                # Isso é crucial para o cálculo de delta na finalização
                if qtd_saida_imediata > 0:
                    try:
                        estoque_service.registrar_saida(
                            produto_id=int(produto_intermediario['id']),
                            deposito_id=deposito_id,
                            quantidade=qtd_saida_imediata,
                            motivo=f"Saída Síncrona (Dashboard) - Demanda {item_demanda.get('demanda_id')}",
                            user_context={'user_id': user_id},
                            documento_referencia=item_demanda.get('demanda_id'),
                            correlation_id=cid,
                            data_movimento=mov_date,
                            origem_tipo=0 # Simples, não gera nova fila
                        )
                        # Atualizar saldo em memória para o restante do lote
                        if str(produto_intermediario['id']) in saldos_produtos:
                            saldos_produtos[str(produto_intermediario['id'])]['quantidade_disponivel'] -= qtd_saida_imediata
                        
                        # REGISTRAR ALOCAÇÃO MANUAL PARA CONTROLE DE DELTA NA FINALIZAÇÃO
                        print(f"DEBUG: Registrando alocação manual: item={item_id}, produto={produto_intermediario['id']}, qtd={qtd_saida_imediata}")
                        self._registrar_alocacao_estoque(
                            demanda_id=str(item_demanda.get('demanda_id')),
                            item_id=item_id,
                            produto_id=str(produto_intermediario['id']),
                            correlation_id=cid,
                            quantidade=qtd_saida_imediata,
                            tipo_alocacao='MANUAL_DASHBOARD',
                            processo_origem='DASHBOARD',
                            metadata={'campo': campo, 'qtd_saida_imediata': qtd_saida_imediata, 'qtd_fila_producao': incremento - qtd_saida_imediata}
                        )
                    except Exception as e_sync:
                        print(f"Erro na saída síncrona: {e_sync}")
                        import traceback
                        traceback.print_exc()
                else:
                    print(f"DEBUG: Sem estoque disponível para saída imediata. incremento={incremento}, saldo_disponivel={saldo_disponivel}")

                # 3.2. Agendar o que falta para ser PRODUZIDO (Assíncrono via BOM)
                qtd_fila_producao = incremento - qtd_saida_imediata
                if qtd_fila_producao > 0:
                    self.agendar_processamento_estoque(
                        demanda_id=item_demanda.get('demanda_id'),
                        item_id=item_id,
                        campo=campo,
                        incremento=qtd_fila_producao,
                        user_id=user_id,
                        correlation_id=cid,
                        created_at=mov_date,
                        produto_id=int(produto_intermediario['id'])
                    )
            else:
                # Estorno (incremento negativo) - Entrada síncrona
                try:
                    estoque_service.registrar_entrada(
                        produto_id=int(produto_intermediario['id']),
                        deposito_id=deposito_id,
                        quantidade=abs(incremento),
                        observacao=f"Estorno Síncrono (Dashboard) - Demanda {item_demanda.get('demanda_id')}",
                        user_context={'user_id': user_id},
                        correlation_id=cid,
                        data_movimento=mov_date,
                        origem_tipo=0
                    )
                    # Atualizar saldo em memória
                    if str(produto_intermediario['id']) in saldos_produtos:
                        saldos_produtos[str(produto_intermediario['id'])]['quantidade_disponivel'] += abs(incremento)
                    
                    # CANCELAR ALOCAÇÃO MANUAL EM CASO DE ESTORNO
                    self._marcar_alocacao_cancelada(cid, f"Estorno de {abs(incremento)} unidades no campo {campo}")
                except Exception as e_estorno:
                    print(f"Erro no estorno síncrono: {e_estorno}")

            # 4. Registro no Log de Produção Diária (Otimizado)
            try:
                daily_production_log_service.create_log(
                    log_date=datetime.fromisoformat(mov_date[:10]).date() if mov_date else datetime.now().date(),
                    product_id=str(produto_intermediario['id']),
                    product_name=produto_intermediario.get('nome') or produto_intermediario.get('name', 'Produto'),
                    quantity=abs(incremento),
                    production_order_id=None,
                    component_stock_snapshot=[],
                    user_email=user_id,
                    metadata={
                        'demanda_id': item_demanda.get('demanda_id'),
                        'item_id': item_id,
                        'campo': campo,
                        'correlation_id': cid
                    }
                )
            except Exception as log_error:
                print(f"Erro ao registrar log diário de produção: {log_error}")

            # 5. Atualização visual e de memória imediata
            self._atualizar_progresso_simples(item_id, campo, incremento)
            
            # CRITICAL: Atualiza o dicionário local para que a próxima etapa do loop
            # veja que esta etapa já foi incrementada e não dispare cascata.
            item_demanda[campo] = float(item_demanda.get(campo, 0) or 0) + incremento


        except Exception as e:
            # FAIL-SAFE: Loga o erro mas garante a atualização visual (Resiliência)
            print(f"ERRO DE ESTOQUE HÍBRIDO: {str(e)}")
            system_events_log_service.log_event(
                event_type='ERRO_ESTOQUE_HIBRIDO_PRODUCAO',
                details={'item_id': item_id, 'campo': campo, 'erro': str(e), 'produto_id': produto_intermediario['id']},
                user_id=user_id
            )
            # Tenta forçar o visual se a movimentação falhou (política best-effort)
            try:
                self._atualizar_progresso_simples(item_id, campo, incremento)
            except: pass

        return {
            'campo': campo,
            'incremento': incremento,
            'status': 'SUCCESS',
            'message': "Processamento concluído (Estoque processado em modo best-effort)",
            'correlation_id': cid
        }

    def _executar_movimentacao_estoque_recursiva(self, item_id, produto_id, quantidade, demanda_id, 
                                               saldos_produtos, boms_produtos, deve_sair_no_final=True):
        """
        Motor de movimentação de estoque com suporte a produção JIT recursiva.
        
        deve_sair_no_final: 
            True  -> (ENTRADA + SAÍDA) Usado para Dashboard (progresso) e para sub-componentes 
                     que estão sendo produzidos para serem consumidos pelo pai imediatamente.
            False -> (APENAS ENTRADA) Usado para Entrada Manual no Controle de Produção, 
                     onde o item final deve permanecer no estoque.
        """
        deposito_id = app_config_service.get_config('default_production_deposit_id')
        produto = product_service.get_by_id(produto_id)
        nome_produto = produto.get('name', f"Produto {produto_id}")
        
        # 1. PRIORIDADE: CONSUMIR DO ESTOQUE EXISTENTE
        saldo_info = saldos_produtos.get(str(produto_id))
        if saldo_info:
            saldo_disponivel = float(saldo_info.get('quantidade_disponivel', 0))
        else:
            res_saldo = estoque_service.get_saldo_atual(produto_id, deposito_id)
            saldo_disponivel = float(res_saldo.get('quantidade_disponivel', 0))

        qtd_do_estoque = min(saldo_disponivel, quantidade)
        qtd_a_produzir = max(0.0, quantidade - qtd_do_estoque)

        # 1.1. Se temos estoque, realizamos a SAÍDA (Consumo)
        # Nota: Se for o item final de uma "Entrada Manual", não queremos tirar do estoque o que já existia lá.
        # Mas se for um componente sendo consumido, ou progresso de dashboard, precisamos tirar.
        if qtd_do_estoque > 0 and deve_sair_no_final:
            estoque_service.registrar_saida(
                produto_id=produto_id,
                deposito_id=deposito_id,
                quantidade=qtd_do_estoque,
                motivo=f"Consumo de estoque para produção" if not demanda_id else f"Alocação item {item_id} demanda {demanda_id}",
                documento_referencia=demanda_id
            )

        # 2. SEGUNDA OPÇÃO: PRODUZIR O RESTANTE (RECURSIVIDADE)
        if qtd_a_produzir > 0:
            componentes = boms_produtos.get(str(produto_id), [])
            if not componentes:
                from nistiprint_shared.services.bom_service import bom_service
                componentes = bom_service.get_bom_for_produto(int(produto_id))

            if componentes:
                # 2.1. Processar cada componente da BOM recursivamente
                for comp in componentes:
                    comp_id = str(comp.componente_id)
                    qtd_comp_necessaria = float(comp.quantidade) * qtd_a_produzir
                    
                    role_comp = product_service.identify_product_role(comp_id)
                    
                    if role_comp in ['MIOLO', 'CAPA_IMPRESSAO', 'CAPA_ACABADA']:
                        # CHAMADA RECURSIVA: Componente deve ser consumido pelo pai (deve_sair_no_final=True)
                        self._executar_movimentacao_estoque_recursiva(
                            item_id=item_id,
                            produto_id=comp_id,
                            quantidade=qtd_comp_necessaria,
                            demanda_id=demanda_id,
                            saldos_produtos=saldos_produtos,
                            boms_produtos=boms_produtos,
                            deve_sair_no_final=True
                        )
                    else:
                        # Saída simples de insumo/materia-prima básica
                        estoque_service.registrar_saida(
                            produto_id=comp_id,
                            deposito_id=deposito_id,
                            quantidade=qtd_comp_necessaria,
                            motivo=f"Consumo insumo para: {nome_produto}",
                            documento_referencia=demanda_id
                        )

                # 2.2. ENTRADA do item que acabamos de produzir (independente da origem)
                estoque_service.registrar_entrada(
                    produto_id=produto_id,
                    deposito_id=deposito_id,
                    quantidade=qtd_a_produzir,
                    observacao=f"Produção JIT automática: {nome_produto}" if demanda_id else f"Entrada de produção: {nome_produto}"
                )
                
                # 2.3. SAÍDA imediata se for para Alocação de Demanda ou Consumo pelo Pai
                # Se for Entrada Manual (deve_sair_no_final=False), o item FICA no estoque.
                if deve_sair_no_final:
                    estoque_service.registrar_saida(
                        produto_id=produto_id,
                        deposito_id=deposito_id,
                        quantidade=qtd_a_produzir,
                        motivo=f"Consumo JIT produção" if not demanda_id else f"Alocação JIT demanda {demanda_id}",
                        documento_referencia=demanda_id
                    )

        return True

    def update_demanda_details(self, demanda_id: str, updates: Dict[str, Any], user_id: str = 'System') -> Dict[str, Any]:
        # 0. Resolver o ID interno (PK) se necessário
        demanda_res = supabase_db.execute_with_retry(self.demandas_table.select("id").eq('id', demanda_id))
        if not demanda_res.data:
            demanda_res = supabase_db.execute_with_retry(self.demandas_table.select("id").eq('demanda_id', demanda_id))
            if not demanda_res.data:
                raise ValueError(f"Demanda {demanda_id} não encontrada")
        
        internal_pk = demanda_res.data[0]['id']

        mapping = {
            'manual_priority_score': 'prioridade_manual',
            'nome': 'descricao'
        }

        final_updates = {'updated_at': get_now_iso()}

        # Separate empresa-specific fields to be stored in dados_adicionais
        empresa_fields = [
            'empresa_cliente_nome', 'empresa_wire_o_cor', 'empresa_elastico_cor',
            'empresa_interacao_status', 'empresa_pedido_plataforma_numero',
            'empresa_responsavel_id', 'empresa_responsavel_nome'
        ]
        
        # Colunas explícitas na tabela demandas_producao (evitar que caiam em dados_adicionais)
        explicit_columns = [
            'modalidade_logistica', 'classificacao_cliente', 'capacidade_requerida',
            'categoria_demanda', 'prioridade_tipo', 'data_limite_execucao',
            'data_inicio_planejada', 'data_fim_planejada', 'setores_envolvidos',
            'categoria_temporal', 'data_promessa_cliente', 'data_maxima_entrega'
        ]

        dados_adicionais = {}
        for k, v in updates.items():
            col = mapping.get(k, k)
            if col == 'status':
                final_updates['status'] = self._normalize_status(v)
            elif col in empresa_fields or col == 'data_finalizacao_prevista':
                # Garantir que datas sejam salvas como string ISO no JSONB
                if col == 'data_finalizacao_prevista' and v and hasattr(v, 'isoformat'):
                    dados_adicionais[col] = v.isoformat()
                else:
                    dados_adicionais[col] = v
            elif col in explicit_columns:
                # Estes campos são campos diretos da tabela, não vão para dados_adicionais
                final_updates[col] = v
            else:
                final_updates[col] = v

        # Add existing dados_adicionais to preserve other data
        existing_demanda = supabase_db.execute_with_retry(self.demandas_table.select("dados_adicionais").eq('id', internal_pk))
        if existing_demanda.data and existing_demanda.data[0]['dados_adicionais']:
            old_dados = existing_demanda.data[0]['dados_adicionais']
            if isinstance(old_dados, dict):
                # Preservar o que já existia mas não foi enviado agora
                new_dados = {**old_dados, **dados_adicionais}
                dados_adicionais = new_dados

        if dados_adicionais:
            final_updates['dados_adicionais'] = dados_adicionais

        supabase_db.execute_with_retry(self.demandas_table.update(final_updates).eq('id', internal_pk))
        return self.get_demanda_with_itens(internal_pk)

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

    def agendar_processamento_estoque(self, demanda_id, item_id, campo, incremento, user_id='System', correlation_id=None, created_at=None, produto_id=None, forcar_sincrono=False):
        """Agenda o processamento de estoque na fila e dispara o worker via Celery."""
        if incremento == 0: return # Alterado para suportar estornos (incremento < 0)
        try:
            now = get_now_iso()

            # Mapeamento: No schema real não temos 'campo'. Usamos 'tipo_operacao' para identificar a tarefa.
            # Se for um campo de etapa (ex: capas_impressas_qtd), prefixamos para o worker saber.
            tipo_op = campo
            if campo in ['ITEM_TOTAL_BOM_PROCESS', 'DEMANDA_TOTAL', 'CONSUMO_BOM', 'ESTORNO_BOM', 'PRODUCAO_AVULSA', 'ESTORNO_AVULSO']:
                tipo_op = campo
            else:
                tipo_op = f"ETAPA:{campo}"

            cid = correlation_id or str(uuid.uuid4())
            
            payload = {
                'demanda_id': demanda_id,
                'item_id': item_id,
                'produto_id': produto_id,
                'quantidade': incremento,
                'user_id': str(user_id),
                'status': 'PENDENTE',
                'tipo_operacao': tipo_op,
                'correlation_id': cid,
                'created_at': created_at or now
            }

            # Remover campos nulos para evitar erros de restrição se houver
            payload = {k: v for k, v in payload.items() if v is not None}

            supabase_db.table('fila_processamento_estoque').insert(payload).execute()
            print(f"DEBUG: Tarefa agendada na fila: {cid} - {tipo_op} - {incremento}")

            # --- DISPARO IMEDIATO VIA CELERY ---
            celery_success = False
            try:
                from nistiprint_shared.services.celery_app import celery_app
                celery_app.send_task('tasks.stock_tasks.process_stock_queue', args=[], kwargs={'limit': 50})
                print(f"DEBUG: Tarefa Celery disparada com sucesso")
                celery_success = True
            except Exception as celery_err:
                print(f"AVISO: Falha ao disparar tarefa Celery: {celery_err}")
            
            # --- FALLBACK: APENAS se Celery falhou ---
            # CORREÇÃO: Não usar fallback síncrono quando Celery está disponível
            # Isso evita duplicação de processamento (condição de corrida)
            if not celery_success:
                print(f"DEBUG: Executando fallback síncrono para {cid} (Celery falhou)")
                try:
                    # Processa imediatamente sem passar pela fila
                    if tipo_op == 'ITEM_TOTAL_BOM_PROCESS':
                        item_demanda = self.get_item_by_id(item_id)
                        produto_final_id = item_demanda['produto_id']
                        if produto_final_id:
                            self.processar_insumos_por_bom_recursivo(
                                produto_id=int(produto_final_id),
                                quantidade=abs(float(incremento)),
                                correlation_id=cid,
                                user_id=str(user_id),
                                tipo_operacao='CONSUMO_BOM' if float(incremento) > 0 else 'ESTORNO_BOM',
                                retroactive_date=created_at,
                                item_id_referencia=item_id
                            )
                            # Marcar como concluído
                            supabase_db.table('fila_processamento_estoque')\
                                .update({'status': 'CONCLUIDO', 'processed_at': now})\
                                .eq('correlation_id', cid)\
                                .execute()
                    elif tipo_op.startswith('ETAPA:'):
                        campo_etapa = tipo_op.replace('ETAPA:', '')
                        self.processar_alocacao_de_demanda(
                            item_id=item_id,
                            campo=campo_etapa,
                            incremento=float(incremento),
                            user_id=str(user_id),
                            skip_visual_update=True,
                            retroactive_date=created_at,
                            correlation_id=cid
                        )
                        supabase_db.table('fila_processamento_estoque')\
                            .update({'status': 'CONCLUIDO', 'processed_at': now})\
                            .eq('correlation_id', cid)\
                            .execute()
                    else:
                        # Outros tipos: mantém na fila para processamento posterior
                        print(f"DEBUG: Tipo {tipo_op} não suportado em fallback síncrono, mantém na fila")
                except Exception as fallback_err:
                    print(f"ERRO no fallback síncrono: {fallback_err}")
                    # Mantém na fila para tentativa posterior
            # -----------------------------------

        except Exception as e:
            print(f"Erro ao agendar processamento de estoque para {campo} no item {item_id}: {e}")
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

    def get_demandas_by_status(self, status_list: List[str], product_id=None) -> List[Dict[str, Any]]:
        if isinstance(status_list, list):
            status_list = [self._normalize_status(s) for s in status_list]
        else:
            status_list = self._normalize_status(status_list)
            
        query = self.demandas_table.select("*, canal_venda:canais_venda(nome, color, plataformas(nome))")
        if isinstance(status_list, list): query = query.in_('status', status_list)
        else: query = query.eq('status', status_list)
        response = supabase_db.execute_with_retry(query)
        return self._get_aggregated_demandas(response.data)

    def get_daily_production_summary(self):
        """Retorna um resumo da produção diária no formato esperado pelo frontend."""
        # Obter todas as demandas
        demandas = self.get_all_demandas()

        # Calcular totais gerais
        total_produzir = sum(d.get('total_itens', 0) for d in demandas)
        total_finalizados = sum(d.get('itens_concluidos', 0) for d in demandas)
        total_restante = total_produzir - total_finalizados

        # Calcular totais por plataforma
        por_plataforma = {}
        for d in demandas:
            plataforma_nome = d.get('canal_venda_nome', 'Outros')
            if plataforma_nome not in por_plataforma:
                por_plataforma[plataforma_nome] = {
                    'total_produzir': 0,
                    'total_restante': 0,
                    'total_capas_restantes': 0,
                    'total_miolos_entregues': 0,
                    'total_miolos_restantes': 0
                }

            por_plataforma[plataforma_nome]['total_produzir'] += d.get('total_itens', 0)
            por_plataforma[plataforma_nome]['total_restante'] += d.get('total_itens', 0) - d.get('itens_concluidos', 0)
            # Adicionando cálculos para capas e miolos (seria necessário ter esses dados específicos)
            # Por enquanto, usando placeholders baseados em total
            por_plataforma[plataforma_nome]['total_capas_restantes'] += d.get('total_itens', 0) - d.get('itens_concluidos', 0)
            por_plataforma[plataforma_nome]['total_miolos_entregues'] += d.get('itens_concluidos', 0)
            por_plataforma[plataforma_nome]['total_miolos_restantes'] += d.get('total_itens', 0) - d.get('itens_concluidos', 0)

        # Calcular totais por setor
        por_setor = {}
        for d in demandas:
            # O setor pode vir do usuário ou de alguma configuração da demanda
            setor_nome = d.get('setor_nome', 'Geral')
            if setor_nome not in por_setor:
                por_setor[setor_nome] = {
                    'completos': 0,
                    'em_andamento': 0,
                    'restantes': 0
                }

            status = d.get('status', '')
            if status == 'CONCLUIDO':
                por_setor[setor_nome]['completos'] += 1
            elif status in ['EM_PRODUCAO', 'COLETA_PARCIAL']:
                por_setor[setor_nome]['em_andamento'] += 1
            else:
                por_setor[setor_nome]['restantes'] += 1

        # Se não houver dados por setor, criar um setor padrão
        if not por_setor:
            por_setor['Geral'] = {
                'completos': 0,
                'em_andamento': 0,
                'restantes': 0
            }

        # Montar o objeto no formato esperado pelo frontend
        summary = {
            'geral': {
                'total_produzir': total_produzir,
                'total_restante': total_restante,
                'total_capas_restantes': total_restante,  # Placeholder
                'total_miolos_restantes': total_restante,  # Placeholder
                'total_miolos_entregues': total_finalizados  # Placeholder
            },
            'por_plataforma': por_plataforma,
            'por_setor': por_setor
        }

        return summary

    def get_dashboard_summary(self):
        from pytz import timezone
        from ..constants import APP_TIMEZONE

        tz = timezone(APP_TIMEZONE)
        now_local = datetime.now(tz)

        demandas = self.get_all_demandas()

        summary = {
            'total': len(demandas),
            'by_status': {},
            'delayed': 0,
            'total_itens_previstos_hoje': 0,
            'total_itens_finalizados_hoje': 0
        }

        for d in demandas:
            st = d.get('status', 'Unknown')
            summary['by_status'][st] = summary['by_status'].get(st, 0) + 1

            # Check data_entrega and horario_coleta
            d_entrega_str = d.get('data_entrega')
            horario_coleta_str = d.get('horario_coleta')

            if d_entrega_str:
                try:
                    d_entrega = datetime.strptime(d_entrega_str, '%Y-%m-%d').date()

                    # Combine date and time if collection time is available
                    if horario_coleta_str:
                        combined_dt = datetime.combine(d_entrega, datetime.strptime(horario_coleta_str, '%H:%M:%S').time() if ':' in horario_coleta_str and len(horario_coleta_str) > 5 else datetime.strptime(horario_coleta_str, '%H:%M').time())
                    else:
                        # Default to end of day if no specific collection time
                        combined_dt = datetime.combine(d_entrega, datetime.max.time()).replace(hour=23, minute=59, second=59)

                    # Localize the combined datetime to the application timezone
                    combined_dt_localized = tz.localize(combined_dt)

                    # Check if the deadline has passed compared to current time in local timezone
                    if combined_dt_localized < now_local and st != 'CONCLUIDO':
                        summary['delayed'] += 1

                    # Check if delivery is scheduled for today
                    if d_entrega == now_local.date():
                        summary['total_itens_previstos_hoje'] += d.get('total_itens', 0)
                        summary['total_itens_finalizados_hoje'] += d.get('itens_concluidos', 0)
                except: pass
        return summary

    def get_prioritized_demandas(self, limit=50):
        response = supabase_db.execute_with_retry(
            self.demandas_table.select("*, canal_venda:canais_venda(nome, color, plataformas(nome))")\
            .neq('status', 'CONCLUIDO').neq('status', 'CANCELADO')\
            .order('data_entrega', nullsfirst=False).limit(limit)
        )
        return self._get_aggregated_demandas(response.data)

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

    def processar_insumos_por_bom_recursivo(self, produto_id: int, quantidade: float, correlation_id: str, user_id: str, tipo_operacao: str = 'CONSUMO_BOM', retroactive_date: Optional[str] = None, item_id_referencia: str = None, qtd_a_produzir_forcada: float = None):
        """
        Motor de Produção Waterfall:
        1. Verifica estoque disponível (apenas se CONSUMO_BOM).
        2. Se houver estoque, consome (SAÍDA).
        3. Se faltar e houver BOM, produz o restante recursivamente (ENTRADA + SAÍDA).
        4. Se for PRODUCAO_AVULSA, produz sem consumir o item final (fica no estoque).
        5. VERIFICA alocações manuais existentes para evitar duplicação (apenas se item_id_referencia fornecido).
        
        Parâmetro qtd_a_produzir_forcada:
        - Usado quando o caller já calculou o delta e quer forçar a quantidade a produzir
        - Ignora cálculo de estoque para este produto, vai direto para explosão BOM
        """
        print(f"DEBUG [WATERFALL] Processando Produto {produto_id}, Qtd: {quantidade}, Operacao: {tipo_operacao}, Correlation: {correlation_id}, ItemRef: {item_id_referencia}, QtdProduzirForcada: {qtd_a_produzir_forcada}")
        from nistiprint_shared.services.bom_service import bom_service
        from nistiprint_shared.services.app_config_service import app_config_service

        default_deposito_id = app_config_service.get_config('default_production_deposit_id')

        # --- VERIFICAÇÃO DE ALOCAÇÕES MANUAIS (DELTA) ---
        # Se temos um item_id_referencia, verificamos o que já foi alocado manualmente
        quantidade_original = quantidade
        qtd_a_produzir = quantidade
        
        if item_id_referencia and tipo_operacao == 'CONSUMO_BOM' and qtd_a_produzir_forcada is None:
            saldo_a_processar = self._calcular_saldo_a_processar(
                item_id=item_id_referencia,
                produto_id=str(produto_id),
                quantidade_necessaria=quantidade
            )
            if saldo_a_processar < quantidade:
                print(f"DEBUG [WATERFALL] Delta detectado: Original={quantidade}, Alocado={quantidade - saldo_a_processar}, AProcessar={saldo_a_processar}")
                quantidade = saldo_a_processar
                qtd_a_produzir = saldo_a_processar

                # Se tudo já foi alocado, não precisa processar nada
                if quantidade <= 0:
                    print(f"DEBUG [WATERFALL] Produto {produto_id} já foi totalmente alocado manualmente. Pulando processamento.")
                    return
            else:
                print(f"DEBUG [WATERFALL] Sem alocações manuais para {produto_id}. Processando {quantidade} unidades normalemente.")

        # --- LÓGICA DE DECISÃO DE ESTOQUE ---
        qtd_estoque = 0.0

        if tipo_operacao == 'CONSUMO_BOM':
            # Se qtd_a_produzir_forcada foi fornecido, usamos esse valor diretamente
            # Isso indica que o caller já calculou o delta e quer produzir apenas essa quantidade
            if qtd_a_produzir_forcada is not None:
                qtd_a_produzir = qtd_a_produzir_forcada
                print(f"DEBUG [WATERFALL] Usando qtd_a_produzir_forcada={qtd_a_produzir_forcada}")
            else:
                # 1. Verificar estoque disponível atual do produto para ver se podemos pular a produção JIT
                saldo_info = estoque_service.get_saldo_atual(produto_id, default_deposito_id)
                disponivel = float(saldo_info.get('quantidade_disponivel', 0) or 0)

                # O que vamos tirar do estoque pronto?
                qtd_estoque = min(max(0.0, disponivel), quantidade)
                # O que precisamos "produzir" via BOM?
                qtd_a_produzir = quantidade - qtd_estoque

                print(f"DEBUG [WATERFALL] Produto {produto_id}: Disponivel={disponivel}, UsarEstoque={qtd_estoque}, Produzir={qtd_a_produzir}")

            # 2. Consumir o que já existe em estoque (SAÍDA SIMPLES)
            if qtd_estoque > 0:
                estoque_service.registrar_saida(
                    produto_id=produto_id,
                    deposito_id=default_deposito_id,
                    quantidade=qtd_estoque,
                    motivo=f"[WATERFALL_ESTOQUE] Saída de saldo existente para Correlation: {correlation_id}",
                    usuario_id=None,
                    correlation_id=correlation_id,
                    origem_tipo=0,
                    data_movimento=retroactive_date
                )

                # Registrar alocação se temos item_id_referencia
                if item_id_referencia:
                    self._registrar_alocacao_estoque(
                        demanda_id='UNKNOWN',  # Será atualizado se necessário
                        item_id=item_id_referencia,
                        produto_id=str(produto_id),
                        correlation_id=correlation_id,
                        quantidade=qtd_estoque,
                        tipo_alocacao='FINALIZACAO',
                        processo_origem='WORKER_FINALIZACAO',
                        metadata={'qtd_estoque': qtd_estoque, 'qtd_a_produzir': qtd_a_produzir, 'quantidade_original': quantidade_original}
                    )
        elif tipo_operacao == 'PRODUCAO_AVULSA':
            # Produção avulsa sempre gera novas unidades explodindo BOM
            qtd_estoque = 0.0
            qtd_a_produzir = quantidade
            print(f"DEBUG [WATERFALL] Produção Avulsa para {produto_id}: Produzindo {quantidade}...")

        # 3. Processar o restante que precisa ser "produzido" ou consumido sem estoque
        if qtd_a_produzir <= 0:
            print(f"DEBUG [WATERFALL] Produto {produto_id}: qtd_a_produzir={qtd_a_produzir}. Pulando explosão BOM.")
            return

        # Verificar se tem BOM para produzir
        componentes = bom_service.get_bom_for_produto(produto_id)

        if componentes and tipo_operacao in ['CONSUMO_BOM', 'PRODUCAO_AVULSA']:
            print(f"DEBUG [WATERFALL] Produto {produto_id} tem BOM. Explodindo para {qtd_a_produzir} unidades...")
            # --- PRODUZIR ---
            # 3.1. Explodir BOM recursivamente para os filhos (Sempre CONSUMO_BOM para os filhos)
            # IMPORTANTE: Não passar item_id_referencia para os filhos, pois eles são componentes da BOM
            # e devem ser consumidos integralmente para produzir qtd_a_produzir
            for comp in componentes:
                qtd_comp_necessaria = float(comp.quantidade) * qtd_a_produzir
                print(f"DEBUG [WATERFALL] Componente {comp.componente_id}: {comp.quantidade} x {qtd_a_produzir} = {qtd_comp_necessaria}")
                self.processar_insumos_por_bom_recursivo(
                    produto_id=int(comp.componente_id),
                    quantidade=qtd_comp_necessaria,
                    correlation_id=correlation_id,
                    user_id=user_id,
                    tipo_operacao='CONSUMO_BOM', # Filhos sempre são consumidos
                    retroactive_date=retroactive_date,
                    item_id_referencia=None  # NÃO passar item_id_referencia para componentes
                )

            # 3.2. Registrar ENTRADA do produto atual (foi produzido agora consumindo os filhos)
            estoque_service.registrar_entrada(
                produto_id=produto_id,
                deposito_id=default_deposito_id,
                quantidade=qtd_a_produzir,
                observacao=f"[WATERFALL_PROD] Entrada de item produzido para Correlation: {correlation_id}",
                usuario_id=None,
                correlation_id=correlation_id,
                origem_tipo=8, # 8: ENTRADA_POR_PRODUCAO_BOM
                data_movimento=retroactive_date
            )
            
            # 3.3. Registrar SAÍDA do produto atual APENAS se for CONSUMO_BOM
            # Se for PRODUCAO_AVULSA, o item FICA no estoque pronto.
            if tipo_operacao == 'CONSUMO_BOM':
                estoque_service.registrar_saida(
                    produto_id=produto_id,
                    deposito_id=default_deposito_id,
                    quantidade=qtd_a_produzir,
                    motivo=f"[WATERFALL_CONSUMO] Saída de item produzido para Correlation: {correlation_id}",
                    usuario_id=None,
                    correlation_id=correlation_id,
                    origem_tipo=0,
                    data_movimento=retroactive_date
                )
        else:
            # --- NÃO TEM BOM OU É ESTORNO ---
            if tipo_operacao in ['CONSUMO_BOM', 'ESTORNO_AVULSO_CONSUMO']: # Estorno de consumo seria saída? Não, entrada.
                # Consome direto (fica negativo se não houver estoque)
                print(f"DEBUG [WATERFALL] Produto {produto_id} SEM BOM. Registrando SAIDA DIRETA: {qtd_a_produzir}")
                estoque_service.registrar_saida(
                    produto_id=produto_id,
                    deposito_id=default_deposito_id,
                    quantidade=qtd_a_produzir,
                    motivo=f"[WATERFALL_DIRETO] Saída direta (sem BOM) para Correlation: {correlation_id}",
                    usuario_id=None,
                    correlation_id=correlation_id,
                    origem_tipo=0,
                    data_movimento=retroactive_date
                )
            elif tipo_operacao in ['ESTORNO_BOM', 'ESTORNO_AVULSO']:
                # Lógica de Estorno (apenas devolve ao estoque)
                print(f"DEBUG [WATERFALL] Estornando {produto_id}: {quantidade}")
                estoque_service.registrar_entrada(
                    produto_id=produto_id,
                    deposito_id=default_deposito_id,
                    quantidade=quantidade,
                    observacao=f"[WATERFALL_ESTORNO] Estorno para Correlation: {correlation_id}",
                    usuario_id=None,
                    correlation_id=correlation_id,
                    origem_tipo=0,
                    data_movimento=retroactive_date
                )

    def processar_fila_estoque(self, limit=10):
        """
        Processa as tarefas pendentes na fila de processamento de estoque (Modelo Outbox Atômico).
        Utiliza RPC fetch_and_lock_stock_tasks para garantir consumo exclusivo por worker.
        """
        import socket
        import uuid
        worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"

        try:
            # 1. Busca e trava as tarefas via RPC (Operação atômica no Postgres)
            print(f"DEBUG: Worker '{worker_id}' tentando buscar até {limit} tarefas na fila...")
            res = supabase_db.rpc('fetch_and_lock_stock_tasks', {
                'p_worker_id': worker_id,
                'p_limit': limit
            }).execute()

            if not res.data:
                # print(f"DEBUG: Nenhuma tarefa pendente encontrada para worker '{worker_id}'.")
                return 0

            print(f"DEBUG: Worker '{worker_id}' obteve {len(res.data)} tarefas para processar.")
            processed_count = 0
            for tarefa in res.data:
                tarefa_id = tarefa['id']
                try:
                    # 2. VERIFICAÇÃO DE IDEMPOTÊNCIA
                    # Verifica se já existe movimentação de estoque para este correlation_id
                    # Isso previne duplicação em caso de condição de corrida
                    t_correlation_id = tarefa.get('correlation_id')
                    
                    # Busca se já existe movimentação para este correlation_id
                    existing_mov = supabase_db.table('movimentacoes_estoque')\
                        .select('id', count='exact')\
                        .eq('correlation_id', t_correlation_id)\
                        .execute()
                    
                    if existing_mov.data and len(existing_mov.data) > 0:
                        print(f"DEBUG: Tarefa {t_correlation_id} JÁ FOI PROCESSADA (idempotência). Marcando como CONCLUIDO.")
                        # Marca como concluído sem processar novamente
                        supabase_db.table('fila_processamento_estoque')\
                            .update({
                                'status': 'CONCLUIDO',
                                'processed_at': get_now_iso(),
                                'locked_at': None,
                                'mensagem_erro': None
                            })\
                            .eq('id', tarefa_id)\
                            .execute()
                        processed_count += 1
                        continue
                    
                    # 3. Executar o processamento real (BOM Explosion)
                    t_retroactive_date = tarefa.get('created_at')
                    t_tipo = tarefa.get('tipo_operacao', '')

                    if t_tipo in ['CONSUMO_BOM', 'ESTORNO_BOM', 'PRODUCAO_AVULSA', 'ESTORNO_AVULSO']:
                        self.processar_insumos_por_bom_recursivo(
                            produto_id=tarefa['produto_id'],
                            quantidade=float(tarefa['quantidade']),
                            correlation_id=t_correlation_id,
                            user_id=tarefa.get('user_id', 'System'),
                            tipo_operacao=t_tipo,
                            retroactive_date=t_retroactive_date
                        )
                    elif t_tipo == 'DEMANDA_TOTAL':
                        self._baixar_estoque_demanda(tarefa['demanda_id'], tarefa.get('user_id', 'System'))
                    elif t_tipo == 'ITEM_TOTAL_BOM_PROCESS':
                        # --- EXPLOSÃO COMPLETA DE BOM NA FINALIZAÇÃO ---
                        item_demanda = self.get_item_by_id(tarefa['item_id'])
                        produto_final_id = item_demanda['produto_id']

                        if produto_final_id:
                            # O motor Waterfall agora cuida de: Consumir Insumos -> Entrar Produto -> Sair Produto
                            # PASSAR item_id_referencia PARA CÁLCULO DE DELTA
                            self.processar_insumos_por_bom_recursivo(
                                produto_id=int(produto_final_id),
                                quantidade=abs(float(tarefa['quantidade'])),
                                correlation_id=t_correlation_id,
                                user_id=tarefa.get('user_id', 'System'),
                                tipo_operacao='CONSUMO_BOM' if float(tarefa['quantidade']) > 0 else 'ESTORNO_BOM',
                                retroactive_date=t_retroactive_date,
                                item_id_referencia=tarefa['item_id']  # NOVO: permite cálculo de delta
                            )

                    elif t_tipo == 'ITEM_TOTAL_PROCESSO':
                        etapas_estoque = ['capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd', 'miolos_prontos_retirada_qtd']
                        for campo_etapa in etapas_estoque:
                            self.processar_alocacao_de_demanda(
                                item_id=tarefa['item_id'],
                                campo=campo_etapa,
                                incremento=float(tarefa['quantidade']),
                                user_id=tarefa.get('user_id', 'System'),
                                skip_visual_update=True,
                                retroactive_date=t_retroactive_date,
                                correlation_id=t_correlation_id
                            )
                    elif t_tipo.startswith('ETAPA:'):
                        # --- EXPLOSÃO DE BOM PARA PRODUÇÃO JIT (ETAPA ESPECÍFICA) ---
                        campo_etapa = t_tipo.replace('ETAPA:', '')
                        from nistiprint_shared.config.production_stages import ESTAGIOS_PRODUCAO
                        estagio = ESTAGIOS_PRODUCAO.get(campo_etapa)
                        
                        if estagio and estagio.get('role_produto_gerado'):
                            item_demanda = self.get_item_by_id(tarefa['item_id'])
                            produto_final_id = item_demanda['produto_id']
                            
                            produto_intermediario = None
                            if estagio['role_produto_gerado'] == 'MIOLO' and item_demanda.get('id_produto_miolo'):
                                produto_intermediario = {'id': item_demanda['id_produto_miolo']}
                            else:
                                produto_intermediario = bom_service.get_component_by_role(produto_final_id, estagio['role_produto_gerado'])
                            
                            if produto_intermediario:
                                # O motor Waterfall agora cuida de: Consumir Insumos -> Entrar Produto -> Sair Produto
                                # PASSAR item_id_referencia PARA CÁLCULO DE DELTA
                                self.processar_insumos_por_bom_recursivo(
                                    produto_id=int(produto_intermediario['id']),
                                    quantidade=abs(float(tarefa['quantidade'])),
                                    correlation_id=t_correlation_id,
                                    user_id=tarefa.get('user_id', 'System'),
                                    tipo_operacao='CONSUMO_BOM' if float(tarefa['quantidade']) > 0 else 'ESTORNO_BOM',
                                    retroactive_date=t_retroactive_date,
                                    item_id_referencia=tarefa['item_id']  # NOVO: permite cálculo de delta
                                )
                    else:
                        # Outros tipos (visuais ou não mapeados)
                        pass
                    
                    # 3. Sucesso: Marcar como concluído
                    supabase_db.table('fila_processamento_estoque')\
                        .update({
                            'status': 'CONCLUIDO', 
                            'processed_at': get_now_iso(),
                            'locked_at': None,
                            'mensagem_erro': None
                        })\
                        .eq('id', tarefa_id)\
                        .execute()
                    
                    processed_count += 1
                except Exception as e:
                    # 4. TRATAMENTO DE ERROS COM BACKOFF
                    error_msg = str(e)
                    tentativas = tarefa.get('tentativas', 1)
                    
                    is_temporary = any(term in error_msg.upper() for term in ['SALDO', 'INSUFICIENTE', 'ESTOQUE', 'CONEXÃO', 'TIMEOUT'])
                    
                    update_payload = {
                        'locked_at': None,
                        'mensagem_erro': f"Tentativa {tentativas}: {error_msg}"
                    }
                    
                    if is_temporary and tentativas < 5:
                        intervals = [1, 5, 15, 30, 60]
                        delay = intervals[min(tentativas-1, len(intervals)-1)]
                        
                        update_payload['status'] = 'ERRO'
                        update_payload['proxima_execucao_at'] = (datetime.now() + timedelta(minutes=delay)).isoformat()
                    else:
                        update_payload['status'] = 'ERRO'
                        update_payload['proxima_execucao_at'] = None
                    
                    supabase_db.table('fila_processamento_estoque').update(update_payload).eq('id', tarefa_id).execute()
            
            return processed_count
        except Exception as e:
            print(f"Erro global no Atomic Stock Worker: {e}")
            return 0

    def finalizar_demanda_completa(self, demanda_id, user_id='System'):
        # 1. Finalizar cada item individualmente (isso dispara estoque, cascatas e logs)
        try:
            itens_res = supabase_db.execute_with_retry(self.itens_table.select("id").eq('demanda_id', demanda_id))
            if itens_res.data:
                for item in itens_res.data:
                    self.finalizar_item(demanda_id, item['id'], user_id)
        except Exception as e:
            print(f"Erro ao finalizar itens da demanda {demanda_id} no processo completo: {e}")

        # 2. Atualizar status para CONCLUIDO
        res = self.update_demanda_details(demanda_id, {'status': 'CONCLUIDO', 'data_conclusao': get_now_iso()}, user_id)

        # 3. AGENDAR BAIXA FINAL: Enviar para a fila para baixar estoque do produto vendido em background
        self.agendar_processamento_estoque(demanda_id, None, 'DEMANDA_TOTAL', 1, user_id)

        return res
    def atualizar_demanda_completa(self, demanda_id: str, updates: Dict[str, Any], itens: List[Dict[str, Any]], user_id: str = 'System') -> Dict[str, Any]:
        """Atualiza completamente uma demanda incluindo cabeçalho e itens"""
        
        # 0. Resolver o ID interno (PK) se necessário
        # Tenta buscar pelo ID (PK) para garantir que temos o número inteiro correto para as FKs
        demanda_res = supabase_db.execute_with_retry(self.demandas_table.select("id").eq('id', demanda_id))
        if not demanda_res.data:
            # Se não achou por ID, tenta por demanda_id (UUID)
            demanda_res = supabase_db.execute_with_retry(self.demandas_table.select("id").eq('demanda_id', demanda_id))
            if not demanda_res.data:
                raise ValueError(f"Demanda {demanda_id} não encontrada")
        
        internal_pk = demanda_res.data[0]['id']

        # Atualizar o cabeçalho da demanda
        mapping = {
            'manual_priority_score': 'prioridade_manual',
            'nome': 'descricao',
            'canal_venda_nome': 'canal_venda_id',  # This might need adjustment based on how frontend sends it
        }

        final_updates = {'updated_at': get_now_iso()}

        # Separate empresa-specific fields to be stored in dados_adicionais
        empresa_fields = [
            'empresa_cliente_nome', 'empresa_wire_o_cor', 'empresa_elastico_cor',
            'empresa_interacao_status', 'empresa_pedido_plataforma_numero',
            'empresa_responsavel_id', 'empresa_responsavel_nome'
        ]

        dados_adicionais = {}
        for k, v in updates.items():
            col = mapping.get(k, k)
            if col in empresa_fields or col == 'data_finalizacao_prevista':
                # Garantir que datas sejam salvas como string ISO no JSONB
                if col == 'data_finalizacao_prevista' and v and hasattr(v, 'isoformat'):
                    dados_adicionais[col] = v.isoformat()
                else:
                    dados_adicionais[col] = v
            elif col in ['modalidade_logistica', 'classificacao_cliente']:
                # Estes campos são campos diretos da tabela, não vão para dados_adicionais
                final_updates[col] = v
            else:
                final_updates[col] = v

        # Add existing dados_adicionais to preserve other data
        existing_demanda = supabase_db.execute_with_retry(self.demandas_table.select("dados_adicionais").eq('id', internal_pk))
        if existing_demanda.data and existing_demanda.data[0]['dados_adicionais']:
            old_dados = existing_demanda.data[0]['dados_adicionais']
            if isinstance(old_dados, dict):
                # Preservar o que já existia mas não foi enviado agora
                new_dados = {**old_dados, **dados_adicionais}
                dados_adicionais = new_dados

        if dados_adicionais:
            final_updates['dados_adicionais'] = dados_adicionais

        # Perform the update using the PK
        supabase_db.execute_with_retry(self.demandas_table.update(final_updates).eq('id', internal_pk))

        # Atualizar itens - primeiro deletar existentes e depois inserir novos usando o PK
        supabase_db.execute_with_retry(self.itens_table.delete().eq('demanda_id', internal_pk))

        # Inserir os novos itens
        itens_payload = []
        for item in itens:
            # Resolve miolo se necessário
            item = self._resolve_miolo_for_item(item)

            itens_payload.append({
                'demanda_id': internal_pk,
                'produto_id': item.get('produto_id'),
                'sku': item.get('sku'),
                'descricao': item.get('descricao', 'Item sem descrição'),
                'quantidade': int(item.get('quantidade', 1)),
                'capas_impressas_qtd': item.get('capas_impressas_qtd', 0),
                'capas_produzidas_qtd': item.get('capas_produzidas_qtd', 0),
                'capas_prontas_retirada_qtd': item.get('capas_prontas_retirada_qtd', 0),
                'miolos_prontos_retirada_qtd': item.get('miolos_prontos_retirada_qtd', 0),
                'expedicao_capas_retiradas_qtd': item.get('expedicao_capas_retiradas_qtd', 0),
                'expedicao_miolos_retirados_qtd': item.get('expedicao_miolos_retirados_qtd', 0),
                'status_item': item.get('status_item', 'Pendente'),
                'miolo_nome': item.get('miolo_name') or item.get('miolo_nome'),
                'id_produto_miolo': item.get('id_produto_miolo'),
                'variacao': item.get('variacao') or item.get('item_variacao'),
                'created_at': get_now_iso(),
                'updated_at': get_now_iso()
            })
        
        if itens_payload:
            supabase_db.execute_with_retry(self.itens_table.insert(itens_payload))
            
            # --- ATUALIZAÇÃO DE PREVISÃO DE CONSUMO ---
            try:
                previsao_consumo_service.gerar_previsao_para_demanda(internal_pk, itens_payload)
            except Exception as e:
                print(f"Erro ao atualizar previsão de consumo: {e}")
            # ------------------------------------------

        auditoria_service.log_event('DEMANDA_ATUALIZADA_COMPLETA', {'demanda_id': internal_pk}, user_id)
        return self.get_demanda_with_itens(internal_pk)

    def deletar_demanda(self, demanda_id: str, user_id='System'):
        # --- INTEGRAÇÃO COM ESTOQUE (LIBERAR RESERVAS) ---
        try:
            itens_res = supabase_db.execute_with_retry(self.itens_table.select("produto_id, quantidade").eq('demanda_id', demanda_id))
            for item in itens_res.data:
                if item.get('produto_id'):
                    estoque_service.liberar_reserva(
                        produto_id=item['produto_id'], 
                        quantidade=item['quantidade']
                    )
        except Exception as e:
            print(f"Erro ao liberar reservas na deleção da demanda {demanda_id}: {e}")
        # --------------------------------------------------

        supabase_db.execute_with_retry(self.itens_table.delete().eq('demanda_id', demanda_id))
        supabase_db.execute_with_retry(self.demandas_table.delete().eq('id', demanda_id))
        return True

    def get_painel_producao_setores(self, setor_id_ou_nome):
        """Retorna dados do painel de produção organizado por setores/colunas Kanban."""
        # Busca demandas ativas
        demandas_ativas = self.get_demandas_by_status(['Pendente', 'Em Produção', 'Em Andamento', 'Criada'])
        
        demanda_ids = [d['id'] for d in demandas_ativas]
        itens_mapping = self.get_items_for_multiple_demandas([str(id) for id in demanda_ids])
        
        colunas = {
            'a_imprimir_capas': [],
            'a_produzir_capas': [],
            'a_agrupar_capas': [],
            'a_produzir_miolos': [],
            'pronto_expedicao': [],
            'em_montagem': []
        }
        
        total_itens_count = 0
        urgentes_count = 0
        setores_pendencias = {
            'CPD': 0,
            'Capas': 0,
            'Miolos': 0,
            'Expedição': 0
        }
        
        # Coletar todos os itens para enriquecer com estoque em lote
        all_items_flat = []
        for d in demandas_ativas:
            did_str = str(d['id'])
            all_items_flat.extend(itens_mapping.get(did_str, []))
        
        # Obter o depósito padrão para produção
        from nistiprint_shared.services.app_config_service import app_config_service
        deposito_id = app_config_service.get_config('default_production_deposit_id')

        # Enriquecer itens com dados de estoque
        enriched_items = self._enrich_items_with_stock(all_items_flat, deposito_id)
        
        # Remapear enriquecidos de volta para o itens_mapping
        itens_mapping = {}
        for item in enriched_items:
            did = str(item['demanda_id'])
            if did not in itens_mapping: itens_mapping[did] = []
            itens_mapping[did].append(item)

        for d in demandas_ativas:
            did_str = str(d['id'])
            itens = itens_mapping.get(did_str, [])
            
            # Check urgency (Express ou Deadline Crítico)
            is_critical = d.get('modalidade_logistica') == 'EXPRESS' or d.get('is_flex') or d.get('manual_priority_score', 0) >= 100
            if is_critical:
                urgentes_count += 1
            
            for item in itens:
                if item.get('status_item') == 'Concluído':
                    continue
                
                qty = item.get('quantidade', 1)
                total_itens_count += 1
                
                # Progress structure for frontend (esperado pelo PainelProducaoPage.jsx)
                item_data = {
                    'id': item['id'],
                    'demanda_id': d['id'],
                    'demanda_nome': d['nome'],
                    'item_descricao': item['descricao'],
                    'quantidade_total': qty,
                    'data_entrega': d['data_entrega'],
                    'horario_coleta': d['horario_coleta'],
                    'canal_venda': d['canal_venda_nome'],
                    'prioridade': d.get('manual_priority_score', 0),
                    'miolo_name': item.get('miolo_name'),
                    # Estoque injetado pelo enriquecimento
                    'estoque_disponivel_miolo': item.get('estoque_disponivel_miolo', 0),
                    'estoque_disponivel_capa': item.get('estoque_disponivel_capa', 0),
                    'estoque_disponivel_impressao': item.get('estoque_disponivel_impressao', 0),
                    'progresso_capas': {
                        'prontas_retirada': item.get('capas_prontas_retirada_qtd', 0),
                        'real_em_producao': item.get('capas_impressas_qtd', 0),
                        'real_ficando_prontas': item.get('capas_produzidas_qtd', 0),
                        'real_finalizando_expedicao': item.get('expedicao_capas_retiradas_qtd', 0)
                    },
                    'progresso_miolos': {
                        'prontos_retirada': item.get('miolos_prontos_retirada_qtd', 0),
                        'real_em_producao': item.get('miolos_prontos_retirada_qtd', 0)
                    }
                }
                
                # Lógica de distribuição nas colunas Kanban
                # 1. CPD (A Imprimir)
                if item.get('capas_impressas_qtd', 0) < qty:
                    colunas['a_imprimir_capas'].append(item_data)
                    setores_pendencias['CPD'] += (qty - item.get('capas_impressas_qtd', 0))
                
                # 2. Capas (A Produzir) - Capas impressas que ainda não foram finalizadas
                if item.get('capas_produzidas_qtd', 0) < item.get('capas_impressas_qtd', 0):
                    colunas['a_produzir_capas'].append(item_data)
                    setores_pendencias['Capas'] += (item.get('capas_impressas_qtd', 0) - item.get('capas_produzidas_qtd', 0))
                
                # 3. Miolos (A Produzir)
                if item.get('miolos_prontos_retirada_qtd', 0) < qty:
                    colunas['a_produzir_miolos'].append(item_data)
                    setores_pendencias['Miolos'] += (qty - item.get('miolos_prontos_retirada_qtd', 0))
                
                # 4. Expedição (Pronto p/ Expedição) - Capa e Miolo prontos mas não retirados
                if item.get('capas_produzidas_qtd', 0) == qty and item.get('miolos_prontos_retirada_qtd', 0) == qty:
                    if item.get('expedicao_capas_retiradas_qtd', 0) < qty:
                        colunas['pronto_expedicao'].append(item_data)
                        setores_pendencias['Expedição'] += (qty - item.get('expedicao_capas_retiradas_qtd', 0))

        # Ordenar colunas por urgência (Data Entrega ASC, Horário Coleta ASC)
        for key in colunas:
            colunas[key].sort(key=lambda x: (x['data_entrega'] or '9999-12-31', x['horario_coleta'] or '23:59'))

        return {
            'total_itens': total_itens_count,
            'demandas_urgentes': urgentes_count,
            'setores_pendencias': setores_pendencias,
            'colunas': colunas
        }

    def alocar_producao_automatica(self, produto_id: str, quantidade: float, user_id: str = 'System'):
        """
        Distribui uma quantidade produzida genericamente entre as demandas pendentes.
        Identifica se o produto é um miolo ou capa/final para atualizar o campo correto.
        """
        if quantidade <= 0: return 0

        # 1. Determinar o tipo de apontamento baseado na categoria do produto
        from nistiprint_shared.services.app_config_service import app_config_service
        miolo_cat_id = app_config_service.get_config('producao_miolos_category_id')
        
        # Busca detalhes do produto para saber a categoria
        prod_details = product_service.get_by_id(str(produto_id))
        if not prod_details: return 0
        
        categoria_id = str(prod_details.get('categoria_id'))
        is_miolo = (categoria_id == str(miolo_cat_id))

        # 2. Buscar itens de demanda pendentes que usam este produto
        # Se for miolo, busca por id_produto_miolo. Se não, por produto_id (capa/final).
        query = self.itens_table.select("*, demanda:demandas_producao(*)").neq('status_item', 'Concluído')
        
        if is_miolo:
            query = query.eq('id_produto_miolo', produto_id)
        else:
            query = query.eq('produto_id', produto_id)

        response = supabase_db.execute_with_retry(query)
        if not response.data: return 0

        # 3. Filtrar apenas demandas ativas e ordenar por prioridade
        itens_pendentes = []
        for item in response.data:
            demanda = item.get('demanda')
            if not demanda or demanda.get('status') in ['CONCLUIDO', 'CANCELADO']:
                continue
            itens_pendentes.append(item)

        # Ordenação: Express -> Score Manual DESC -> Data Entrega ASC -> Coleta ASC
        def sort_priority(i):
            d = i['demanda']
            is_express = d.get('modalidade_logistica') == 'EXPRESS' or d.get('is_flex', False)
            prioridade = d.get('prioridade_manual', 0) or 0
            data = d.get('data_entrega', '9999-12-31')
            hora = d.get('horario_coleta', '23:59')
            return (not is_express, -int(prioridade), data, hora)

        itens_pendentes.sort(key=sort_priority)

        # 4. Distribuir a quantidade
        saldo_a_alocar = float(quantidade)
        alocacoes_realizadas = 0

        for item in itens_pendentes:
            if saldo_a_alocar <= 0: break

            qtd_total_item = item['quantidade']
            
            # Determina o campo a ser atualizado e o saldo atual naquele item
            campo_progresso = 'miolos_prontos_retirada_qtd' if is_miolo else 'capas_produzidas_qtd'
            progresso_atual = item.get(campo_progresso, 0) or 0
            
            necessidade = qtd_total_item - progresso_atual
            if necessidade <= 0: continue

            alocacao = min(saldo_a_alocar, necessidade)
            novo_valor = progresso_atual + alocacao
            
            # Atualiza o item no banco
            updates = {
                campo_progresso: novo_valor,
                'updated_at': get_now_iso(),
                'status_item': 'Em Andamento'
            }
            
            # Se for capa, também assume que foi impressa (se o contador estiver menor)
            if not is_miolo and item.get('capas_impressas_qtd', 0) < novo_valor:
                updates['capas_impressas_qtd'] = novo_valor

            supabase_db.execute_with_retry(self.itens_table.update(updates).eq('id', item['id']))
            
            saldo_a_alocar -= alocacao
            alocacoes_realizadas += alocacao
            
            # Log de auditoria para cada alocação
            auditoria_service.log_event('ALOCACAO_AUTOMATICA', {
                'demanda_id': item['demanda_id'],
                'item_id': item['id'],
                'produto_id': produto_id,
                'quantidade': alocacao,
                'tipo': 'MIOLO' if is_miolo else 'CAPA/FINAL'
            }, user_id)

        return alocacoes_realizadas

    def get_demandas_ativas_por_item(self, produto_id: str) -> List[Dict[str, Any]]:
        """
        Retorna demandas ativas que contenham o produto_id (como miolo ou capa).
        Ordenado por prioridade de entrega.
        """
        from nistiprint_shared.services.app_config_service import app_config_service
        miolo_cat_id = str(app_config_service.get_config('producao_miolos_category_id') or '6')
        
        prod_details = product_service.get_by_id(str(produto_id))
        if not prod_details: return []
        
        is_miolo = (str(prod_details.get('categoria_id')) == miolo_cat_id)

        # Busca itens pendentes
        query = self.itens_table.select("*, demanda:demandas_producao(*)").neq('status_item', 'Concluído')
        if is_miolo:
            query = query.eq('id_produto_miolo', produto_id)
        else:
            query = query.eq('produto_id', produto_id)

        response = supabase_db.execute_with_retry(query)
        if not response.data: return []

        # Agrupar por demanda para exibição na UI
        demandas_map = {}
        for item in response.data:
            dem = item.get('demanda')
            if not dem or dem.get('status') in ['CONCLUIDO', 'CANCELADO']:
                continue
                
            did = str(dem['id'])
            if did not in demandas_map:
                demandas_map[did] = self._process_demanda_dict(dem)
                demandas_map[did]['itens_relacionados'] = []
                demandas_map[did]['quantidade_total_pendente'] = 0
                demandas_map[did]['quantidade_total_produzida'] = 0

            item_data = self._process_item_dict(item)
            demandas_map[did]['itens_relacionados'].append(item_data)

            # Consolidação das quantidades para exibição agrupada
            qty_total = float(item_data.get('quantidade', 0))

            # Identifica o campo de progresso correto baseado se é miolo ou capa
            # para exibir o total já produzido desta demanda específica
            if is_miolo:
                qty_produzida = float(item_data.get('miolos_prontos_retirada_qtd', 0))
            else:
                qty_produzida = float(item_data.get('capas_produzidas_qtd', 0))

            demandas_map[did]['quantidade_total_pendente'] += qty_total
            demandas_map[did]['quantidade_total_produzida'] += qty_produzida
        # Ordenar demandas por prioridade
        result = list(demandas_map.values())
        def sort_priority(d):
            is_express = d.get('modalidade_logistica') == 'EXPRESS' or d.get('is_flex', False)
            return (not is_express, d.get('data_entrega', '9999-12-31'), d.get('horario_coleta', '23:59'))
        
        result.sort(key=sort_priority)
        return result

    def get_pending_items_by_miolo(self, miolo_id: str) -> List[Dict[str, Any]]:
        """Alias para get_demandas_ativas_por_item para compatibilidade."""
        return self.get_demandas_ativas_por_item(miolo_id)

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

    def _resolve_miolo_for_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Tenta identificar o produto miolo para um item de demanda se ele não estiver presente.
        """
        # 1. Tenta resolver via BOM (Ficha Técnica)
        if not item.get('id_produto_miolo') and item.get('produto_id'):
            try:
                miolo = bom_service.get_miolo_component_from_bom(int(item['produto_id']))
                if miolo:
                    item['id_produto_miolo'] = miolo.get('id')
                    if not item.get('miolo_nome') and not item.get('miolo_name'):
                        item['miolo_nome'] = miolo.get('nome')
            except Exception as e:
                import logging
                logging.error(f"Erro ao resolver miolo via BOM para produto {item.get('produto_id')}: {e}")
        
        # 2. Se ainda não resolveu, tenta busca por nome parcial (LIKE) na categoria Miolo (ID 6)
        if not item.get('id_produto_miolo') and (item.get('miolo_nome') or item.get('miolo_name')):
            nome_busca = item.get('miolo_nome') or item.get('miolo_name')
            try:
                # Busca produtos da categoria 6 (Miolo) que terminem com o nome fornecido
                # Ex: Busca "AGMT26" -> Encontra "Miolo AGMT26"
                res = supabase_db.table('produtos')\
                    .select('id, nome')\
                    .eq('categoria_id', 6)\
                    .ilike('nome', f'%{nome_busca}')\
                    .limit(1)\
                    .execute()
                
                if res.data:
                    item['id_produto_miolo'] = res.data[0]['id']
                    # Opcional: Atualiza para o nome completo do cadastro para padronização
                    # item['miolo_nome'] = res.data[0]['nome']
            except Exception as e:
                import logging
                logging.error(f"Erro ao resolver miolo via busca parcial para '{nome_busca}': {e}")
        
        return item

demanda_producao_service = DemandaProducaoService()

