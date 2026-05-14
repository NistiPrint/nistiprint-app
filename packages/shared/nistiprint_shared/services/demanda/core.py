"""
Demanda Core Service - CRUD de demandas e métodos de enrich/normalização.

Este módulo contém:
- Inicialização e configuração
- Normalização de status
- Processamento e enrich de dados de demandas
- CRUD básico de demandas
- Criação de demandas a partir de pedidos
- Reserva inteligente de estoque
"""

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
import logging
from nistiprint_shared.utils.date_utils import get_now, get_now_iso

logger = logging.getLogger(__name__)


class DemandaCoreService:
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

    def create_demanda(
        self,
        origem: str,
        order_data: Optional[Dict[str, Any]] = None,
        itens: Optional[List[Dict[str, Any]]] = None,
        canal_venda_id: Optional[int] = None,
        nome_demanda: Optional[str] = None,
        data_entrega_str: Optional[str] = None,
        horario_coleta: Optional[str] = None,
        observacoes: Optional[str] = None,
        user_id: str = 'System',
        tipo_demanda: Optional[str] = None,
        modalidade_logistica: Optional[str] = None,
        classificacao_cliente: Optional[str] = None,
        status: str = 'EM_PRODUCAO',
        pedido_id: Optional[int] = None,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """
        Método unificado para criação de demandas.
        
        Suporta múltiplas origens:
        - 'PLATAFORMA': Pedido de marketplace (Shopee, ML, Amazon, Bling)
        - 'B2B': Venda corporativa
        - 'FULFILLMENT': Reposição para fulfillment
        - 'ESTOQUE': Produção para estoque interno
        
        Args:
            origem: Tipo de origem da demanda
            order_data: Dados do pedido (para origem PLATAFORMA)
            itens: Lista de itens da demanda (para origens manuais)
            canal_venda_id: ID do canal de venda
            nome_demanda: Nome/descrição da demanda
            data_entrega_str: Data de entrega (YYYY-MM-DD)
            horario_coleta: Horário de coleta (HH:MM)
            observacoes: Observações adicionais
            user_id: ID do usuário criador
            tipo_demanda: Tipo da demanda (PLATAFORMA, B2B, FULFILLMENT, ESTOQUE_INTERNO)
            modalidade_logistica: STANDARD, EXPRESS, FULFILLMENT, RETIRADA
            classificacao_cliente: B2C, B2B, INTERNO
            status: Status inicial da demanda
            pedido_id: ID do pedido unificado (para vínculo)
            **kwargs: Argumentos adicionais
            
        Returns:
            Demanda criada ou None se não houve necessidade de criar
        """
        # 1. Se for origem PLATAFORMA, usar create_from_order
        if origem == 'PLATAFORMA' and order_data:
            return self.create_from_order(order_data, user_id)
        
        # 2. Para outras origens, usar criar_demanda_direta
        if not nome_demanda:
            nome_demanda = f"Demanda {origem} - {get_now().strftime('%Y-%m-%d')}"
        
        if not data_entrega_str:
            data_entrega_str = get_now().strftime('%Y-%m-%d')
        
        if not itens:
            itens = []
        
        # Definir tipo_demanda default baseado na origem
        if not tipo_demanda:
            tipo_demanda_map = {
                'B2B': 'B2B',
                'FULFILLMENT': 'FULFILLMENT',
                'ESTOQUE': 'ESTOQUE_INTERNO',
                'PLATAFORMA': 'PLATAFORMA'
            }
            tipo_demanda = tipo_demanda_map.get(origem, 'PLATAFORMA')
        
        # Definir classificacao_cliente default
        if not classificacao_cliente:
            classificacao_cliente_map = {
                'B2B': 'B2B',
                'FULFILLMENT': 'B2C',
                'ESTOQUE': 'INTERNO',
                'PLATAFORMA': 'B2C'
            }
            classificacao_cliente = classificacao_cliente_map.get(origem, 'B2C')
        
        # Definir modalidade_logistica default
        if not modalidade_logistica:
            modalidade_logistica = 'STANDARD'
        
        return self.criar_demanda_direta(
            nome_demanda=nome_demanda,
            canal_venda_id=canal_venda_id,
            data_entrega_str=data_entrega_str,
            lista_de_itens=itens,
            horario_coleta_especifico=horario_coleta,
            observacoes=observacoes,
            user_id=user_id,
            tipo_demanda=tipo_demanda,
            status=status,
            pedido_id=pedido_id,
            modalidade_logistica=modalidade_logistica,
            classificacao_cliente=classificacao_cliente,
            **kwargs
        )

    def _process_demanda_dict(self, demanda: Dict[str, Any], itens: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Adiciona aliases e processa campos para o frontend, incluindo agregações de itens."""
        if not demanda: return None
        d = dict(demanda)
        d['nome'] = d.get('descricao')
        d['manual_priority_score'] = d.get('prioridade_manual', 0)

        if itens is not None:
            def qtd(item, field):
                return max(0, float(item.get(field) or 0))
            # Agregações para o DemandaCard
            d['total_itens'] = sum(qtd(i, 'quantidade') for i in itens)
            d['total_quantidade'] = d['total_itens']

            # Itens finalizados (incluindo parcial) para lógica de status textual e progresso real
            # Este campo representa a finalização manual e explícita no dashboard (real time).
            d['itens_finalizados_total'] = sum(qtd(i, 'finalizados_qtd') for i in itens)

            # Aliase para o frontend (DemandaCard usa itens_fechados ou completed_quantidade para progresso)
            d['itens_finalizados'] = d['itens_finalizados_total']

            # Itens prontos (unidades completas: capa + miolo) - suporte para finalização parcial
            # REGRA: Um item está pronto para retirar quando a CAPA ESTÁ PRONTA (casada com pedido) E o MIOLO ESTÁ PRONTO.
            d['itens_prontos_total'] = sum(min(qtd(i, 'capas_prontas_retirada_qtd'), qtd(i, 'miolos_prontos_retirada_qtd')) for i in itens)
            # Aliase para o frontend usar o campo itens_concluidos como "unidades prontas"
            d['itens_concluidos'] = d['itens_prontos_total']

            d['capas_impressas_qtd'] = sum(qtd(i, 'capas_impressas_qtd') for i in itens)
            d['capas_produzidas_qtd'] = sum(qtd(i, 'capas_produzidas_qtd') for i in itens)
            d['capas_prontas_retirada_qtd'] = sum(qtd(i, 'capas_prontas_retirada_qtd') for i in itens)
            d['miolos_produzidos_qtd'] = sum(qtd(i, 'miolos_prontos_retirada_qtd') for i in itens)
            d['miolos_prontos_retirada_qtd'] = d['miolos_produzidos_qtd']

            # completed_quantidade agora representa o progresso de FINALIZAÇÃO MANUAL para o frontend
            d['completed_quantidade'] = d['itens_finalizados_total']

            # quantidade_coletada_total mantém o valor da tabela entrega_producao (coleta física/faturamento)
            d['quantidade_coletada_total'] = d.get('quantidade_coletada_total', 0)

            # Itens em fechamento: soma do menor valor entre exp. capas e exp. miolos de cada item
            # Representa itens que a expedição está processando em paralelo (READY TO CLOSE)
            d['itens_em_fechamento'] = sum(
                min(qtd(i, 'expedicao_capas_retiradas_qtd'), qtd(i, 'expedicao_miolos_retirados_qtd'))
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

    def enrich_items_with_stock(self, itens: List[Dict[str, Any]], deposito_id: Any = None) -> List[Dict[str, Any]]:
        """
        Adiciona informações de saldo de estoque (miolo e capas) aos itens em lote.
        Otimizado para REDUZIR query N+1 via batch fetching completo.
        """
        if not itens: return []

        # Se não for fornecido um depósito, obter o padrão para produção
        if deposito_id is None:
            from nistiprint_shared.services.app_config_service import app_config_service
            deposito_id = app_config_service.get_config('default_production_deposit_id')

        # 1. Coletar IDs de Miolos e Produtos Pais
        miolo_ids = set()
        produto_pai_ids = set()

        for i in itens:
            if i.get('id_produto_miolo'):
                miolo_ids.add(str(i['id_produto_miolo']))
            if i.get('produto_id'):
                produto_pai_ids.add(str(i['produto_id']))

        # 2. Buscar saldos de Miolos (Batch)
        saldos_miolos = {}
        if miolo_ids:
            try:
                saldos_miolos = estoque_service.get_saldos_em_lote(list(miolo_ids), deposito_id)
            except Exception as e:
                print(f"Erro não fatal ao buscar estoque de miolos: {e}")

        # 3. Buscar BOMs e IDENTIFICAR ROLES em Lote
        pai_component_map = {} 
        all_component_ids = set()
        boms_by_pai = {}

        if produto_pai_ids:
            try:
                # Batch fetch BOMs for all parent products
                boms_by_pai = bom_service.get_bom_for_multiple_products(list(produto_pai_ids))
                for components in boms_by_pai.values():
                    for comp in components:
                        all_component_ids.add(str(comp.componente_id))
            except Exception as e:
                print(f"Erro ao buscar BOMs em lote: {e}")

        # 4. Batch Identify Roles (Otimizado)
        # Em vez de chamar identify_product_role N vezes, buscamos as categorias dos componentes em uma única query
        component_role_map = {}
        if all_component_ids:
            try:
                from nistiprint_shared.services.app_config_service import app_config_service
                miolo_cat = str(app_config_service.get_config('producao_miolos_category_id') or '6')
                capa_cat = str(app_config_service.get_config('producao_capas_category_id') or '12')
                impressao_cat = str(app_config_service.get_config('producao_capas_impressas_category_id') or '13')

                # Busca categorias e nomes de todos os componentes de uma vez
                comp_data_res = supabase_db.table('produtos').select('id, categoria_id, nome').in_('id', list(all_component_ids)).execute()

                for p in comp_data_res.data:
                    cid = str(p['id'])
                    cat_id = str(p.get('categoria_id'))
                    nome = p.get('nome', '').lower()

                    role = 'OUTRO'
                    if cat_id == miolo_cat or 'miolo' in nome:
                        role = 'MIOLO'
                    elif cat_id == capa_cat:
                        role = 'CAPA_ACABADA'
                    elif cat_id == impressao_cat:
                        role = 'CAPA_IMPRESSAO'
                    elif 'capa' in nome:
                        role = 'CAPA_IMPRESSAO' if 'impress' in nome else 'CAPA_ACABADA'

                    component_role_map[cid] = role
            except Exception as e:
                print(f"Erro ao identificar roles em lote: {e}")

        # 5. Mapeap componentes por pai e role
        all_target_ids = set()
        for p_id_int, components in boms_by_pai.items():
            p_id_str = str(p_id_int)
            pai_component_map[p_id_str] = {}
            for comp in components:
                c_id_str = str(comp.componente_id)
                role = component_role_map.get(c_id_str, 'OUTRO')
                if role in ['CAPA_ACABADA', 'CAPA_IMPRESSAO']:
                    pai_component_map[p_id_str][role] = c_id_str
                    all_target_ids.add(c_id_str)

        # 6. Buscar saldos dos componentes encontrados (Capas/Impressão) em Lote
        saldos_extra = {}
        if all_target_ids:
            try:
                saldos_extra = estoque_service.get_saldos_em_lote(list(all_target_ids), deposito_id)
            except Exception as e:
                print(f"Erro não fatal ao buscar estoque de capas: {e}")

        # 7. Injetar nos itens
        for item in itens:
            # Miolo
            m_id = str(item.get('id_produto_miolo'))
            if m_id in saldos_miolos:
                item['estoque_disponivel_miolo'] = saldos_miolos[m_id].get('quantidade_disponivel', 0)
            else:
                item['estoque_disponivel_miolo'] = 0

            # Capa e Impressão via Mapa BOM
            p_id = str(item.get('produto_id'))
            bom_map = pai_component_map.get(p_id, {})

            c_id = bom_map.get('CAPA_ACABADA')
            if c_id and c_id in saldos_extra:
                item['estoque_disponivel_capa'] = saldos_extra[c_id].get('quantidade_disponivel', 0)
            else:
                item['estoque_disponivel_capa'] = 0

            i_id = bom_map.get('CAPA_IMPRESSAO')
            if i_id and i_id in saldos_extra:
                item['estoque_disponivel_impressao'] = saldos_extra[i_id].get('quantidade_disponivel', 0)
            else:
                item['estoque_disponivel_impressao'] = 0

        return itens
    def _enrich_items_with_stock(self, itens: List[Dict[str, Any]], deposito_id: Any = None) -> List[Dict[str, Any]]:
        """Alias para backward compatibility."""
        return self.enrich_items_with_stock(itens, deposito_id)

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

    def get_bom_components(self, produto_id: str) -> List[Any]:
        """Obtém componentes da BOM para um produto."""
        return bom_service.get_bom_for_produto(produto_id)

    def _get_aggregated_demandas(self, response_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not response_data: return []

        valid_rows = []
        for idx, row in enumerate(response_data):
            if not isinstance(row, dict):
                logger.warning("Ignoring invalid demanda row at index %s: expected dict, got %s", idx, type(row).__name__)
                continue
            if row.get('id') is None:
                logger.warning("Ignoring demanda row without id at index %s", idx)
                continue
            valid_rows.append(row)

        if not valid_rows:
            return []

        demanda_ids = [row['id'] for row in valid_rows]
        # Busca itens para todas as demandas da página de uma vez
        itens_res = supabase_db.execute_with_retry(self.itens_table.select("*").in_('demanda_id', demanda_ids))

        # Agrupa itens por demanda_id
        itens_by_demanda = {}
        for item in (itens_res.data or []):
            if not isinstance(item, dict):
                logger.warning("Ignoring invalid item row while aggregating demandas: %s", type(item).__name__)
                continue
            did = item.get('demanda_id')
            if did is None:
                continue
            if did not in itens_by_demanda: itens_by_demanda[did] = []
            itens_by_demanda[did].append(item)

        # Buscar totais de coleta para todas as demandas de uma vez
        coletas_res = supabase_db.execute_with_retry(
            supabase_db.table('entrega_producao')
            .select('demanda_id, quantidade')
            .in_('demanda_id', demanda_ids)
        )
        coleta_totals_map = {}
        for row in (coletas_res.data or []):
            if not isinstance(row, dict):
                logger.warning("Ignoring invalid coleta row while aggregating demandas: %s", type(row).__name__)
                continue
            did = row.get('demanda_id')
            if did is None:
                continue
            coleta_totals_map[did] = coleta_totals_map.get(did, 0) + float(row.get('quantidade') or 0)

        result = []
        for row in valid_rows:
            canal_venda = row.get('canal_venda')
            if not isinstance(canal_venda, dict):
                canal_venda = {}
            plataformas = canal_venda.get('plataformas')
            if not isinstance(plataformas, dict):
                plataformas = {}

            canal_nome = canal_venda.get('nome')
            canal_color = canal_venda.get('color')
            canal_plataforma = plataformas.get('nome')

            # Injetar o total coletado na row antes de processar
            row_with_totals = {**row, 'quantidade_coletada_total': coleta_totals_map.get(row['id'], 0)}

            processed = self._process_demanda_dict(
                {
                    **row_with_totals,
                    'canal_venda_nome': canal_nome,
                    'canal_venda_color': canal_color,
                    'canal_venda_plataforma': canal_plataforma
                },
                itens_by_demanda.get(row['id'], [])
            )
            if not isinstance(processed, dict):
                logger.warning("Ignoring invalid processed demanda for id=%s", row.get('id'))
                continue
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
        demanda.update(self._get_pedidos_origem_metadata(internal_id))

        return demanda

    def _get_pedidos_origem_metadata(self, demanda_internal_id: int) -> Dict[str, Any]:
        """
        Retorna a rastreabilidade da demanda a partir da tabela pivot demandas_pedidos.
        Este Ã© o contrato usado pelo frontend para a lista de pedidos, chunks e NF.
        """
        empty = {
            'pedidos_origem': [],
            'pedidos_origem_chunks': [],
            'pedidos_origem_por_bling': []
        }
        if not demanda_internal_id:
            return empty

        try:
            pivot_res = supabase_db.table('demandas_pedidos') \
                .select('pedido_id, created_at') \
                .eq('demanda_id', demanda_internal_id) \
                .order('created_at') \
                .execute()
            pivot_rows = pivot_res.data or []
            pedido_ids = [row.get('pedido_id') for row in pivot_rows if row.get('pedido_id')]
            if not pedido_ids:
                return empty

            pedidos_res = supabase_db.table('pedidos').select('''
                id,
                numero_pedido,
                codigo_pedido_externo,
                origem,
                cliente_nome,
                canal_venda_id,
                situacao_pedido_id,
                data_venda,
                total_pedido,
                is_flex,
                bling_integration_id,
                marketplace_integration_id,
                pedido_bling_id
            ''').in_('id', pedido_ids).execute()
            pedidos = pedidos_res.data or []
            pedidos_by_id = {pedido.get('id'): pedido for pedido in pedidos}

            pedido_bling_ids = [
                pedido.get('pedido_bling_id')
                for pedido in pedidos
                if pedido.get('pedido_bling_id')
            ]
            bling_by_id = {}
            if pedido_bling_ids:
                bling_res = supabase_db.table('pedidos_bling').select('''
                    id,
                    bling_id,
                    numero_pedido,
                    numero_loja,
                    bling_integration_id,
                    raw_payload
                ''').in_('id', pedido_bling_ids).execute()
                bling_by_id = {row.get('id'): row for row in (bling_res.data or [])}

            integration_ids = sorted({
                int(pedido.get('bling_integration_id'))
                for pedido in pedidos
                if pedido.get('bling_integration_id') is not None
            })
            integration_labels = {}
            if integration_ids:
                integrations_res = supabase_db.table('installed_integrations') \
                    .select('id, instance_name') \
                    .in_('id', integration_ids) \
                    .execute()
                integration_labels = {
                    int(row.get('id')): row.get('instance_name') or f"Conta Bling {row.get('id')}"
                    for row in (integrations_res.data or [])
                    if row.get('id') is not None
                }

            pedidos_origem = []
            for pedido_id in pedido_ids:
                pedido = pedidos_by_id.get(pedido_id)
                if not pedido:
                    continue

                bling_data = bling_by_id.get(pedido.get('pedido_bling_id')) or {}
                raw_payload = bling_data.get('raw_payload') or {}
                bling_order_id = bling_data.get('bling_id') or raw_payload.get('id')
                bling_numero = bling_data.get('numero_pedido') or raw_payload.get('numero') or pedido.get('numero_pedido')
                bling_integration_id = pedido.get('bling_integration_id') or bling_data.get('bling_integration_id')
                try:
                    bling_integration_key = int(bling_integration_id) if bling_integration_id is not None else None
                except (TypeError, ValueError):
                    bling_integration_key = bling_integration_id

                pedidos_origem.append({
                    'pedido_id': pedido.get('id'),
                    'numero_pedido': pedido.get('numero_pedido'),
                    'codigo_pedido_externo': pedido.get('codigo_pedido_externo'),
                    'origem': pedido.get('origem'),
                    'cliente_nome': pedido.get('cliente_nome'),
                    'canal_venda_id': pedido.get('canal_venda_id'),
                    'situacao_pedido_id': pedido.get('situacao_pedido_id'),
                    'data_venda': pedido.get('data_venda'),
                    'total_pedido': pedido.get('total_pedido'),
                    'is_flex': pedido.get('is_flex'),
                    'bling_integration_id': bling_integration_id,
                    'bling_account_label': integration_labels.get(bling_integration_key),
                    'bling_order_id': bling_order_id,
                    'bling_numero': bling_numero,
                    'pedido_bling_id': pedido.get('pedido_bling_id')
                })

            codigos_externos = [
                str(pedido.get('codigo_pedido_externo')).strip()
                for pedido in pedidos_origem
                if pedido.get('codigo_pedido_externo')
            ]
            chunks = [
                ';'.join(codigos_externos[index:index + 100])
                for index in range(0, len(codigos_externos), 100)
            ]

            grupos_map = {}
            for pedido in pedidos_origem:
                group_key = pedido.get('bling_integration_id') or 'sem_conta'
                if group_key not in grupos_map:
                    grupos_map[group_key] = {
                        'bling_integration_id': pedido.get('bling_integration_id'),
                        'account_label': pedido.get('bling_account_label') or 'Conta Bling nao identificada',
                        'pedidos': []
                    }
                grupos_map[group_key]['pedidos'].append(pedido)

            return {
                'pedidos_origem': pedidos_origem,
                'pedidos_origem_chunks': chunks,
                'pedidos_origem_por_bling': list(grupos_map.values())
            }
        except Exception as e:
            logger.error("Erro ao montar pedidos de origem da demanda %s: %s", demanda_internal_id, e, exc_info=True)
            return empty

    def _resolve_miolo_for_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve e associa o ID do produto miolo para um item da demanda.
        Tenta primeiro via BOM do produto pai, depois por busca parcial na categoria Miolo.
        """
        # 1. Se já tem ID do miolo, não faz nada
        if item.get('id_produto_miolo'):
            return item

        # 2. Tenta resolver via BOM do produto pai
        produto_pai_id = item.get('produto_id')
        if produto_pai_id:
            try:
                from nistiprint_shared.services.bom_service import bom_service
                from nistiprint_shared.services.product_service import product_service

                # Busca componentes da BOM
                componentes = bom_service.get_bom_for_produto(produto_pai_id)
                for comp in componentes:
                    comp_id_str = str(comp.componente_id)
                    # Identifica o papel do componente
                    role = product_service.identify_product_role(comp_id_str)
                    if role == 'MIOLO_ACABADO':
                        # Encontrou o miolo!
                        miolo = product_service.get_by_id(comp_id_str)
                        if miolo:
                            item['id_produto_miolo'] = miolo.get('id')
                            if not item.get('miolo_nome') and not item.get('miolo_name'):
                                item['miolo_nome'] = miolo.get('nome')
                        break
            except Exception as e:
                import logging
                logging.error(f"Erro ao resolver miolo via BOM para produto {item.get('produto_id')}: {e}")

        # 3. Se ainda não resolveu, tenta busca por nome parcial (LIKE) na categoria Miolo (ID 6)
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

    def create_from_order(self, order_data: Dict[str, Any], user_id='System', **kwargs) -> Dict[str, Any]:
        """
        Gera uma demanda de produção a partir de um pedido.
        Aceita is_flex, modalidade_logistica e canal_venda_id via kwargs.
        Se não fornecidos, tenta derivar do banco 'pedidos'.
        """
        # 1. Resolver metadados básicos
        is_flex = kwargs.get('is_flex')
        modalidade = kwargs.get('modalidade_logistica')
        canal_venda_id = kwargs.get('canal_venda_id')

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

        # Se não vieram via kwargs, tenta ler do banco 'pedidos'
        if is_flex is None or modalidade is None or canal_venda_id is None:
            try:
                pedido_db = supabase_db.table('pedidos')\
                    .select('is_flex, modalidade_logistica, canal_venda_id')\
                    .eq('codigo_pedido_externo', external_id)\
                    .maybe_single().execute().data
                if pedido_db:
                    if is_flex is None: is_flex = pedido_db.get('is_flex')
                    if modalidade is None: modalidade = pedido_db.get('modalidade_logistica')
                    if canal_venda_id is None: canal_venda_id = pedido_db.get('canal_venda_id')
            except Exception as e:
                import logging
                logging.error(f"⚠️ Erro ao buscar metadados do pedido {external_id} no banco: {e}")

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

        # 2. Filter Deduplication
        filtered_orders = order_tracker_service.filter_processed_items(orders_list, plataforma)
        if not filtered_orders:
            # All items processed
            existing = self.demandas_table.select("id").eq('demanda_id', external_id).execute()
            if existing.data:
                return self.get_demanda_with_itens(existing.data[0]['id'])
            return None

        # 3. Process Remaining Items
        remaining_items = filtered_orders[0]['items']

        # Prepare content for new demand
        contato_nome = order_data.get('contato', {}).get('nome', 'Cliente Desconhecido')
        nome_demanda = f"Pedido {order_data.get('numero') or external_id} - {contato_nome}"

        data_entrega = order_data.get('dataPrevista') or order_data.get('data') or get_now().strftime('%Y-%m-%d')
        if isinstance(data_entrega, str) and 'T' in data_entrega:
            data_entrega = data_entrega.split('T')[0]

        itens_demanda = []
        remaining_map = {(i['sku_externo'], i['item_externo_id']): i['quantidade'] for i in remaining_items}

        for item in order_data.get('itens', []):
            sku = str(item.get('codigo') or item.get('sku') or '')
            item_ext_id = str(item.get('id') or item.get('order_item_id') or sku)

            key = (sku, item_ext_id)
            if key in remaining_map:
                qty_to_process = remaining_map[key]
                nome_externo = item.get('descricao') or item.get('name')
                resolved_prod = product_service.resolve_variation(sku, plataforma, nome_externo)
                prod_id = resolved_prod['id'] if resolved_prod else None

                itens_demanda.append({
                    'sku': sku,
                    'descricao': nome_externo,
                    'quantidade': qty_to_process,
                    'produto_id': prod_id,
                    '_item_externo_id': item_ext_id
                })

        if not itens_demanda:
            return None

        observacoes = f"Importado automaticamente. ID Externo: {external_id}"
        if 'observacoes' in order_data:
             observacoes += f"\nObs Pedido: {order_data['observacoes']}"

        pedido_id_vincular = None
        try:
            pedido_res = supabase_db.table('pedidos')\
                .select('id')\
                .eq('codigo_pedido_externo', str(external_id))\
                .execute()
            if pedido_res.data:
                pedido_id_vincular = pedido_res.data[0]['id']
        except Exception as find_err:
            import logging
            logging.error(f"Erro ao buscar pedido unificado para vínculo: {find_err}")

        # 4. Create Demand
        new_demanda = self.criar_demanda_direta(
            nome_demanda=nome_demanda,
            canal_venda_id=canal_venda_id,
            data_entrega_str=data_entrega,
            lista_de_itens=itens_demanda,
            demanda_id=external_id,
            pedido_numero=str(order_data.get('numero') or external_id),
            pedido_id=pedido_id_vincular,
            observacoes=observacoes,
            user_id=user_id,
            tipo_demanda='PLATAFORMA',
            is_flex=is_flex,
            modalidade_logistica=modalidade
        )

        # 5. Register Processed Items
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

    def _resolver_horario_coleta(
        self,
        canal_venda_id: Optional[int],
        modalidade_logistica: str,
        horario_coleta_especifico: Optional[str] = None
    ) -> Optional[str]:
        """
        Resolve horário de coleta com base na regra de precedência.
        
        PRECEDÊNCIA:
        1. horario_coleta_especifico (se fornecido explicitamente)
        2. regras_logisticas_canal.horario_limite WHERE (canal_venda_id, modalidade) — FONTE CANÔNICA
        3. canais_venda.horario_coleta — FALLBACK LEGADO
        4. None — Se nada configurado
        
        Args:
            canal_venda_id: ID do canal de venda
            modalidade_logistica: STANDARD, EXPRESS, FULFILLMENT, RETIRADA
            horario_coleta_especifico: Horário explícito (opcional)
        
        Returns:
            Horário de coleta (HH:MM) ou None
        """
        # Prioridade 1: Horário explícito
        if horario_coleta_especifico:
            return horario_coleta_especifico
        
        # Prioridade 2: Buscar em regras_logisticas_canal
        if canal_venda_id and modalidade_logistica:
            try:
                response = supabase_db.table('regras_logisticas_canal').select('horario_limite') \
                    .eq('canal_venda_id', canal_venda_id) \
                    .eq('modalidade', modalidade_logistica) \
                    .maybe_single() \
                    .execute()
                
                if response and response.data and response.data.get('horario_limite'):
                    horario = response.data['horario_limite']
                    # Converter time para string HH:MM se necessário
                    if hasattr(horario, 'isoformat'):
                        return horario.strftime('%H:%M')
                    return str(horario)
            except Exception as e:
                logger.warning(
                    "Erro ao buscar horario_limite em regras_logisticas_canal: %s",
                    str(e)
                )
        
        # Prioridade 3: Fallback para canais_venda.horario_coleta (LEGADO)
        if canal_venda_id:
            try:
                response = supabase_db.table('canais_venda').select('horario_coleta') \
                    .eq('id', canal_venda_id) \
                    .maybe_single() \
                    .execute()
                
                if response.data and response.data.get('horario_coleta'):
                    horario = response.data['horario_coleta']
                    logger.warning(
                        "Horário de coleta derivado de canais_venda.horario_coleta (LEGADO). "
                        "Considere configurar regras_logisticas_canal para (canal=%s, modalidade=%s).",
                        canal_venda_id,
                        modalidade_logistica
                    )
                    if hasattr(horario, 'isoformat'):
                        return horario.strftime('%H:%M')
                    return str(horario)
            except Exception as e:
                logger.warning(
                    "Erro ao buscar horario_coleta em canais_venda: %s",
                    str(e)
                )
        
        # Prioridade 4: Nenhum configurado
        return None

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

        # Resolver horário de coleta com base na regra de precedência
        # 1. horario_coleta_especifico > 2. regras_logisticas_canal > 3. canais_venda > 4. None
        horario_coleta_resolvido = self._resolver_horario_coleta(
            canal_venda_id,
            modalidade_logistica,
            horario_coleta_especifico
        )

        demanda_payload = {
            'demanda_id': provided_id,
            'descricao': nome_demanda,
            'data_entrega': data_entrega_str,
            'status': status,
            'canal_venda_id': canal_venda_id,
            'horario_coleta': horario_coleta_resolvido,
            'tipo_demanda': tipo_demanda,
            'observacoes': observacoes or None,
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
                # Agenda a reserva inteligente para processamento ASSÍNCRONO na fila.
                # O worker irá gerar a previsão de consumo e executar a lógica Waterfall (estoque.py)
                # sem travar o request HTTP de criação da demanda.
                from nistiprint_shared.services.demanda_alocacao.queue import demanda_alocacao_queue_service

                agendamento_result = demanda_alocacao_queue_service.agendar_reserva_inteligente(
                    demanda_id=new_demanda_id,
                    itens_payload=itens_payload,
                    user_id=user_id
                )

                # Armazena o correlation_id para rastreamento futuro
                if agendamento_result.get('success'):
                    self.update_demanda_details(new_demanda_id, {
                        'dados_adicionais': {
                            'reserva_inteligente_agendada': True,
                            'reserva_inteligente_correlation_id': agendamento_result.get('correlation_id'),
                            'reserva_inteligente_agendada_em': get_now_iso()
                        }
                    }, user_id)
                    print(f"DEBUG: Reserva inteligente agendada assincronamente para demanda {new_demanda_id}")

            except Exception as e:
                print(f"Erro ao agendar reserva inteligente para demanda {new_demanda_id}: {e}")
                # Fallback: Se falhar o agendamento, tenta reserva simples síncrona para não deixar sem nada
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

    def atualizar_demanda_completa(self, demanda_id: str, updates: Dict[str, Any], itens: List[Dict[str, Any]], user_id: str = 'System') -> Dict[str, Any]:
        """
        Atualiza demanda e seus itens em transação atômica.
        """
        # 0. Resolver o ID interno (PK) se necessário
        demanda_res = supabase_db.execute_with_retry(self.demandas_table.select("id").eq('id', demanda_id))
        if not demanda_res.data:
            demanda_res = supabase_db.execute_with_retry(self.demandas_table.select("id").eq('demanda_id', demanda_id))
            if not demanda_res.data:
                raise ValueError(f"Demanda {demanda_id} não encontrada")

        internal_pk = demanda_res.data[0]['id']

        # 1. Atualizar cabeçalho da demanda
        self.update_demanda_details(demanda_id, updates, user_id)

        # 2. Atualizar itens (UPSERT)
        if itens:
            for item in itens:
                if 'id' in item and item['id']:
                    # UPDATE existente
                    item_updates = {
                        'descricao': item.get('descricao'),
                        'quantidade': item.get('quantidade'),
                        'sku': item.get('sku'),
                        'miolo_nome': item.get('miolo_nome'),
                        'id_produto_miolo': item.get('id_produto_miolo'),
                        'updated_at': get_now_iso()
                    }
                    supabase_db.execute_with_retry(self.itens_table.update(item_updates).eq('id', item['id']))
                else:
                    # INSERT novo
                    item['demanda_id'] = internal_pk
                    item['created_at'] = get_now_iso()
                    item['updated_at'] = get_now_iso()
                    supabase_db.execute_with_retry(self.itens_table.insert(item))

        return self.get_demanda_with_itens(internal_pk)

    def deletar_demanda(self, demanda_id: str, user_id='System') -> bool:
        """Deleta uma demanda e seus itens."""
        try:
            # 0. Resolver o ID interno (PK) se necessário
            demanda_res = supabase_db.execute_with_retry(self.demandas_table.select("id").eq('id', demanda_id))
            if not demanda_res.data:
                demanda_res = supabase_db.execute_with_retry(self.demandas_table.select("id").eq('demanda_id', demanda_id))
                if not demanda_res.data:
                    return False

            internal_pk = demanda_res.data[0]['id']

            # 1. Deletar itens
            supabase_db.execute_with_retry(self.itens_table.delete().eq('demanda_id', internal_pk))

            # 2. Deletar demanda
            supabase_db.execute_with_retry(self.demandas_table.delete().eq('id', internal_pk))

            # 3. Log auditoria
            auditoria_service.log_event('DEMANDA_EXCLUIDA', {'demanda_id': internal_pk}, user_id)

            return True
        except Exception as e:
            print(f"Erro ao deletar demanda {demanda_id}: {e}")
            return False


# Instância singleton para compatibilidade
demanda_core_service = DemandaCoreService()
