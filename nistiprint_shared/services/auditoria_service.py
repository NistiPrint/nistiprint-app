from datetime import datetime
from typing import Dict, Any, Optional
from nistiprint_shared.database.supabase_db_service import supabase_db

class AuditoriaService:
    """Serviço para registro imutável de eventos de auditoria."""

    def __init__(self):
        self.table = supabase_db.table('eventos_auditoria')

    def log_event(self, event_type: str, payload: Dict[str, Any], user_id: Optional[Any] = None) -> str:
        """
        Registra um evento de auditoria de forma imutável.

        Args:
            event_type: Tipo do evento (ex: 'ENTRADA_ESTOQUE', 'SAIDA_ASSOCIADA_DEMANDA')
            payload: Dados relevantes do evento
            user_id: ID do usuário que realizou a ação (esperado ID numérico para o banco)

        Returns:
            ID do documento criado
        """
        # Tratamento defensivo do usuario_id para o PostgreSQL (FK para usuarios.id que é INTEGER)
        db_user_id = None
        if user_id:
            try:
                # Tenta converter para int se for string numérica ou int
                db_user_id = int(str(user_id))
            except (ValueError, TypeError):
                # Se for 'System' ou outro valor não numérico, deixamos como None
                # para evitar erro de violação de FK
                pass

        # Tenta extrair entidade e ID do registro se presentes no payload para popular colunas específicas
        entidade = payload.get('entidade_tipo') or payload.get('entity_type')
        registro_id_raw = payload.get('entidade_id') or payload.get('registro_id') or payload.get('demanda_id') or payload.get('produto_id')
        
        db_registro_id = None
        if registro_id_raw:
            try:
                db_registro_id = int(str(registro_id_raw))
            except:
                pass

        event_data = {
            'tipo_evento': event_type,
            'descricao': payload.get('descricao') or f"Evento {event_type} registrado",
            'dados_novos': payload,
            'usuario_id': db_user_id,
            'entidade_afetada': entidade,
            'registro_id': db_registro_id
        }

        # Registrar de forma independente
        response = self.table.insert(event_data).execute()
        if response.data:
            return str(response.data[0]['id'])
        else:
            raise Exception("Falha ao inserir o evento de auditoria")

    def get_events(self, event_type: Optional[str] = None, user_id: Optional[Any] = None,
                   start_date: Optional[datetime] = None, end_date: Optional[datetime] = None,
                   limit: int = 100) -> list:
        """
        Consulta eventos de auditoria com filtros opcionais.
        """
        query = self.table.select("*").order('created_at', desc=True).limit(limit)

        if event_type:
            query = query.eq('tipo_evento', event_type)
        if user_id:
            try:
                query = query.eq('usuario_id', int(user_id))
            except:
                pass
        if start_date:
            query = query.gte('created_at', start_date.isoformat())
        if end_date:
            query = query.lte('created_at', end_date.isoformat())

        response = query.execute()

        events = []
        for row in response.data:
            event_data = dict(row)
            # Mapeia de volta para compatibilidade se necessário, mas aqui retornamos o objeto do banco
            events.append(event_data)

        return events

    def get_event_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Busca um evento específico por ID."""
        response = self.table.select("*").eq('id', event_id).execute()
        if response.data:
            return dict(response.data[0])
        return None

    def get_events_for_entity(self, entity_type: str, entity_id: Any,
                             event_types: Optional[list] = None) -> list:
        """
        Busca todos os eventos relacionados a uma entidade específica.
        """
        query = self.table.select("*").eq('entidade_afetada', entity_type)
        
        try:
            query = query.eq('registro_id', int(entity_id))
        except:
            # Se não for numérico, teremos que filtrar nos dados_novos (JSONB)
            # Para simplificar agora, buscamos todos e filtramos em Python se necessário
            # mas o ideal seria usar o operador -> do Postgres se soubermos a chave.
            query = self.table.select("*").order('created_at', desc=True).limit(1000)

        response = query.execute()

        filtered_events = []
        for row in response.data:
            event = dict(row)
            payload = event.get('dados_novos', {})

            # Filtro adicional em Python se o registro_id não funcionou ou para chaves variadas
            entity_related = False
            
            # Se já filtrou via query, entity_related é True
            if event.get('entidade_afetada') == entity_type and str(event.get('registro_id')) == str(entity_id):
                entity_related = True
            else:
                # Fallback para busca no JSON
                if entity_type == 'produto':
                    entity_related = (str(payload.get('produto_id', '')) == str(entity_id) or str(payload.get('product_id', '')) == str(entity_id))
                elif entity_type == 'demanda':
                    entity_related = (str(payload.get('demanda_id', '')) == str(entity_id) or str(payload.get('demand_id', '')) == str(entity_id))

            if entity_related and (not event_types or event['tipo_evento'] in event_types):
                filtered_events.append(event)

        return filtered_events

auditoria_service = AuditoriaService()

