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


class DemandaReportingProductionService:
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

        if itens is not None and isinstance(itens, list):
            def qtd(item, field):
                if not isinstance(item, dict): return 0
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
            if d.get('total_itens', 0) > 0:
                progresso = round((d['itens_finalizados_total'] / d['total_itens']) * 100)
            d['progresso_percentual'] = progresso

            if d.get('total_itens', 0) > 0:
                d['readiness_score'] = round(((d['capas_impressas_qtd'] + d['miolos_produzidos_qtd']) / (2 * d['total_itens'])) * 100)
            else:
                d['readiness_score'] = 0

            d['is_stuck'] = False
            if d.get('status') == 'Em Produção' and d.get('total_itens', 0) > 0:
                gap_capas = d['capas_impressas_qtd'] - d['capas_produzidas_qtd']
                if gap_capas > (d['total_itens'] * 0.5) and d['itens_concluidos'] < (d['total_itens'] * 0.2):
                    d['is_stuck'] = True

            if itens:
                first_item = itens[0]
                if isinstance(first_item, dict):
                    d['id_produto_miolo'] = first_item.get('id_produto_miolo')
                    d['produto_miolo_nome'] = first_item.get('produto_miolo_nome') or first_item.get('miolo_nome')
        else:
            # Fallback para caso itens não seja uma lista válida
            d.update({
                'total_itens': 0, 'total_quantidade': 0, 'itens_finalizados_total': 0,
                'itens_finalizados': 0, 'itens_prontos_total': 0, 'itens_concluidos': 0,
                'capas_impressas_qtd': 0, 'capas_produzidas_qtd': 0, 'capas_prontas_retirada_qtd': 0,
                'miolos_produzidos_qtd': 0, 'miolos_prontos_retirada_qtd': 0, 'completed_quantidade': 0,
                'progresso_percentual': 0, 'readiness_score': 0, 'is_stuck': False
            })

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

    def _get_aggregated_demandas(self, response_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not response_data:
            return []

        demanda_ids = [row['id'] for row in response_data]
        itens_res = supabase_db.execute_with_retry(self.itens_table.select("*").in_('demanda_id', demanda_ids))

        itens_by_demanda = {}
        for item in itens_res.data:
            did = item['demanda_id']
            if did not in itens_by_demanda:
                itens_by_demanda[did] = []
            itens_by_demanda[did].append(item)

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

    def get_consolidado_producao(self, trilha=None, sku=None):
        """
        Busca dados da view consolidada com filtros opcionais.
        Filtra apenas demandas em produção (exclui finalizadas, coletadas, canceladas).
        """
        query = supabase_db.table('view_consolidado_producao').select("*")
        
        # Filtro adicional para garantir que apenas demandas ativas sejam retornadas
        # A view já filtra, mas reforçamos no código para garantir consistência
        query = query.neq('demanda_status', 'Finalizado')
        query = query.neq('demanda_status', 'CONCLUIDO')
        query = query.neq('demanda_status', 'Coletado')
        query = query.neq('demanda_status', 'COLETADO')
        query = query.neq('demanda_status', 'Cancelado')
        query = query.neq('demanda_status', 'CANCELADO')
        
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

            # Adiciona a demanda à lista de relacionadas
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


# Singleton instance
demanda_reporting_production_service = DemandaReportingProductionService()
