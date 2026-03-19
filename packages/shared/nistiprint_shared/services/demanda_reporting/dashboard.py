"""
Demanda Reporting Dashboard Service - Sumários e KPIs de demandas.

Este módulo fornece métodos para:
- get_dashboard_summary: Sumário geral com totais, status, atrasos
- get_prioritized_demandas: Demandas priorizadas não concluídas
- get_demandas_by_status: Busca demandas filtradas por status
"""

from datetime import datetime
from pytz import timezone
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.constants import APP_TIMEZONE
from typing import List, Dict, Any


class DemandaReportingDashboardService:
    """
    Serviço de dashboard para relatórios e sumários de demandas.
    """

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

        return mapping.get(status, status.upper().replace(' ', '_'))

    def _process_demanda_dict(self, demanda: Dict[str, Any], itens: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Adiciona aliases e processa campos para o frontend, incluindo agregações de itens."""
        if not demanda:
            return None
        d = dict(demanda)
        d['nome'] = d.get('descricao')
        d['manual_priority_score'] = d.get('prioridade_manual', 0)

        if itens is not None:
            # Agregações básicas para o frontend (DemandaCard e Dashboard)
            d['total_itens'] = sum(float(i.get('quantidade', 0)) for i in itens)
            d['total_quantidade'] = d['total_itens']

            # Itens finalizados (finalização manual no dashboard)
            d['itens_finalizados_total'] = sum(float(i.get('finalizados_qtd', 0)) for i in itens)
            d['itens_finalizados'] = d['itens_finalizados_total']
            
            # completed_quantidade agora representa o progresso de FINALIZAÇÃO MANUAL para o frontend
            d['completed_quantidade'] = d['itens_finalizados_total']

            # Itens prontos (unidades completas: capa + miolo)
            d['capas_impressas_qtd'] = sum(float(i.get('capas_impressas_qtd', 0)) for i in itens)
            d['capas_produzidas_qtd'] = sum(float(i.get('capas_produzidas_qtd', 0)) for i in itens)
            d['capas_prontas_retirada_qtd'] = sum(float(i.get('capas_prontas_retirada_qtd', 0)) for i in itens)
            d['miolos_produzidos_qtd'] = sum(float(i.get('miolos_prontos_retirada_qtd', 0)) for i in itens)
            d['miolos_prontos_retirada_qtd'] = d['miolos_produzidos_qtd']

            d['itens_prontos_total'] = sum(min(float(i.get('capas_prontas_retirada_qtd') or 0), float(i.get('miolos_prontos_retirada_qtd') or 0)) for i in itens)
            d['itens_concluidos'] = d['itens_prontos_total']

            # quantidade_coletada_total mantém o valor da tabela entrega_producao (coleta física/faturamento)
            d['quantidade_coletada_total'] = d.get('quantidade_coletada_total', 0)

            # Itens em fechamento
            d['itens_em_fechamento'] = sum(
                min(float(i.get('expedicao_capas_retiradas_qtd') or 0), float(i.get('expedicao_miolos_retirados_qtd') or 0))
                for i in itens
            )

            progresso = 0
            if d['total_itens'] > 0:
                progresso = round((d['itens_finalizados_total'] / d['total_itens']) * 100)
            d['progresso_percentual'] = progresso
            
            # Cálculo de Prontidão (Readiness Score)
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

    def _get_aggregated_demandas(self, response_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Agrega dados de demandas com itens e coletas."""
        if not response_data:
            return []

        demanda_ids = [row['id'] for row in response_data]
        # Busca itens para todas as demandas da página de uma vez
        itens_res = supabase_db.execute_with_retry(self.itens_table.select("*").in_('demanda_id', demanda_ids))

        # Agrupa itens por demanda_id
        itens_by_demanda = {}
        for item in itens_res.data:
            did = item['demanda_id']
            if did not in itens_by_demanda:
                itens_by_demanda[did] = []
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

    def get_dashboard_summary(self):
        """
        Obtém sumário do dashboard com totais, status, atrasos e previsões.
        
        Returns:
            Dict com:
            - total: total de demandas
            - by_status: contagem por status
            - delayed: quantidade de demandas atrasadas
            - total_itens_previstos_hoje: itens previstos para hoje
            - total_itens_finalizados_hoje: itens finalizados hoje
        """
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
                except:
                    pass
        return summary

    def get_prioritized_demandas(self, limit=50):
        """
        Obtém demandas priorizadas (não concluídas e não canceladas), ordenadas por data de entrega.
        
        Args:
            limit: Limite de demandas a retornar (padrão: 50)
            
        Returns:
            List[Dict] com demandas priorizadas
        """
        response = supabase_db.execute_with_retry(
            self.demandas_table.select("*, canal_venda:canais_venda(nome, color, plataformas(nome))")
            .neq('status', 'CONCLUIDO').neq('status', 'CANCELADO')
            .order('data_entrega', nullsfirst=False).limit(limit)
        )
        return self._get_aggregated_demandas(response.data)

    def get_demandas_by_status(self, status_list: List[str], product_id=None) -> List[Dict[str, Any]]:
        """
        Busca demandas por status.
        
        Args:
            status_list: Lista de status para filtrar (ou status único)
            product_id: ID do produto para filtrar (opcional, não implementado)
            
        Returns:
            List[Dict] com demandas filtradas por status
        """
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

    def get_all_demandas(self) -> List[Dict[str, Any]]:
        """Busca todas as demandas."""
        response = supabase_db.execute_with_retry(
            self.demandas_table.select("*, canal_venda:canais_venda(nome, color, plataformas(nome))").order('created_at', desc=True)
        )
        return self._get_aggregated_demandas(response.data)


# Singleton instance
demanda_reporting_dashboard_service = DemandaReportingDashboardService()
