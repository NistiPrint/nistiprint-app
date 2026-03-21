"""
Serviço para gerenciar configuração de vínculos entre:
- Canais de venda internos
- Lojas Bling (bling_loja_id)
- Instâncias de integração (installed_integrations)

Este serviço substitui o uso de constants.py (BLING_ID_LOJA) para resolução dinâmica.
"""

from typing import Optional, Dict, Any, List
from nistiprint_shared.database.supabase_db_service import supabase_db
from datetime import datetime
import logging

logger = logging.getLogger("IntegracaoCanalService")


class IntegracaoCanalService:
    """Serviço para gestão de vínculos de integração."""

    def __init__(self):
        self.table_name = "integracao_canais_config"
        self._cache = {}
        self._cache_ttl = 300  # 5 minutos

    def get_canal_by_bling_loja_id(self, bling_loja_id: int) -> Optional[Dict[str, Any]]:
        """
        Busca o canal de venda vinculado a um ID de loja Bling.
        
        Args:
            bling_loja_id: ID da loja no Bling (ex: 204047801, 205218967)
            
        Returns:
            Dicionário com dados do canal ou None se não encontrado
        """
        cache_key = f"canal_by_bling_{bling_loja_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        try:
            # Buscar configuração ativa
            result = supabase_db.table(self.table_name).select("""
                id,
                canal_venda_id,
                integration_id,
                bling_loja_id,
                plataforma_nome,
                is_primary,
                config_json,
                canais_venda!inner (
                    id,
                    nome,
                    slug,
                    plataforma_id,
                    conta_bling_id,
                    ativo
                )
            """).eq('bling_loja_id', bling_loja_id).eq('is_active', True).execute()
            
            if result.data:
                config = result.data[0]
                canal = config.get('canais_venda')
                
                response = {
                    'canal_venda_id': config['canal_venda_id'],
                    'integration_id': config.get('integration_id'),
                    'bling_loja_id': config['bling_loja_id'],
                    'plataforma_nome': config.get('plataforma_nome'),
                    'is_primary': config.get('is_primary', False),
                    'canal_nome': canal.get('nome') if canal else None,
                    'canal_slug': canal.get('slug') if canal else None,
                    'canal_ativo': canal.get('ativo', True) if canal else False
                }
                
                self._cache[cache_key] = response
                return response
            
            # Fallback: buscar em canais_venda (coluna de fallback)
            fallback = supabase_db.table('canais_venda').select('id, nome, slug').eq('bling_loja_id_principal', bling_loja_id).execute()
            # ✅ VALIDAÇÃO DEFENSIVA: verificar se fallback.data existe e tem elementos
            if fallback.data and len(fallback.data) > 0:
                canal = fallback.data[0]
                response = {
                    'canal_venda_id': canal['id'],
                    'integration_id': None,
                    'bling_loja_id': bling_loja_id,
                    'plataforma_nome': None,
                    'is_primary': True,
                    'canal_nome': canal.get('nome'),
                    'canal_slug': canal.get('slug'),
                    'canal_ativo': True,
                    'fallback': True
                }
                self._cache[cache_key] = response
                return response

            return None

        except Exception as e:
            logger.error(f"Erro ao buscar canal por bling_loja_id {bling_loja_id}: {e}", exc_info=True)
            return None

    def get_bling_loja_id_by_canal(self, canal_venda_id: int, plataforma_nome: Optional[str] = None) -> Optional[int]:
        """
        Busca o ID da loja Bling vinculado a um canal de venda.
        
        Args:
            canal_venda_id: ID do canal de venda
            plataforma_nome: Nome da plataforma para filtrar (opcional)
            
        Returns:
            ID da loja Bling ou None se não encontrado
        """
        cache_key = f"bling_by_canal_{canal_venda_id}_{plataforma_nome}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        try:
            query = supabase_db.table(self.table_name).select('bling_loja_id, is_primary') \
                .eq('canal_venda_id', canal_venda_id) \
                .eq('is_active', True)
            
            if plataforma_nome:
                query = query.eq('plataforma_nome', plataforma_nome.lower())
            
            result = query.order('is_primary', desc=True).execute()
            
            if result.data:
                # Retorna o primário primeiro, ou o primeiro disponível
                bling_loja_id = result.data[0]['bling_loja_id']
                self._cache[cache_key] = bling_loja_id
                return bling_loja_id
            
            # Fallback: buscar em canais_venda
            fallback = supabase_db.table('canais_venda').select('bling_loja_id_principal').eq('id', canal_venda_id).execute()
            if fallback.data and fallback.data[0].get('bling_loja_id_principal'):
                self._cache[cache_key] = fallback.data[0]['bling_loja_id_principal']
                return fallback.data[0]['bling_loja_id_principal']
            
            return None
            
        except Exception as e:
            logger.error(f"Erro ao buscar bling_loja_id por canal {canal_venda_id}: {e}")
            return None

    def get_integration_by_canal(self, canal_venda_id: int) -> Optional[Dict[str, Any]]:
        """
        Busca a instância de integração vinculada a um canal.

        Args:
            canal_venda_id: ID do canal de venda

        Returns:
            Dicionário com dados da integração ou None
        """
        try:
            # Buscar configuração
            result = supabase_db.table(self.table_name).select("""
                integration_id,
                plataforma_nome,
                installed_integrations!inner (
                    id,
                    module_id,
                    instance_name,
                    is_active,
                    config,
                    credentials
                )
            """).eq('canal_venda_id', canal_venda_id).eq('is_active', True).execute()

            if result.data:
                config = result.data[0]
                # ✅ VALIDAÇÃO DEFENSIVA: installed_integrations pode ser None
                integration = config.get('installed_integrations') or {}

                return {
                    'integration_id': config['integration_id'],
                    'plataforma_nome': config.get('plataforma_nome'),
                    'module_id': integration.get('module_id') if integration else None,
                    'instance_name': integration.get('instance_name') if integration else None,
                    'is_active': integration.get('is_active', True) if integration else False,
                    'config': integration.get('config', {}) if integration else {},
                    'credentials': integration.get('credentials', {}) if integration else {}
                }

            # Fallback: buscar em canais_venda
            fallback = supabase_db.table('canais_venda').select('integration_id_principal').eq('id', canal_venda_id).execute()
            if fallback.data and fallback.data[0].get('integration_id_principal'):
                integration_id = fallback.data[0]['integration_id_principal']
                integration_result = supabase_db.table('installed_integrations').select('*').eq('id', integration_id).execute()
                # ✅ VALIDAÇÃO DEFENSIVA: verificar se integration_result.data existe
                if integration_result.data and len(integration_result.data) > 0:
                    integration = integration_result.data[0]
                    return {
                        'integration_id': integration_id,
                        'plataforma_nome': integration.get('module_id'),
                        'module_id': integration.get('module_id'),
                        'instance_name': integration.get('instance_name'),
                        'is_active': integration.get('is_active', True),
                        'config': integration.get('config', {}),
                        'credentials': integration.get('credentials', {}),
                        'fallback': True
                    }

            return None

        except Exception as e:
            logger.error(f"Erro ao buscar integração por canal {canal_venda_id}: {e}", exc_info=True)
            return None

    def get_config_by_id(self, config_id: str) -> Optional[Dict[str, Any]]:
        """Busca configuração específica por ID."""
        try:
            result = supabase_db.table(self.table_name).select("*").eq('id', config_id).execute()
            if result.data:
                return dict(result.data[0])
            return None
        except Exception as e:
            logger.error(f"Erro ao buscar configuração {config_id}: {e}")
            return None

    def listar_configuracoes(self, plataforma_nome: Optional[str] = None, 
                            canal_venda_id: Optional[int] = None,
                            include_inactive: bool = False) -> List[Dict[str, Any]]:
        """
        Lista configurações de vínculos com filtros opcionais.
        
        Args:
            plataforma_nome: Filtrar por plataforma (shopee, amazon, etc.)
            canal_venda_id: Filtrar por canal específico
            include_inactive: Incluir configurações inativas
            
        Returns:
            Lista de configurações
        """
        try:
            query = supabase_db.table(self.table_name).select("""
                *,
                canais_venda (
                    id,
                    nome,
                    slug,
                    ativo
                ),
                installed_integrations (
                    id,
                    module_id,
                    instance_name,
                    is_active
                )
            """).order('plataforma_nome', desc=False).order('is_primary', desc=True)
            
            if plataforma_nome:
                query = query.eq('plataforma_nome', plataforma_nome.lower())
            
            if canal_venda_id:
                query = query.eq('canal_venda_id', canal_venda_id)
            
            if not include_inactive:
                query = query.eq('is_active', True)
            
            result = query.execute()

            configs = []
            for row in result.data:
                # ✅ VALIDAÇÃO DEFENSIVA: joins podem retornar None
                canal = row.get('canais_venda') or {}
                integration = row.get('installed_integrations') or {}

                config = {
                    'id': row['id'],
                    'canal_venda_id': row['canal_venda_id'],
                    'integration_id': row.get('integration_id'),
                    'bling_loja_id': row['bling_loja_id'],
                    'plataforma_nome': row.get('plataforma_nome'),
                    'is_active': row.get('is_active', True),
                    'is_primary': row.get('is_primary', False),
                    'config_json': row.get('config_json', {}),
                    'created_at': row.get('created_at'),
                    'updated_at': row.get('updated_at'),
                    # ✅ Acesso seguro com fallback para None
                    'canal_nome': canal.get('nome') if canal else None,
                    'canal_slug': canal.get('slug') if canal else None,
                    'canal_ativo': canal.get('ativo', True) if canal else True,
                    'integration_instance_name': integration.get('instance_name') if integration else None,
                    'integration_module_id': integration.get('module_id') if integration else None,
                    'integration_active': integration.get('is_active', True) if integration else True
                }
                configs.append(config)

            return configs

        except Exception as e:
            logger.error(f"Erro ao listar configurações: {e}", exc_info=True)
            return []

    def criar_vinculo(self, canal_venda_id: int, bling_loja_id: int, 
                     plataforma_nome: str, integration_id: Optional[int] = None,
                     is_primary: bool = False, config_json: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """
        Cria novo vínculo entre canal e loja Bling.
        
        Args:
            canal_venda_id: ID do canal de venda
            bling_loja_id: ID da loja no Bling
            plataforma_nome: Nome da plataforma (shopee, amazon, etc.)
            integration_id: ID da instância de integração (opcional)
            is_primary: Se é o vínculo primário para esta plataforma
            config_json: Configurações adicionais
            
        Returns:
            Configuração criada ou None em caso de erro
        """
        try:
            # Verificar se já existe vínculo para este canal + loja
            existing = supabase_db.table(self.table_name).select('id').eq('canal_venda_id', canal_venda_id).eq('bling_loja_id', bling_loja_id).execute()
            if existing.data:
                logger.warning(f"Vínculo já existe para canal {canal_venda_id} e loja {bling_loja_id}")
                return None
            
            # Se é primário, remover primário existente para esta plataforma + canal
            if is_primary:
                supabase_db.table(self.table_name).update({'is_primary': False}).eq('canal_venda_id', canal_venda_id).eq('plataforma_nome', plataforma_nome.lower()).eq('is_active', True).execute()
            
            data = {
                'canal_venda_id': canal_venda_id,
                'bling_loja_id': bling_loja_id,
                'plataforma_nome': plataforma_nome.lower(),
                'integration_id': integration_id,
                'is_primary': is_primary,
                'is_active': True,
                'config_json': config_json or {}
            }
            
            result = supabase_db.table(self.table_name).insert(data).execute()
            
            # Limpar cache
            self._cache.clear()
            
            if result.data:
                return self.get_config_by_id(result.data[0]['id'])
            
            return None
            
        except Exception as e:
            logger.error(f"Erro ao criar vínculo: {e}")
            return None

    def atualizar_vinculo(self, config_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Atualiza vínculo existente.
        
        Args:
            config_id: ID da configuração
            updates: Dicionário com campos a atualizar
            
        Returns:
            Configuração atualizada ou None
        """
        try:
            # Se está marcando como primário, remover outros primários
            if updates.get('is_primary'):
                existing = self.get_config_by_id(config_id)
                if existing:
                    supabase_db.table(self.table_name).update({'is_primary': False}).eq('canal_venda_id', existing['canal_venda_id']).eq('plataforma_nome', existing['plataforma_nome']).neq('id', config_id).eq('is_active', True).execute()
            
            updates['updated_at'] = datetime.utcnow().isoformat()
            
            result = supabase_db.table(self.table_name).update(updates).eq('id', config_id).execute()
            
            # Limpar cache
            self._cache.clear()
            
            if result.data:
                return self.get_config_by_id(config_id)
            
            return None
            
        except Exception as e:
            logger.error(f"Erro ao atualizar vínculo {config_id}: {e}")
            return None

    def remover_vinculo(self, config_id: str) -> bool:
        """
        Remove vínculo (soft delete).
        
        Args:
            config_id: ID da configuração
            
        Returns:
            True se removido com sucesso
        """
        try:
            result = supabase_db.table(self.table_name).update({
                'is_active': False,
                'updated_at': datetime.utcnow().isoformat()
            }).eq('id', config_id).execute()
            
            # Limpar cache
            self._cache.clear()
            
            return result.data is not None
            
        except Exception as e:
            logger.error(f"Erro ao remover vínculo {config_id}: {e}")
            return False

    def resolver_canal_para_pedido(self, bling_loja_id: int, plataforma_nome: Optional[str] = None) -> Dict[str, Any]:
        """
        Resolve qual canal usar para um pedido baseado no bling_loja_id.
        
        Este é o método principal usado no processamento de webhooks.
        
        Args:
            bling_loja_id: ID da loja no pedido Bling
            plataforma_nome: Nome da plataforma (opcional, para fallback)
            
        Returns:
            Dicionário com channel_id e integration_id resolvidos
        """
        config = self.get_canal_by_bling_loja_id(bling_loja_id)
        
        if config:
            return {
                'channel_id': config['canal_venda_id'],
                'integration_id': config.get('integration_id'),
                'plataforma': config.get('plataforma_nome'),
                'resolved_from': 'integracao_canais_config',
                'is_primary': config.get('is_primary', False)
            }
        
        # Fallback: tentar resolver por plataforma
        if plataforma_nome:
            configs = self.listar_configuracoes(plataforma_nome=plataforma_nome)
            if configs:
                # Retorna o primário ou o primeiro
                primary = next((c for c in configs if c.get('is_primary')), configs[0])
                return {
                    'channel_id': primary['canal_venda_id'],
                    'integration_id': primary.get('integration_id'),
                    'plataforma': primary.get('plataforma_nome'),
                    'resolved_from': 'plataforma_fallback',
                    'is_primary': primary.get('is_primary', False)
                }
        
        # Fallback final: retornar None para tratamento no código chamador
        return {
            'channel_id': None,
            'integration_id': None,
            'plataforma': plataforma_nome,
            'resolved_from': 'none',
            'is_primary': False
        }

    def clear_cache(self):
        """Limpa o cache em memória."""
        self._cache.clear()


# Instância global
integracao_canal_service = IntegracaoCanalService()
