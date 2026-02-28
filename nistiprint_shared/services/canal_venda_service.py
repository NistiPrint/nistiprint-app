from nistiprint_shared.database.supabase_db_service import supabase_db
from datetime import datetime
from nistiprint_shared.services.regra_logistica_service import regra_logistica_service

class CanalVendaService:
    """Service for managing sales channels (canais de venda) in Supabase."""

    def __init__(self):
        self._table = None

    @property
    def table(self):
        """Lazy initialization of table."""
        if self._table is None:
            self._table = supabase_db.table('canais_venda')
        return self._table

    def _process_channel_data(self, channel_data):
        """Ensures 'plataforma' is present, with fallback from 'platform_type' or joined table."""
        if not channel_data:
            return None

        # Armazenar temporariamente as regras logísticas antes de processar
        regras_logisticas = channel_data.get('regras_logisticas')

        # Map 'nome' to 'name' for frontend
        if 'nome' in channel_data:
            channel_data['name'] = channel_data['nome']

        if 'plataforma' not in channel_data:
            # Check if we have joined data from plataformas table
            if 'plataformas' in channel_data and channel_data['plataformas']:
                # Supabase returns joined data as a dict or list
                p_data = channel_data['plataformas']
                if isinstance(p_data, dict):
                    channel_data['plataforma'] = p_data.get('nome')
                elif isinstance(p_data, list) and len(p_data) > 0:
                    channel_data['plataforma'] = p_data[0].get('nome')

            # Fallback to platform_type if still missing
            if 'plataforma' not in channel_data and 'platform_type' in channel_data:
                channel_data['plataforma'] = channel_data['platform_type']

        # Restaurar as regras logísticas após o processamento
        if regras_logisticas is not None:
            channel_data['regras_logisticas'] = regras_logisticas

        return channel_data

    def get_all(self, active_only=True):
        """Get all sales channels ordered by name."""
        try:
            query = self.table.select("*, plataformas(nome)")

            if active_only:
                query = query.eq('ativo', True)

            # Order by ID to be safe if name is ambiguous, or trust Supabase handles 'nome' for the main table
            response = query.order("nome", desc=False).execute()

            channels = []
            for row in response.data:
                channel_data = dict(row)
                channel_data['id'] = row.get('id')

                # Carregar regras logísticas estruturadas e adicioná-las ao objeto
                regras = regra_logistica_service.get_by_canal(channel_data['id'])
                channel_data['regras_logisticas'] = regras

                channels.append(self._process_channel_data(channel_data))

            return channels
        except Exception as e:
            print(f"Error in get_all: {e}")
            return []

    def get_by_id(self, channel_id: str):
        """Get sales channel by ID."""
        try:
            response = self.table.select("*, plataformas(nome)").eq('id', channel_id).execute()
            if response.data:
                channel = dict(response.data[0])
                channel['id'] = channel.get('id')

                # Carregar regras logísticas estruturadas e adicioná-las ao objeto
                regras = regra_logistica_service.get_by_canal(channel['id'])
                channel['regras_logisticas'] = regras

                return self._process_channel_data(channel)
            return None
        except Exception as e:
            print(f"Error in get_by_id: {e}")
            return None

    def get_by_slug(self, slug: str):
        """Get sales channel by slug."""
        try:
            response = self.table.select("*, plataformas(nome)").eq('slug', slug).execute()
            if response.data:
                channel = dict(response.data[0])
                channel['id'] = channel.get('id')
                return self._process_channel_data(channel)
            return None
        except Exception as e:
            return None

    def get_by_plataforma(self, plataforma: str):
        """Get sales channels by platform name."""
        try:
            # First find the platform ID
            p_resp = supabase_db.table('plataformas').select('id').eq('nome', plataforma).execute()
            if not p_resp.data:
                return []
            
            plataforma_id = p_resp.data[0]['id']
            
            response = self.table.select("*, plataformas(nome)").eq('plataforma_id', plataforma_id).execute()

            channels = []
            for row in response.data:
                channel = dict(row)
                channel['id'] = channel.get('id')
                channels.append(self._process_channel_data(channel))

            return channels
        except Exception as e:
            return []

    def get_by_bling_account(self, conta_bling_id: str):
        """Get sales channels by Bling account."""
        try:
            response = self.table.select("*, plataformas(nome)").eq('conta_bling_id', conta_bling_id).execute()

            channels = []
            for row in response.data:
                channel = dict(row)
                channel['id'] = channel.get('id')
                channels.append(self._process_channel_data(channel))

            return channels
        except Exception as e:
            return []

    def create(self, channel_data):
        """Create a new sales channel."""
        # Determine plataforma_id
        plataforma_id = channel_data.get('plataforma_id')

        if not plataforma_id and 'plataforma' in channel_data:
             p_resp = supabase_db.table('plataformas').select('id').eq('nome', channel_data['plataforma']).execute()
             if p_resp.data:
                 plataforma_id = p_resp.data[0]['id']

        # Prepare data - extract logistic rules before saving
        config = channel_data.get('configuracao', {})
        regras_logisticas = config.pop('regras_logisticas', {})  # Extract rules to process separately

        data = {
            'nome': channel_data['nome'],
            'slug': channel_data.get('slug'),
            'plataforma_id': plataforma_id,
            'conta_bling_id': str(channel_data['conta_bling_id']), # Ensure string
            'horario_coleta': channel_data.get('horario_coleta'),
            'configuracao': config, # Store remaining config without logistic rules
            'flex': channel_data.get('flex', False),
            'fulfillment': channel_data.get('fulfillment', False),
            'color': channel_data.get('color', '#007bff'),
            'ativo': channel_data.get('ativo', True),
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }

        response = self.table.insert(data).execute()
        if response.data:
            result = dict(response.data[0])
            new_id = result.get('id')

            # Criar regras logísticas na tabela específica
            if regras_logisticas:
                # Primeiro, deletar todas as regras existentes para este canal (caso existam)
                regra_logistica_service.delete_all_by_canal(new_id)

                # Depois, criar as novas regras
                regras_para_criar = []
                for modalidade, regras in regras_logisticas.items():
                    if isinstance(regras, list):
                        for regra in regras:
                            regras_para_criar.append({
                                'canal_venda_id': new_id,
                                'modalidade': modalidade,
                                'tipo_envio': regra.get('tipo') or regra.get('tipo_envio'),
                                'horario_limite': regra['horario_limite'],
                                'ponto_coleta_id': regra.get('ponto_coleta_id'),
                                'prioridade_uso': regra.get('prioridade_uso', 1)
                            })

                if regras_para_criar:
                    regra_logistica_service.bulk_create_regras(regras_para_criar)

            # Recuperar o canal completo após salvar as regras
            return self.get_by_id(new_id)

        return None

    def update(self, channel_id: str, channel_data):
        """Update an existing sales channel."""
        # Get existing channel
        existing = self.get_by_id(channel_id)
        if not existing:
            raise ValueError(f"Sales channel with ID '{channel_id}' not found")

        # Prepare update data
        update_data = {'updated_at': datetime.utcnow().isoformat()}

        field_mappings = {
            'nome': 'nome',
            'slug': 'slug',
            'plataforma_id': 'plataforma_id',
            'conta_bling_id': 'conta_bling_id',
            'horario_coleta': 'horario_coleta',
            'flex': 'flex',
            'fulfillment': 'fulfillment',
            'color': 'color',
            'ativo': 'ativo'
        }

        for field, key in field_mappings.items():
            if field in channel_data:
                update_data[key] = channel_data[field]

        # Tratar configuracao e regras logísticas separadamente
        if 'configuracao' in channel_data:
            config = { **channel_data['configuracao'] }
            regras_logisticas = config.pop('regras_logisticas', None)  # Extract logistic rules
            update_data['configuracao'] = config  # Store remaining config without logistic rules

            # Atualizar regras logísticas na tabela específica
            if regras_logisticas is not None:
                # Primeiro, deletar todas as regras existentes para este canal
                regra_logistica_service.delete_all_by_canal(int(channel_id))

                # Depois, criar as novas regras
                regras_para_criar = []
                for modalidade, regras in regras_logisticas.items():
                    if isinstance(regras, list):
                        for regra in regras:
                            regras_para_criar.append({
                                'canal_venda_id': int(channel_id),
                                'modalidade': modalidade,
                                'tipo_envio': regra.get('tipo') or regra.get('tipo_envio'),
                                'horario_limite': regra['horario_limite'],
                                'ponto_coleta_id': regra.get('ponto_coleta_id'),
                                'prioridade_uso': regra.get('prioridade_uso', 1)
                            })

                if regras_para_criar:
                    regra_logistica_service.bulk_create_regras(regras_para_criar)

        # Handle platform update by name if ID not explicitly passed
        if 'plataforma' in channel_data and 'plataforma_id' not in channel_data:
             p_resp = supabase_db.table('plataformas').select('id').eq('nome', channel_data['plataforma']).execute()
             if p_resp.data:
                 update_data['plataforma_id'] = p_resp.data[0]['id']

        self.table.update(update_data).eq('id', channel_id).execute()

        # Return updated channel
        return self.get_by_id(channel_id)

    def delete(self, channel_id: str):
        """Soft delete a sales channel by setting ativo to False."""
        self.table.update({
            'ativo': False,
            'updated_at': datetime.utcnow().isoformat()
        }).eq('id', channel_id).execute()

        return True

    def count(self):
        """Get total count of sales channels."""
        response = self.table.select("count(*)", count='exact').eq('ativo', True).execute()
        return response.count if response.count is not None else 0

# Global instance for use throughout the application
canal_venda_service = CanalVendaService()

