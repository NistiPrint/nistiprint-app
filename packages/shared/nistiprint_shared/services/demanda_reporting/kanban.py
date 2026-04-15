from datetime import datetime
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


class DemandaReportingKanbanService:
    def __init__(self):
        self.demandas_table = supabase_db.table('demandas_producao')
        self.itens_table = supabase_db.table('itens_demanda')

    def _normalize_status(self, status: str) -> str:
        """Converte status legados para o novo padrão Upper Snake Case do banco de dados."""
        if not status:
            return 'AGUARDANDO'

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
        if not demanda:
            return None
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
            d['itens_finalizados_total'] = sum(qtd(i, 'finalizados_qtd') for i in itens)
            d['itens_finalizados'] = d['itens_finalizados_total']

            # Itens prontos (unidades completas: capa + miolo)
            d['itens_prontos_total'] = sum(min(qtd(i, 'capas_prontas_retirada_qtd'), qtd(i, 'miolos_prontos_retirada_qtd')) for i in itens)
            d['itens_concluidos'] = d['itens_prontos_total']

            d['capas_impressas_qtd'] = sum(qtd(i, 'capas_impressas_qtd') for i in itens)
            d['capas_produzidas_qtd'] = sum(qtd(i, 'capas_produzidas_qtd') for i in itens)
            d['capas_prontas_retirada_qtd'] = sum(qtd(i, 'capas_prontas_retirada_qtd') for i in itens)
            d['miolos_produzidos_qtd'] = sum(qtd(i, 'miolos_prontos_retirada_qtd') for i in itens)
            d['miolos_prontos_retirada_qtd'] = d['miolos_produzidos_qtd']

            d['completed_quantidade'] = d['itens_finalizados_total']
            d['quantidade_coletada_total'] = d.get('quantidade_coletada_total', 0)

            d['itens_em_fechamento'] = sum(
                min(qtd(i, 'expedicao_capas_retiradas_qtd'), qtd(i, 'expedicao_miolos_retirados_qtd'))
                for i in itens
            )

            progresso = 0
            if d['total_itens'] > 0:
                progresso = round((d['itens_finalizados_total'] / d['total_itens']) * 100)
            d['progresso_percentual'] = progresso

            if d['total_itens'] > 0:
                d['readiness_score'] = round(((d['capas_impressas_qtd'] + d['miolos_produzidos_qtd']) / (2 * d['total_itens'])) * 100)
            else:
                d['readiness_score'] = 0

            d['is_stuck'] = False
            if d['status'] == 'Em Produção' and d['total_itens'] > 0:
                gap_capas = d['capas_impressas_qtd'] - d['capas_produzidas_qtd']
                if gap_capas > (d['total_itens'] * 0.5) and d['itens_concluidos'] < (d['total_itens'] * 0.2):
                    d['is_stuck'] = True

            if itens:
                first_item = itens[0]
                d['id_produto_miolo'] = first_item.get('id_produto_miolo')
                d['produto_miolo_nome'] = first_item.get('produto_miolo_nome') or first_item.get('miolo_nome')

        if d.get('dados_adicionais'):
            dados_adicionais = d['dados_adicionais']
            if isinstance(dados_adicionais, dict):
                empresa_fields = [
                    'empresa_cliente_nome', 'empresa_wire_o_cor', 'empresa_elastico_cor',
                    'empresa_interacao_status', 'empresa_pedido_plataforma_numero',
                    'empresa_responsavel_id', 'empresa_responsavel_nome'
                ]
                for field in empresa_fields:
                    if field in dados_adicionais:
                        d[field] = dados_adicionais[field]

            for k, v in dados_adicionais.items():
                if k not in d or d[k] is None:
                    d[k] = v
        return d

    def _process_item_dict(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Adiciona aliases e processa campos para o frontend."""
        if not item:
            return None
        i = dict(item)
        i['item_descricao'] = i.get('descricao')
        i['quantidade_total'] = i.get('quantidade')
        i['miolo_name'] = i.get('miolo_nome')

        # Merge legado de dados_adicionais
        if i.get('dados_adicionais'):
            for k, v in i['dados_adicionais'].items():
                if k not in i or i[k] is None:
                    i[k] = v
        return i

    def _get_aggregated_demandas(self, response_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not response_data:
            return []

        demanda_ids = [row['id'] for row in response_data]
        itens_res = supabase_db.execute_with_retry(self.itens_table.select("*").in_('demanda_id', demanda_ids))

        # OTIMIZAÇÃO: Coletar nomes de miolos em lote se estiverem faltando
        missing_miolo_ids = set()
        for i in itens_res.data:
            if i.get('id_produto_miolo') and not i.get('miolo_nome'):
                missing_miolo_ids.add(str(i['id_produto_miolo']))
        
        miolo_names_map = {}
        if missing_miolo_ids:
            try:
                # Otimização via ProductService se tiver batch mode, ou via query direta
                prods_res = supabase_db.table('produtos').select('id, nome').in_('id', list(missing_miolo_ids)).execute()
                for p in prods_res.data:
                    miolo_names_map[str(p['id'])] = p['nome']
            except: pass

        itens_by_demanda = {}
        for item in itens_res.data:
            processed_item = self._process_item_dict(item)
            # Injetar nome do miolo se faltava e buscamos em lote
            mid = str(processed_item.get('id_produto_miolo'))
            if not processed_item.get('miolo_name') and mid in miolo_names_map:
                processed_item['miolo_nome'] = miolo_names_map[mid]
                processed_item['miolo_name'] = miolo_names_map[mid]

            did = item['demanda_id']
            if did not in itens_by_demanda:
                itens_by_demanda[did] = []
            itens_by_demanda[did].append(processed_item)

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

            row['quantidade_coletada_total'] = coleta_totals_map.get(row['id'], 0)

            # Passar itens processados para o helper
            demanda_itens = itens_by_demanda.get(row['id'], [])
            
            processed = self._process_demanda_dict(
                {
                    **row,
                    'canal_venda_nome': canal_nome,
                    'canal_venda_color': canal_color,
                    'canal_venda_plataforma': canal_plataforma
                },
                demanda_itens
            )
            # Garantir que itens fiquem no dict para evitar re-fetch
            processed['itens'] = demanda_itens
            result.append(processed)
        return result

    def get_all_demandas(self) -> List[Dict[str, Any]]:
        response = supabase_db.execute_with_retry(
            self.demandas_table.select("*, canal_venda:canais_venda(nome, color, plataformas(nome))").order('created_at', desc=True)
        )
        return self._get_aggregated_demandas(response.data)

    def get_demandas_by_status(self, status_list: List[str], product_id=None) -> List[Dict[str, Any]]:
        if isinstance(status_list, list):
            status_list = [self._normalize_status(s) for s in status_list]
        else:
            status_list = self._normalize_status(status_list)

        query = self.demandas_table.select("*, canal_venda:canais_venda(nome, color, plataformas(nome))")
        if isinstance(status_list, list):
            query = query.in_('status', status_list)
        else:
            query = query.eq('status', status_list)
        response = supabase_db.execute_with_retry(query)
        return self._get_aggregated_demandas(response.data)

    def get_items_for_multiple_demandas(self, demanda_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Busca itens de múltiplas demandas em uma única chamada e retorna mapeado por demanda_id."""
        if not demanda_ids:
            return {}
        response = supabase_db.execute_with_retry(
            self.itens_table.select("*").in_('demanda_id', [str(id) for id in demanda_ids])
        )

        # OTIMIZAÇÃO: Coletar nomes de miolos em lote se estiverem faltando
        missing_miolo_ids = set()
        for i in response.data:
            if i.get('id_produto_miolo') and not i.get('miolo_nome'):
                missing_miolo_ids.add(str(i['id_produto_miolo']))
        
        miolo_names_map = {}
        if missing_miolo_ids:
            try:
                prods_res = supabase_db.table('produtos').select('id, nome').in_('id', list(missing_miolo_ids)).execute()
                for p in prods_res.data:
                    miolo_names_map[str(p['id'])] = p['nome']
            except: pass

        mapping = {}
        for item in response.data:
            processed = self._process_item_dict(item)
            
            # Injetar nome do miolo se faltava
            mid = str(processed.get('id_produto_miolo'))
            if not processed.get('miolo_name') and mid in miolo_names_map:
                processed['miolo_nome'] = miolo_names_map[mid]
                processed['miolo_name'] = miolo_names_map[mid]

            did = str(item['demanda_id'])
            if did not in mapping:
                mapping[did] = []
            mapping[did].append(processed)
        return mapping

    def get_painel_producao_setores(self, setor_id_ou_nome):
        """Retorna dados do painel de produção organizado por setores/colunas Kanban."""
        # Busca demandas ativas (status normalizados para Upper Snake Case)
        # Exclui: Finalizado (CONCLUIDO), Coletado (COLETADO), Cancelado (CANCELADO)
        demandas_ativas = self.get_demandas_by_status(['AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL'])

        # Coletar todos os itens para enriquecer com estoque em lote
        all_items_flat = []
        itens_mapping = {}
        
        for d in demandas_ativas:
            # Pega os itens que já foram processados e anexados à demanda
            itens = d.get('itens', [])
            all_items_flat.extend(itens)
            itens_mapping[str(d['id'])] = itens

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

        # Obter o depósito padrão para produção
        deposito_id = app_config_service.get_config('default_production_deposit_id')

        # Enriquecer itens com dados de estoque (Delegado para o Core Service Otimizado)
        from nistiprint_shared.services.demanda.core import demanda_core_service
        enriched_items = demanda_core_service.enrich_items_with_stock(all_items_flat, deposito_id)

        # Remapear enriquecidos de volta para o itens_mapping
        itens_mapping = {}
        for item in enriched_items:
            did = str(item['demanda_id'])
            if did not in itens_mapping:
                itens_mapping[did] = []
            itens_mapping[did].append(item)

        for d in demandas_ativas:
            did_str = str(d['id'])
            itens = itens_mapping.get(did_str, [])

            # Pular demandas finalizadas, coletadas ou canceladas (filtro de segurança)
            status_normalizado = d.get('status', '').upper().replace(' ', '_')
            if status_normalizado in ['CONCLUIDO', 'COLETADO', 'CANCELADO']:
                continue

            # Check urgency (Express ou Deadline Crítico)
            is_critical = d.get('modalidade_logistica') == 'EXPRESS' or d.get('is_flex') or d.get('manual_priority_score', 0) >= 100
            if is_critical:
                urgentes_count += 1

            for item in itens:
                # Skip only 'Concluído' items (not 'Fechando')
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


# Singleton instance
demanda_reporting_kanban_service = DemandaReportingKanbanService()
