from datetime import datetime, timedelta
from typing import Dict, Any, List
from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
from nistiprint_shared.services.priority_calculation_service import priority_calculation_service


class CalendarService:
    """
    Service for calendar integration and scheduling functionality.
    """
    
    def __init__(self):
        self.demanda_service = demanda_producao_service
        self.priority_service = priority_calculation_service

    def get_calendar_data(self, start_date: str, end_date: str, filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        Get calendar data for demands in the specified date range.
        """
        try:
            # Parse dates
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            
            # Get all active demands
            status_filter = ['Pendente', 'Em Produção', 'Concluído']  # Include all relevant statuses
            if filters and 'status' in filters:
                status_filter = filters['status']
                
            demandas = self.demanda_service.get_demandas_by_status(status_filter)
            
            calendar_events = []
            
            for demanda in demandas:
                data_entrega_str = demanda.get('data_entrega')
                if not data_entrega_str:
                    continue
                    
                try:
                    data_entrega = datetime.strptime(data_entrega_str, '%Y-%m-%d')
                    
                    # Check if demand falls within the date range
                    if start_dt <= data_entrega <= end_dt:
                        # Create calendar event for the demand
                        event = {
                            'id': f"demanda_{demanda['id']}",
                            'title': f"{demanda.get('nome', 'Demanda')} - {demanda.get('canal_venda_nome', '')}",
                            'start': data_entrega_str,
                            'end': data_entrega_str,
                            'extendedProps': {
                                'demanda_id': demanda['id'],
                                'tipo_demanda': demanda.get('tipo_demanda', 'Standard'),
                                'categoria_demanda': demanda.get('categoria_demanda', ''),
                                'categoria_temporal': demanda.get('categoria_temporal', ''),
                                'is_flex': demanda.get('is_flex', False),
                                'status': demanda.get('status', ''),
                                'prioridade': self.priority_service.calculate_priority_score(demanda),
                                'cliente': demanda.get('empresa_cliente_nome', ''),
                                'itens_count': len(demanda.get('itens', [])) if 'itens' in demanda else 0
                            },
                            'className': self._get_event_class(demanda),
                            'backgroundColor': self._get_event_color(demanda)
                        }
                        
                        calendar_events.append(event)
                        
                        # If the demand has planned start and end dates, add those as well
                        data_inicio_planejada = demanda.get('data_inicio_planejada')
                        data_fim_planejada = demanda.get('data_fim_planejada')
                        
                        if data_inicio_planejada and data_fim_planejada:
                            planned_event = {
                                'id': f"demanda_{demanda['id']}_planned",
                                'title': f"Planejado: {demanda.get('nome', 'Demanda')}",
                                'start': data_inicio_planejada,
                                'end': data_fim_planejada,
                                'extendedProps': {
                                    'demanda_id': demanda['id'],
                                    'tipo_demanda': demanda.get('tipo_demanda', 'Standard'),
                                    'categoria_demanda': demanda.get('categoria_demanda', ''),
                                    'categoria_temporal': demanda.get('categoria_temporal', ''),
                                    'is_flex': demanda.get('is_flex', False),
                                    'status': demanda.get('status', ''),
                                    'prioridade': self.priority_service.calculate_priority_score(demanda),
                                    'cliente': demanda.get('empresa_cliente_nome', ''),
                                    'itens_count': len(demanda.get('itens', [])) if 'itens' in demanda else 0,
                                    'event_type': 'planned'
                                },
                                'className': 'planned-event',
                                'backgroundColor': '#e0e0e0',
                                'borderColor': '#9e9e9e'
                            }
                            
                            calendar_events.append(planned_event)
                        
                except ValueError:
                    continue  # Skip invalid dates
            
            # Sort events by priority (higher priority first)
            calendar_events.sort(key=lambda x: x['extendedProps'].get('prioridade', 0), reverse=True)
            
            return calendar_events
        except Exception as e:
            print(f"ERROR in get_calendar_data: {e}")
            raise

    def _get_event_class(self, demanda: Dict[str, Any]) -> str:
        """
        Get CSS class for calendar event based on demand type.
        """
        classes = ['calendar-event']
        
        if demanda.get('is_flex'):
            classes.append('flex-demand')
        elif demanda.get('tipo_demanda') == 'Empresas':
            classes.append('corporate-demand')
        else:
            classes.append('standard-demand')
            
        categoria_temporal = demanda.get('categoria_temporal')
        if categoria_temporal:
            classes.append(f"{categoria_temporal}-demand")
            
        return ' '.join(classes)

    def _get_event_color(self, demanda: Dict[str, Any]) -> str:
        """
        Get color for calendar event based on demand priority and type.
        """
        if demanda.get('is_flex'):
            return '#ff5722'  # Red-orange for flex (high priority)
        elif demanda.get('categoria_temporal') == 'urgente':
            return '#f44336'  # Red for urgent
        elif demanda.get('categoria_temporal') == 'curto_prazo':
            return '#ff9800'  # Orange for short term
        elif demanda.get('tipo_demanda') == 'Empresas':
            return '#2196f3'  # Blue for corporate
        else:
            return '#4caf50'  # Green for standard

    def validate_scheduling_conflict(self, demanda_id: str, new_schedule_dates: Dict[str, str]) -> Dict[str, Any]:
        """
        Validate if the new schedule dates would create conflicts with existing demands.
        """
        try:
            from nistiprint_shared.services.capacity_planning_service import capacity_planning_service
            
            # Get the demand to validate
            demanda = self.demanda_service.get_demanda_with_itens(demanda_id)
            if not demanda:
                raise ValueError(f"Demanda com ID {demanda_id} não encontrada.")
            
            # Create a temporary updated demand with new dates
            temp_demanda = demanda.copy()
            if 'data_inicio_planejada' in new_schedule_dates:
                temp_demanda['data_inicio_planejada'] = new_schedule_dates['data_inicio_planejada']
            if 'data_fim_planejada' in new_schedule_dates:
                temp_demanda['data_fim_planejada'] = new_schedule_dates['data_fim_planejada']
            if 'data_entrega' in new_schedule_dates:
                temp_demanda['data_entrega'] = new_schedule_dates['data_entrega']
            
            # Check for capacity conflicts
            conflicts = capacity_planning_service.detect_capacity_conflicts(temp_demanda)
            
            # Check for resource conflicts (double booking)
            resource_conflicts = self._check_resource_conflicts(temp_demanda, new_schedule_dates)
            
            return {
                'has_conflicts': len(conflicts) > 0 or len(resource_conflicts) > 0,
                'capacity_conflicts': conflicts,
                'resource_conflicts': resource_conflicts
            }
        except Exception as e:
            print(f"ERROR in validate_scheduling_conflict: {e}")
            raise

    def _check_resource_conflicts(self, demanda: Dict[str, Any], new_schedule_dates: Dict[str, str]) -> List[Dict[str, Any]]:
        """
        Check for resource conflicts (double booking) with other demands.
        """
        # This would normally check against a resource scheduling database
        # For now, return an empty list
        return []

    def update_demand_schedule(self, demanda_id: str, schedule_updates: Dict[str, str], user_id: str = 'System') -> Dict[str, Any]:
        """
        Update the schedule dates for a demand.
        """
        try:
            # Prepare updates for the schedule fields
            allowed_schedule_fields = [
                'data_inicio_planejada', 'data_fim_planejada', 'data_entrega',
                'data_limite_execucao', 'data_promessa_cliente', 'data_maxima_entrega'
            ]
            
            filtered_updates = {
                k: v for k, v in schedule_updates.items() 
                if k in allowed_schedule_fields and v is not None
            }
            
            if not filtered_updates:
                raise ValueError("Nenhum campo de agenda válido fornecido para atualização.")
            
            # Update the demand with new schedule dates
            updated_demanda = self.demanda_service.update_demanda_extended_fields(
                demanda_id, filtered_updates, user_id
            )
            
            return updated_demanda
        except Exception as e:
            print(f"ERROR in update_demand_schedule: {e}")
            raise


# Global instance for use throughout the application
calendar_service = CalendarService()

