from datetime import datetime, timedelta
from typing import Dict, Any, List
from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
from nistiprint_shared.services.priority_calculation_service import priority_calculation_service
from nistiprint_shared.services.capacity_planning_service import capacity_planning_service
from nistiprint_shared.services.calendar_service import calendar_service


class ProductionPlanningService:
    """
    Service for comprehensive production planning with timeline visualization and resource allocation.
    """
    
    def __init__(self):
        self.demanda_service = demanda_producao_service
        self.priority_service = priority_calculation_service
        self.capacity_service = capacity_planning_service
        self.calendar_service = calendar_service

    def get_production_plan(self, start_date: str, end_date: str, filters: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Get comprehensive production plan with timeline visualization.
        """
        try:
            # Get all demands in the date range
            plan_data = {
                'period': {
                    'start_date': start_date,
                    'end_date': end_date
                },
                'sectors': {
                    'CPD': {'demands': [], 'utilization': 0, 'capacity': 40},  # 8 hrs/day * 5 days
                    'Capas': {'demands': [], 'utilization': 0, 'capacity': 40},
                    'Miolos': {'demands': [], 'utilization': 0, 'capacity': 40},
                    'Expedição': {'demands': [], 'utilization': 0, 'capacity': 40}
                },
                'demands': [],
                'summary': {
                    'total_demands': 0,
                    'urgent_demands': 0,
                    'flex_demands': 0,
                    'corporate_demands': 0
                }
            }
            
            # Get demands for the period
            all_demandas = self.demanda_service.get_all_demandas()
            
            for demanda in all_demandas:
                data_entrega_str = demanda.get('data_entrega')
                if not data_entrega_str:
                    continue
                
                try:
                    data_entrega = datetime.strptime(data_entrega_str, '%Y-%m-%d').date()
                    start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
                    end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
                    
                    if start_dt <= data_entrega <= end_dt:
                        # Calculate priority for this demand
                        priority_score = self.priority_service.calculate_priority_score(demanda)
                        
                        # Add to plan data
                        demand_data = {
                            'id': demanda['id'],
                            'nome': demanda.get('nome', ''),
                            'canal_venda_nome': demanda.get('canal_venda_nome', ''),
                            'data_entrega': data_entrega_str,
                            'data_inicio_planejada': demanda.get('data_inicio_planejada'),
                            'data_fim_planejada': demanda.get('data_fim_planejada'),
                            'tipo_demanda': demanda.get('tipo_demanda', 'Standard'),
                            'categoria_demanda': demanda.get('categoria_demanda', ''),
                            'categoria_temporal': demanda.get('categoria_temporal', ''),
                            'is_flex': demanda.get('is_flex', False),
                            'status': demanda.get('status', ''),
                            'prioridade': priority_score,
                            'capacidade_requerida': demanda.get('capacidade_requerida', {}),
                            'itens_count': len(demanda.get('itens', [])) if 'itens' in demanda else 0
                        }
                        
                        plan_data['demands'].append(demand_data)
                        
                        # Update summary
                        plan_data['summary']['total_demands'] += 1
                        
                        if demanda.get('categoria_temporal') == 'urgente':
                            plan_data['summary']['urgent_demands'] += 1
                        if demanda.get('is_flex'):
                            plan_data['summary']['flex_demands'] += 1
                        if demanda.get('tipo_demanda') == 'Empresas':
                            plan_data['summary']['corporate_demands'] += 1
                        
                        # Add to sector-specific lists
                        capacidade_requerida = demanda.get('capacidade_requerida', {})
                        for sector, req_data in capacidade_requerida.items():
                            if sector in plan_data['sectors']:
                                plan_data['sectors'][sector]['demands'].append({
                                    'demanda_id': demanda['id'],
                                    'nome': demanda.get('nome', ''),
                                    'horas_requeridas': req_data.get('horas', 0),
                                    'data_entrega': data_entrega_str
                                })
                                
                except ValueError:
                    continue  # Skip invalid dates
            
            # Calculate utilization for each sector
            for sector, sector_data in plan_data['sectors'].items():
                total_horas = sum(d['horas_requeridas'] for d in sector_data['demands'])
                capacity = sector_data['capacity']
                utilization = (total_horas / capacity) * 100 if capacity > 0 else 0
                sector_data['utilization'] = round(utilization, 2)
            
            # Sort demands by priority
            plan_data['demands'].sort(key=lambda x: x['prioridade'], reverse=True)
            
            return plan_data
        except Exception as e:
            print(f"ERROR in get_production_plan: {e}")
            raise

    def get_gantt_data(self, demanda_ids: List[str] = None) -> List[Dict[str, Any]]:
        """
        Get data formatted for Gantt chart visualization (Optimized with Batching).
        """
        try:
            gantt_data = []
            
            # 1. Fetch demands in batch
            if demanda_ids:
                demandas = self.demanda_service.get_demandas_by_ids(demanda_ids)
            else:
                demandas = self.demanda_service.get_demandas_by_status(['Pendente', 'Em Produção'])
            
            if not demandas:
                return []

            # 2. Fetch items for all these demands in a SINGLE batch call
            all_ids = [str(d['id']) for d in demandas]
            all_items_map = self.demanda_service.get_items_for_multiple_demandas(all_ids)

            # 3. Assemble Gantt data
            for demanda in demandas:
                # Inject items pre-fetched into demand object for progress calculation
                demanda['itens'] = all_items_map.get(str(demanda['id']), [])
                self._add_demanda_to_gantt_data(gantt_data, demanda)
            
            return gantt_data
        except Exception as e:
            print(f"ERROR in get_gantt_data: {e}")
            raise

    def _add_demanda_to_gantt_data(self, gantt_data: List[Dict[str, Any]], demanda: Dict[str, Any]):
        """
        Helper method to add a demand to the Gantt data structure.
        """
        # Add main demand task
        main_task = {
            'id': f"demanda_{demanda['id']}",
            'name': f"Demanda: {demanda.get('nome', '')}",
            'start': demanda.get('data_inicio_planejada') or demanda.get('data_entrega'),
            'end': demanda.get('data_fim_planejada') or demanda.get('data_entrega'),
            'progress': self._calculate_demand_progress(demanda),
            'type': 'demand',
            'demanda_id': demanda['id'],
            'dependencies': []
        }
        gantt_data.append(main_task)
        
        # Add sector-specific tasks if available
        capacidade_requerida = demanda.get('capacidade_requerida', {})
        for sector, req_data in capacidade_requerida.items():
            sector_task = {
                'id': f"demanda_{demanda['id']}_{sector}",
                'name': f"{sector}: {demanda.get('nome', '')}",
                'start': demanda.get('data_inicio_planejada') or demanda.get('data_entrega'),
                'end': demanda.get('data_fim_planejada') or demanda.get('data_entrega'),
                'progress': self._calculate_sector_progress(demanda, sector),
                'type': 'sector',
                'demanda_id': demanda['id'],
                'sector': sector,
                'dependencies': [f"demanda_{demanda['id']}"]
            }
            gantt_data.append(sector_task)

    def _calculate_demand_progress(self, demanda: Dict[str, Any]) -> int:
        """
        Calculate progress percentage for a demand.
        Only 'Concluído' status counts as completed. 'Fechando' is still in progress.
        """
        if 'itens' not in demanda or not demanda['itens']:
            return 0
        
        total_itens = len(demanda['itens'])
        completed_itens = sum(1 for item in demanda['itens'] if item.get('status_item') == 'Concluído')
        
        return int((completed_itens / total_itens) * 100) if total_itens > 0 else 0

    def _calculate_sector_progress(self, demanda: Dict[str, Any], sector: str) -> int:
        """
        Calculate progress percentage for a specific sector of a demand.
        """
        if 'itens' not in demanda or not demanda['itens']:
            return 0
        
        # This is a simplified calculation - in a real implementation, 
        # this would track progress for each sector specifically
        total_quantidade = sum(item.get('quantidade_total', 0) for item in demanda['itens'])
        
        if sector == 'CPD':
            produzido = sum(item.get('capas_impressas_qtd', 0) for item in demanda['itens'])
        elif sector == 'Capas':
            produzido = sum(item.get('capas_produzidas_qtd', 0) for item in demanda['itens'])
        elif sector == 'Miolos':
            produzido = sum(item.get('miolos_prontos_retirada_qtd', 0) for item in demanda['itens'])
        elif sector == 'Expedição':
            # Consider expedited when both caps and cores are done
            capas_expedidas = sum(item.get('expedicao_capas_retiradas_qtd', 0) for item in demanda['itens'])
            miolos_expedidos = sum(item.get('expedicao_miolos_retirados_qtd', 0) for item in demanda['itens'])
            produzido = min(capas_expedidas, miolos_expedidos)
        else:
            produzido = 0
        
        return int((produzido / total_quantidade) * 100) if total_quantidade > 0 else 0

    def get_resource_allocation_dashboard(self) -> Dict[str, Any]:
        """
        Get dashboard data for resource allocation.
        """
        try:
            dashboard_data = {
                'sectors': {
                    'CPD': {'resources': [], 'allocation_rate': 0},
                    'Capas': {'resources': [], 'allocation_rate': 0},
                    'Miolos': {'resources': [], 'allocation_rate': 0},
                    'Expedição': {'resources': [], 'allocation_rate': 0}
                },
                'allocation_summary': {
                    'total_resources': 0,
                    'allocated_resources': 0,
                    'available_resources': 0
                }
            }
            
            # For each sector, get available resources and their allocation status
            for sector in dashboard_data['sectors'].keys():
                resources = self.capacity_service.get_available_resources(sector, {
                    'start': datetime.now().strftime('%Y-%m-%d'),
                    'end': (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
                })
                
                dashboard_data['sectors'][sector]['resources'] = resources
                dashboard_data['allocation_summary']['total_resources'] += len(resources)
                
                # Calculate allocation rate for this sector (simplified)
                allocated_count = sum(1 for r in resources if not r.get('available', True))
                dashboard_data['sectors'][sector]['allocation_rate'] = (
                    (allocated_count / len(resources)) * 100 if resources else 0
                )
                
                dashboard_data['allocation_summary']['allocated_resources'] += allocated_count
            
            dashboard_data['allocation_summary']['available_resources'] = (
                dashboard_data['allocation_summary']['total_resources'] - 
                dashboard_data['allocation_summary']['allocated_resources']
            )
            
            return dashboard_data
        except Exception as e:
            print(f"ERROR in get_resource_allocation_dashboard: {e}")
            raise

    def forecast_production_needs(self, period_days: int = 30) -> Dict[str, Any]:
        """
        Forecast production needs based on historical data and demand patterns.
        """
        try:
            forecast_data = {
                'period_days': period_days,
                'start_date': datetime.now().strftime('%Y-%m-%d'),
                'end_date': (datetime.now() + timedelta(days=period_days)).strftime('%Y-%m-%d'),
                'demand_forecast': {
                    'total_demands': 0,
                    'by_category': {},
                    'by_sector': {}
                },
                'capacity_requirements': {
                    'CPD': {'hours': 0, 'resources_needed': 0},
                    'Capas': {'hours': 0, 'resources_needed': 0},
                    'Miolos': {'hours': 0, 'resources_needed': 0},
                    'Expedição': {'hours': 0, 'resources_needed': 0}
                },
                'alerts': []
            }
            
            # Get upcoming demands for the forecast period
            start_date = datetime.now().strftime('%Y-%m-%d')
            end_date = (datetime.now() + timedelta(days=period_days)).strftime('%Y-%m-%d')
            
            # Get demands in the forecast period
            all_demandas = self.demanda_service.get_all_demandas()
            
            for demanda in all_demandas:
                data_entrega_str = demanda.get('data_entrega')
                if not data_entrega_str:
                    continue
                
                try:
                    data_entrega = datetime.strptime(data_entrega_str, '%Y-%m-%d')
                    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                    
                    if start_dt <= data_entrega <= end_dt:
                        forecast_data['demand_forecast']['total_demands'] += 1
                        
                        # Count by category
                        categoria = demanda.get('categoria_demanda', 'outros')
                        if categoria not in forecast_data['demand_forecast']['by_category']:
                            forecast_data['demand_forecast']['by_category'][categoria] = 0
                        forecast_data['demand_forecast']['by_category'][categoria] += 1
                        
                        # Add capacity requirements
                        capacidade_requerida = demanda.get('capacidade_requerida', {})
                        for sector, req_data in capacidade_requerida.items():
                            if sector in forecast_data['capacity_requirements']:
                                forecast_data['capacity_requirements'][sector]['hours'] += req_data.get('horas', 0)
                                
                                # Estimate resources needed (simplified)
                                forecast_data['capacity_requirements'][sector]['resources_needed'] = int(
                                    forecast_data['capacity_requirements'][sector]['hours'] / 8  # 8 hours per day per resource
                                )
                                
                except ValueError:
                    continue  # Skip invalid dates
            
            # Generate alerts for potential capacity issues
            for sector, req_data in forecast_data['capacity_requirements'].items():
                if req_data['resources_needed'] > 5:  # If more than 5 resources needed
                    forecast_data['alerts'].append({
                        'type': 'capacity_warning',
                        'sector': sector,
                        'message': f'Setor {sector} precisará de {req_data["resources_needed"]} recursos no período, verifique disponibilidade',
                        'severity': 'warning'
                    })
            
            return forecast_data
        except Exception as e:
            print(f"ERROR in forecast_production_needs: {e}")
            raise


# Global instance for use throughout the application
production_planning_service = ProductionPlanningService()

