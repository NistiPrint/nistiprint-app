from typing import Optional, Dict, Any
from nistiprint_shared.database.supabase_db_service import supabase_db
import logging

class IntegrationRoutingService:
    """
    Serviço para gerenciar o roteamento de contas de integração por função e escopo.
    Permite que múltiplas contas da mesma plataforma (ex: Bling) coexistam,
    sendo selecionadas dinamicamente conforme a necessidade (NFe, Importação, etc).
    """

    def __init__(self):
        self.table_name = "integration_account_routing"

    def get_account_id(self, function_name: str, module: str = 'bling', 
                       channel_id: Optional[int] = None, 
                       platform_name: Optional[str] = None) -> Optional[str]:
        """
        Resolve o ID da conta a ser utilizada baseado na hierarquia de escopo:
        1. Canal (Mais específico)
        2. Plataforma
        3. Global (Fallback)
        """
        try:
            # 1. Tentar por Canal
            if channel_id:
                res = supabase_db.table(self.table_name).select("account_id") \
                    .eq('module', module) \
                    .eq('function_name', function_name) \
                    .eq('scope_type', 'CHANNEL') \
                    .eq('scope_id', str(channel_id)) \
                    .eq('is_active', True) \
                    .execute()
                if res.data:
                    return res.data[0]['account_id']

            # 2. Tentar por Plataforma
            if platform_name:
                res = supabase_db.table(self.table_name).select("account_id") \
                    .eq('module', module) \
                    .eq('function_name', function_name) \
                    .eq('scope_type', 'PLATFORM') \
                    .eq('scope_id', platform_name) \
                    .eq('is_active', True) \
                    .execute()
                if res.data:
                    return res.data[0]['account_id']

            # 3. Tentar Global
            res = supabase_db.table(self.table_name).select("account_id") \
                .eq('module', module) \
                .eq('function_name', function_name) \
                .eq('scope_type', 'GLOBAL') \
                .eq('is_active', True) \
                .execute()
            if res.data:
                return res.data[0]['account_id']

            # 4. Fallback para App Config (legacy binding)
            from nistiprint_shared.services.app_config_service import app_config_service
            bindings = app_config_service.get_config('platform_account_bindings') or {}
            
            # Se tivermos canal, o canal pode ter uma conta vinculada diretamente (coluna legada)
            if channel_id:
                channel_res = supabase_db.table('canais_venda').select('conta_bling_id').eq('id', channel_id).execute()
                if channel_res.data and channel_res.data[0].get('conta_bling_id'):
                    return channel_res.data[0]['conta_bling_id']

            # Fallback por plataforma nas bindings globais
            if platform_name and platform_name in bindings:
                return bindings[platform_name]

            return None

        except Exception as e:
            logging.error(f"Erro ao resolver roteamento de conta ({module}:{function_name}): {e}")
            return None

    def set_routing(self, function_name: str, scope_type: str, scope_id: Optional[str], 
                    account_id: str, module: str = 'bling') -> bool:
        """Configura ou atualiza uma regra de roteamento."""
        try:
            data = {
                'module': module,
                'function_name': function_name,
                'scope_type': scope_type,
                'scope_id': scope_id,
                'account_id': account_id,
                'is_active': True,
                'updated_at': 'now()'
            }
            
            # Upsert manual (check existence first for simplicity in mapping logic)
            query = supabase_db.table(self.table_name).select("id") \
                .eq('module', module) \
                .eq('function_name', function_name) \
                .eq('scope_type', scope_type)
            
            if scope_id:
                query = query.eq('scope_id', scope_id)
            else:
                query = query.is_('scope_id', 'null')
                
            existing = query.execute()
            
            if existing.data:
                supabase_db.table(self.table_name).update(data).eq('id', existing.data[0]['id']).execute()
            else:
                supabase_db.table(self.table_name).insert(data).execute()
                
            return True
        except Exception as e:
            logging.error(f"Erro ao salvar roteamento: {e}")
            return False

# Instância global
integration_routing_service = IntegrationRoutingService()
