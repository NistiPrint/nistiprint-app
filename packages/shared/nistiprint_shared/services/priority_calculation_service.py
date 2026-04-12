from datetime import datetime, timedelta
from typing import Dict, Any, List
from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
from nistiprint_shared.services.canal_venda_service import canal_venda_service


class PriorityCalculationService:
    """
    Service for calculating demand priorities based on multiple factors.
    """
    
    def __init__(self):
        self.demanda_service = demanda_producao_service

    def calculate_priority_score(self, demanda_data: Dict[str, Any], item_data: Dict[str, Any] = None, canal_info: Dict[str, Any] = None) -> int:
        """
        Calculate priority score based on multiple factors.
        Higher score means higher priority.
        """
        score = 0

        # Base priority from type
        tipo_prioridade = {
            'flex': 1000,
            'urgente': 800,
            'curto_prazo': 600,
            'medio_prazo': 400,
            'longo_prazo': 200,
            'normal': 100
        }

        # Get category from demand data
        categoria_temporal = demanda_data.get('categoria_temporal', 'normal')
        score += tipo_prioridade.get(categoria_temporal, 100)

        # Check modalidade logística
        modalidade_logistica = demanda_data.get('modalidade_logistica', 'STANDARD')
        
        # Lógica de Deadline Crítico (Baseada na nova regra de backups logísticos)
        deadline_score = 0
        if canal_info and canal_info.get('regras_logisticas'):
            regras = canal_info.get('regras_logisticas', {}).get(modalidade_logistica, [])

            if regras:
                # O deadline crítico é o MAIOR horário limite disponível para aquela modalidade no dia
                # Ex: Coleta 11h, Ponto 19h -> Deadline Crítico é 19h.
                # Se Amazon só tem Coleta 12h -> Deadline Crítico é 12h.
                try:
                    horarios = [r.get('horario_limite') for r in regras if r.get('horario_limite')]
                    if horarios:
                        deadline_final_str = max(horarios)
                        deadline_final = datetime.strptime(deadline_final_str, '%H:%M').time()

                        # Quanto mais cedo for o deadline FINAL, maior a urgência
                        # Ex: 12:00 (Amazon) vs 19:00 (Shopee)
                        # Amazon deve pontuar mais
                        hora_ref = deadline_final.hour + (deadline_final.minute / 60.0)
                        # Inverte a escala: 24h - hora_deadline. 12h -> 12pts, 19h -> 5pts.
                        deadline_score = int((24 - hora_ref) * 100)
                except Exception as e:
                    print(f"Erro ao calcular deadline_score: {e}")

        if deadline_score > 0:
            score += deadline_score
        else:
            # Fallback se não houver regras configuradas
            if modalidade_logistica == 'EXPRESS':
                score += 1000
            elif modalidade_logistica == 'STANDARD':
                score += 100
            elif modalidade_logistica == 'FULFILLMENT':
                score += 50
            elif modalidade_logistica == 'RETIRADA':
                score += 75

        # Deadline urgency factor (Data de Entrega)
        data_entrega_str = demanda_data.get('data_entrega')
        if data_entrega_str:
            try:
                data_entrega = datetime.strptime(data_entrega_str, '%Y-%m-%d').date()
                hoje = datetime.utcnow().date()
                dias_para_entrega = (data_entrega - hoje).days

                if dias_para_entrega <= 0:
                    score += 1000  # Overdue
                elif dias_para_entrega <= 1:
                    score += 800   # Tomorrow
                elif dias_para_entrega <= 3:
                    score += 600   # This week
                elif dias_para_entrega <= 7:
                    score += 400   # This week
                elif dias_para_entrega <= 14:
                    score += 200   # Two weeks
            except ValueError:
                pass  # Invalid date format

        # Manual priority boost
        manual_boost = demanda_data.get('manual_priority_score', 0)
        if manual_boost:
            score += manual_boost

        # Classificação do cliente - substitui o tipo_demanda para priorização
        classificacao_cliente = demanda_data.get('classificacao_cliente', 'B2C')
        if classificacao_cliente == 'B2B':
            score += 50  # Corporate demands get slight boost
        elif classificacao_cliente == 'INTERNO':
            score += 25  # Internal demands get small boost
        elif classificacao_cliente == 'B2C':
            score += 0   # Consumer demands get baseline priority

        # Category-based boost
        categoria_demanda = demanda_data.get('categoria_demanda')
        if categoria_demanda == 'corporate':
            score += 100
        elif categoria_demanda == 'custom':
            score += 75

        # Para manter compatibilidade com código legado, também consideramos is_flex e tipo_demanda
        # mas com menor prioridade do que os novos campos
        is_flex = demanda_data.get('is_flex', False)
        if is_flex and modalidade_logistica != 'EXPRESS':
            score += 1000  # Flex demands get high priority if not already set as EXPRESS

        tipo_demanda_antigo = demanda_data.get('tipo_demanda', 'PLATAFORMA')
        if tipo_demanda_antigo == 'B2B' and classificacao_cliente != 'B2B':
            score += 50  # Corporate demands get slight boost if not already classified as B2B

        return score

    def calculate_item_priority_score(self, demanda_data: Dict[str, Any], item_data: Dict[str, Any], canal_info: Dict[str, Any] = None) -> int:
        """
        Calculate priority score for a specific item in a demand.
        """
        # Start with the demand's priority score
        score = self.calculate_priority_score(demanda_data, item_data, canal_info)
        
        # Adjust based on item-specific factors
        quantidade_total = item_data.get('quantidade_total', 0)
        
        # Large orders might get priority
        if quantidade_total > 1000:
            score += 50
        elif quantidade_total > 500:
            score += 30
        elif quantidade_total > 100:
            score += 10
            
        # Manual priority for item
        item_manual_priority = item_data.get('manual_priority_score', 0)
        if item_manual_priority:
            score += item_manual_priority
            
        return score

    def get_prioritized_demandas(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Return prioritized demands based on calculated scores.
        """
        # Get all active demands
        active_demandas = self.demanda_service.get_demandas_by_status(['Pendente', 'Em Produção'])

        prioritized_items = []

        # Pre-fetch channels for info enrichment
        try:
            canais = canal_venda_service.get_all()
            canais_map = {c['id']: c for c in canais}
        except:
            canais_map = {}

        for demanda in active_demandas:
            is_flex = demanda.get('is_flex', False)
            canal_id = demanda.get('canal_venda_id')
            canal_info = canais_map.get(canal_id, {})

            demanda_info = {
                'id': demanda['id'],
                'nome': demanda.get('nome', ''),
                'canal_venda_nome': demanda.get('canal_venda_nome', ''),
                'canal_venda_plataforma': demanda.get('canal_venda_plataforma', ''),
                'canal_venda_color': canal_info.get('color', '#007bff'),
                'data_entrega': demanda.get('data_entrega', ''),
                'horario_coleta': demanda.get('horario_coleta', ''),
                'observacoes': demanda.get('observacoes', ''),
                'tipo_demanda': demanda.get('tipo_demanda', 'Standard'),
                'is_flex': is_flex,
                'modalidade_logistica': demanda.get('modalidade_logistica', 'STANDARD'),
                'classificacao_cliente': demanda.get('classificacao_cliente', 'B2C'),
                # Empresa fields if Empresas type
                'empresa_cliente_nome': demanda.get('empresa_cliente_nome'),
                'empresa_interacao_status': demanda.get('empresa_interacao_status'),
                'empresa_wire_o_cor': demanda.get('empresa_wire_o_cor'),
                'empresa_elastico_cor': demanda.get('empresa_elastico_cor')
            }

            demanda_with_itens = self.demanda_service.get_demanda_with_itens(demanda['id'])
            if demanda_with_itens and 'itens' in demanda_with_itens:
                for item in demanda_with_itens['itens']:
                    # Skip concluded items (only 'Concluído', not 'Fechando')
                    if item.get('status_item') == 'Concluído':
                        continue

                    # Calculate priority based on the new calculation method
                    priority_score = self.calculate_item_priority_score(demanda, item, canal_info)

                    item['prioridade_calculada'] = priority_score
                    item['demanda_info'] = demanda_info
                    prioritized_items.append(item)

        # Sort by calculated priority (higher first)
        prioritized_items.sort(key=lambda x: x['prioridade_calculada'], reverse=True)

        return prioritized_items[:limit]

    def is_capacity_tight(self, demanda_data: Dict[str, Any], start_date: str = None, end_date: str = None) -> bool:
        """
        Check if adding this demand would exceed capacity in the given period.
        """
        # This is a simplified implementation - in a real scenario, this would
        # check against actual resource schedules and capacities
        capacidade_requerida = demanda_data.get('capacidade_requerida', {})
        
        # If no capacity data, assume it's not tight
        if not capacidade_requerida:
            return False
            
        # Check if any department has high capacity requirements
        for dept, dept_info in capacidade_requerida.items():
            horas_requeridas = dept_info.get('horas', 0)
            # If any department requires more than 8 hours, consider capacity tight
            if horas_requeridas > 8:
                return True
                
        return False


# Global instance for use throughout the application
priority_calculation_service = PriorityCalculationService()

