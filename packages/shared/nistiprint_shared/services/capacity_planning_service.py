from datetime import datetime, timedelta
from typing import Dict, Any, List
from nistiprint_shared.services.demanda.core import demanda_core_service
from nistiprint_shared.database.supabase_db_service import supabase_db


class CapacityPlanningService:
    """
    Service for forecasting resource utilization and detecting capacity conflicts.
    """

    def __init__(self):
        self.demanda_service = demanda_core_service
        self.resources_table = supabase_db.table('recursos_produtivos')
        self.schedules_table = supabase_db.table('agenda_recursos')

    def forecast_resource_utilization(self, start_date: str, end_date: str, resources: List[str] = None) -> Dict[str, Any]:
        """
        Forecast resource utilization based on scheduled demands.
        """
        try:
            # Parse dates
            start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
            
            # Get all active demands in the date range
            all_demandas = self.demanda_service.get_all_demandas()
            
            # Initialize utilization report
            utilization_report = {
                'period_start': start_date,
                'period_end': end_date,
                'sectors': {
                    'CPD': {'total_hours': 0, 'available_hours': 8 * 5, 'utilization_rate': 0},  # 8 hrs/day * 5 days
                    'Capas': {'total_hours': 0, 'available_hours': 8 * 5, 'utilization_rate': 0},
                    'Miolos': {'total_hours': 0, 'available_hours': 8 * 5, 'utilization_rate': 0},
                    'Expedição': {'total_hours': 0, 'available_hours': 8 * 5, 'utilization_rate': 0}
                },
                'daily_breakdown': {}
            }
            
            # Process each day in the range
            current_date = start_dt
            while current_date <= end_dt:
                date_str = current_date.strftime('%Y-%m-%d')
                utilization_report['daily_breakdown'][date_str] = {
                    'CPD': 0,
                    'Capas': 0,
                    'Miolos': 0,
                    'Expedição': 0
                }
                current_date += timedelta(days=1)
            
            # Calculate utilization based on demands
            for demanda in all_demandas:
                data_entrega_str = demanda.get('data_entrega')
                if not data_entrega_str:
                    continue
                    
                try:
                    data_entrega = datetime.strptime(data_entrega_str, '%Y-%m-%d').date()
                    if start_dt <= data_entrega <= end_dt:
                        date_str = data_entrega.strftime('%Y-%m-%d')
                        
                        # Get capacity requirements for this demand
                        capacidade_requerida = demanda.get('capacidade_requerida', {})
                        
                        for sector, sector_data in capacidade_requerida.items():
                            if sector in utilization_report['sectors']:
                                horas = sector_data.get('horas', 0)
                                utilization_report['sectors'][sector]['total_hours'] += horas
                                
                                # Update daily breakdown
                                if date_str in utilization_report['daily_breakdown']:
                                    utilization_report['daily_breakdown'][date_str][sector] += horas
                                    
                except ValueError:
                    continue  # Skip invalid dates
            
            # Calculate utilization rates
            for sector, data in utilization_report['sectors'].items():
                available_hours = data['available_hours']
                total_hours = data['total_hours']
                utilization_rate = (total_hours / available_hours) * 100 if available_hours > 0 else 0
                data['utilization_rate'] = round(utilization_rate, 2)
            
            return utilization_report
        except Exception as e:
            print(f"ERROR in forecast_resource_utilization: {e}")
            raise

    def detect_capacity_conflicts(self, demanda_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Detect if adding this demand would exceed capacity.
        """
        try:
            conflicts = []
            
            # Get capacity requirements for this demand
            capacidade_requerida = demanda_data.get('capacidade_requerida', {})
            
            # Get forecast for the delivery date
            data_entrega_str = demanda_data.get('data_entrega')
            if not data_entrega_str:
                return conflicts  # No delivery date, no conflict possible
            
            # Calculate forecast for the next few days to check for conflicts
            start_date = data_entrega_str
            end_date = datetime.strptime(data_entrega_str, '%Y-%m-%d') + timedelta(days=7)
            end_date_str = end_date.strftime('%Y-%m-%d')
            
            forecast = self.forecast_resource_utilization(start_date, end_date_str)
            
            # Check for conflicts
            for sector, req_data in capacidade_requerida.items():
                if sector in forecast['sectors']:
                    total_req = forecast['sectors'][sector]['total_hours']
                    available = forecast['sectors'][sector]['available_hours']
                    horas_adicionais = req_data.get('horas', 0)
                    
                    if total_req + horas_adicionais > available:
                        conflicts.append({
                            'sector': sector,
                            'required_additional_hours': horas_adicionais,
                            'current_total_hours': total_req,
                            'available_hours': available,
                            'conflict_level': 'critical' if (total_req + horas_adicionais) > available * 1.2 else 'warning'
                        })
            
            return conflicts
        except Exception as e:
            print(f"ERROR in detect_capacity_conflicts: {e}")
            raise

    def get_available_resources(self, sector: str, date_range: Dict[str, str]) -> List[Dict[str, Any]]:
        """
        Get available resources for a specific sector in a date range.
        """
        try:
            # This would normally query a resource availability database
            # For now, return a mock response
            resources = []
            
            # Example resources for each sector
            if sector == 'CPD':
                resources = [
                    {'id': 'printer_1', 'name': 'Impressora HP Indigo 1', 'capacity_hours': 8, 'available': True},
                    {'id': 'printer_2', 'name': 'Impressora HP Indigo 2', 'capacity_hours': 8, 'available': True},
                    {'id': 'cutting_1', 'name': 'Cortadora Automática', 'capacity_hours': 8, 'available': True}
                ]
            elif sector == 'Capas':
                resources = [
                    {'id': 'machine_1', 'name': 'Máquina de Capas 1', 'capacity_hours': 8, 'available': True},
                    {'id': 'machine_2', 'name': 'Máquina de Capas 2', 'capacity_hours': 8, 'available': True}
                ]
            elif sector == 'Miolos':
                resources = [
                    {'id': 'folder_1', 'name': 'Dobradeira 1', 'capacity_hours': 8, 'available': True},
                    {'id': 'stapler_1', 'name': 'Grampeador 1', 'capacity_hours': 8, 'available': True}
                ]
            elif sector == 'Expedição':
                resources = [
                    {'id': 'packing_station_1', 'name': 'Estação de Embalagem 1', 'capacity_hours': 8, 'available': True},
                    {'id': 'packing_station_2', 'name': 'Estação de Embalagem 2', 'capacity_hours': 8, 'available': True}
                ]
            
            return resources
        except Exception as e:
            print(f"ERROR in get_available_resources: {e}")
            raise

    def allocate_resources_to_demand(self, demanda_id: str, allocations: List[Dict[str, Any]], user_id: str = 'System') -> bool:
        """
        Allocate specific resources to a demand.
        """
        try:
            # Update the demand with resource allocations
            # In Supabase, we'll update the demand record directly
            update_data = {
                'data_alocacao_recursos': datetime.utcnow().isoformat(),
                'alocado_por': user_id
            }

            # Update the main demand document with allocation info
            response = supabase_db.table('demandas_producao').update(update_data).eq('id', demanda_id).execute()

            if len(response.data) == 0:
                raise ValueError(f"Demanda com ID {demanda_id} não encontrada.")

            # For item allocations, we'll need to update the itens_demanda table
            # This assumes there's a separate table for demand items
            for allocation in allocations:
                sector = allocation.get('sector')
                if sector:
                    # Update item allocations in the demanda_itens table
                    # This is a simplified approach - in a real implementation,
                    # you might need to join with the demanda_itens table
                    item_update_data = {
                        'alocacao_recursos': {
                            sector: {
                                'alocado': True,
                                'recurso': allocation.get('resource_id'),
                                'operador': allocation.get('operator_id')
                            }
                        }
                    }

                    # Update all items for this demand
                    supabase_db.table('itens_demanda').update(item_update_data).eq('demanda_id', demanda_id).execute()

            return True
        except Exception as e:
            print(f"ERROR in allocate_resources_to_demand: {e}")
            raise


# Global instance for use throughout the application
capacity_planning_service = CapacityPlanningService()

