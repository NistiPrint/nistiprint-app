"""
Serviço para gerenciar configuração de vínculos entre:
- Canais de venda internos
- Lojas Bling (aggregator_store_id)
- Instâncias de integração (installed_integrations)

Nova arquitetura (Fase 2 - Refatoração):
- Usa channel_connections como tabela principal
- Mantém fallback para integracao_canais_config durante transição
- Mantém fallback para canais_venda.colunas_legacy

Este serviço substitui o uso de constants.py (BLING_ID_LOJA) para resolução dinâmica.
"""

from typing import Optional, Dict, Any, List
from nistiprint_shared.database.supabase_db_service import supabase_db
from datetime import datetime
import logging

logger = logging.getLogger("IntegracaoCanalService")


class IntegracaoCanalService:
    """Serviço para gestão de vínculos de integração."""

    MARKETPLACE_MODULES = {
        'shopee',
        'amazon',
        'amazonfba_classic',
        'amazon_fulfillment',
        'mercadolivre',
        'shein',
        'tiktok',
        'tiktokshop',
        'kwai',
        'lojaintegrada',
        'magazineluiza',
    }

    def __init__(self):
        # Tabela principal (nova arquitetura)
        self.table_name = "channel_connections"
        # Tabela legada (fallback durante transição)
        self.legacy_table_name = "integracao_canais_config"
        self._cache = {}
        self._cache_ttl = 300  # 5 minutos

    def _normalize_module(self, module_id: Optional[str]) -> Optional[str]:
        return module_id.lower().strip() if module_id else None

    def _safe_int(self, value: Any) -> Optional[int]:
        if value is None or value == '':
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _get_installed_integration(
        self,
        integration_id: Any,
        expected_module: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        integration_id = self._safe_int(integration_id)
        if not integration_id:
            return None

        query = supabase_db.table('installed_integrations').select('*') \
            .eq('id', integration_id) \
            .eq('is_active', True)

        if expected_module:
            query = query.eq('module_id', self._normalize_module(expected_module))

        result = query.execute()
        if result.data:
            return result.data[0]
        return None

    def _get_erp_marketplace_link(
        self,
        erp_integration_id: Any,
        erp_store_id: Any,
        expected_module: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Busca o vinculo ERP loja -> marketplace instalado."""
        erp_integration_id = self._safe_int(erp_integration_id)
        if not erp_integration_id or erp_store_id in (None, ''):
            return None

        try:
            result = supabase_db.table('erp_marketplace_links') \
                .select('*') \
                .eq('erp_integration_id', erp_integration_id) \
                .eq('erp_store_id', str(erp_store_id)) \
                .execute()

            for link in result.data or []:
                marketplace_id = link.get('marketplace_integration_id')
                if expected_module and marketplace_id:
                    integration = self._get_installed_integration(marketplace_id, expected_module)
                    if not integration:
                        continue
                    link['marketplace'] = integration
                return link
        except Exception as e:
            logger.warning(
                "Erro ao buscar erp_marketplace_links (erp=%s, store=%s): %s",
                erp_integration_id,
                erp_store_id,
                e
            )
        return None

    def _enrich_connection_from_erp_link(
        self,
        row: Dict[str, Any],
        expected_module: Optional[str] = None
    ) -> Dict[str, Any]:
        """Preenche marketplace_integration_id a partir de erp_marketplace_links quando a conexao esta incompleta."""
        enriched = dict(row)
        if enriched.get('marketplace_integration_id'):
            return enriched

        for erp_integration_id in (enriched.get('bling_integration_id'), enriched.get('integration_id')):
            link = self._get_erp_marketplace_link(
                erp_integration_id,
                enriched.get('aggregator_store_id'),
                expected_module=expected_module
            )
            if link:
                enriched['marketplace_integration_id'] = link.get('marketplace_integration_id')
                enriched['erp_marketplace_link_id'] = link.get('id')
                enriched['erp_marketplace_config'] = link.get('config') or {}
                if not enriched.get('bling_integration_id'):
                    enriched['bling_integration_id'] = link.get('erp_integration_id')
                break

        return enriched

    def _build_integration_response(
        self,
        row: Dict[str, Any],
        integration: Dict[str, Any],
        target_id: int,
        fallback: Optional[str] = None
    ) -> Dict[str, Any]:
        response = {
            'connection_id': row.get('id'),
            'integration_id': target_id,
            'bling_integration_id': row.get('bling_integration_id'),
            'marketplace_integration_id': row.get('marketplace_integration_id'),
            'aggregator_store_id': (
                row.get('aggregator_store_id')
                or (str(row.get('bling_loja_id')) if row.get('bling_loja_id') else None)
            ),
            'plataforma_nome': row.get('plataforma_nome') or self._extract_platform_from_store_name(row.get('aggregator_store_name')),
            'module_id': integration.get('module_id'),
            'instance_name': integration.get('instance_name'),
            'is_active': integration.get('is_active', True),
            'config': integration.get('config', {}),
            'credentials': integration.get('credentials', {}),
            'erp_marketplace_link_id': row.get('erp_marketplace_link_id'),
            'erp_marketplace_config': row.get('erp_marketplace_config', {}),
        }
        if fallback:
            response['fallback'] = fallback
        return response

    def _resolve_integration_from_connection(
        self,
        row: Dict[str, Any],
        expected_module: Optional[str] = None,
        fallback: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        expected_module = self._normalize_module(expected_module)
        row = self._enrich_connection_from_erp_link(row, expected_module)

        if expected_module == 'bling':
            candidate_ids = [row.get('bling_integration_id'), row.get('integration_id')]
        elif expected_module in self.MARKETPLACE_MODULES:
            candidate_ids = [row.get('marketplace_integration_id'), row.get('integration_id')]
        elif expected_module:
            candidate_ids = [row.get('marketplace_integration_id'), row.get('integration_id'), row.get('bling_integration_id')]
        else:
            candidate_ids = [row.get('marketplace_integration_id'), row.get('integration_id'), row.get('bling_integration_id')]

        seen = set()
        for target_id in candidate_ids:
            target_id = self._safe_int(target_id)
            if not target_id or target_id in seen:
                continue
            seen.add(target_id)

            integration = self._get_installed_integration(target_id, expected_module)
            if integration:
                return self._build_integration_response(row, integration, target_id, fallback=fallback)

        return None

    def _sync_erp_marketplace_link(self, row: Dict[str, Any]) -> None:
        if not row:
            return

        bling_integration_id = row.get('bling_integration_id')
        marketplace_integration_id = row.get('marketplace_integration_id')
        store_id = row.get('aggregator_store_id') or row.get('bling_loja_id')

        if not (bling_integration_id and marketplace_integration_id and store_id):
            return

        try:
            supabase_db.table('erp_marketplace_links').upsert({
                'erp_integration_id': bling_integration_id,
                'marketplace_integration_id': marketplace_integration_id,
                'erp_store_id': str(store_id),
                'store_name': row.get('aggregator_store_name') or str(store_id),
                'config': row.get('config') or row.get('config_json') or {},
                'updated_at': datetime.utcnow().isoformat()
            }, on_conflict='erp_integration_id,erp_store_id').execute()
        except Exception as link_error:
            logger.warning("Falha ao sincronizar erp_marketplace_links: %s", link_error)

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
            # 1. Buscar em channel_connections (nova tabela)
            result = supabase_db.table(self.table_name).select("""
                id,
                channel_id,
                integration_id,
                bling_integration_id,
                marketplace_integration_id,
                aggregator_store_id,
                aggregator_store_name,
                config,
                sync_status,
                is_active,
                canais_venda!inner (
                    id,
                    nome,
                    slug,
                    plataforma_id,
                    conta_bling_id,
                    ativo
                )
            """).eq('aggregator_store_id', str(bling_loja_id)).eq('is_active', True).execute()

            if result.data:
                config = self._enrich_connection_from_erp_link(result.data[0])
                canal = config.get('canais_venda')

                response = {
                    'canal_venda_id': config['channel_id'],
                    'connection_id': config['id'],
                    'integration_id': config.get('integration_id'),
                    'bling_integration_id': config.get('bling_integration_id'),
                    'marketplace_integration_id': config.get('marketplace_integration_id'),
                    'bling_loja_id': config['aggregator_store_id'],
                    'aggregator_store_name': config.get('aggregator_store_name'),
                    'plataforma_nome': self._extract_platform_from_store_name(config.get('aggregator_store_name')),
                    'is_primary': str(config.get('sync_status')).lower() in ('true', 'primary'),
                    'canal_nome': canal.get('nome') if canal else None,
                    'canal_slug': canal.get('slug') if canal else None,
                    'canal_ativo': canal.get('ativo', True) if canal else False,
                    'config': config.get('config', {}),
                    'erp_marketplace_link_id': config.get('erp_marketplace_link_id'),
                    'erp_marketplace_config': config.get('erp_marketplace_config', {}),
                    'resolved_from': 'channel_connections'
                }

                self._cache[cache_key] = response
                return response

            # 2. Fallback: buscar em integracao_canais_config (tabela legada)
            fallback_legacy = supabase_db.table(self.legacy_table_name).select("""
                id,
                canal_venda_id,
                integration_id,
                bling_integration_id,
                marketplace_integration_id,
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

            if fallback_legacy.data:
                config = fallback_legacy.data[0]
                canal = config.get('canais_venda')

                response = {
                    'canal_venda_id': config['canal_venda_id'],
                    'connection_id': config['id'],
                    'integration_id': config.get('integration_id'),
                    'bling_integration_id': config.get('bling_integration_id'),
                    'marketplace_integration_id': config.get('marketplace_integration_id'),
                    'bling_loja_id': config['bling_loja_id'],
                    'aggregator_store_name': None,
                    'plataforma_nome': config.get('plataforma_nome'),
                    'is_primary': config.get('is_primary', False),
                    'canal_nome': canal.get('nome') if canal else None,
                    'canal_slug': canal.get('slug') if canal else None,
                    'canal_ativo': canal.get('ativo', True) if canal else False,
                    'config': config.get('config_json', {}),
                    'fallback': 'legacy_table'
                }

                self._cache[cache_key] = response
                return response

            # 3. Fallback: buscar em canais_venda (colunas legacy)
            fallback = supabase_db.table('canais_venda').select('id, nome, slug').eq('bling_loja_id_principal', bling_loja_id).execute()
            # ✅ VALIDAÇÃO DEFENSIVA: verificar se fallback.data existe e tem elementos
            if fallback.data and len(fallback.data) > 0:
                canal = fallback.data[0]
                response = {
                    'canal_venda_id': canal['id'],
                    'connection_id': None,
                    'integration_id': None,
                    'bling_integration_id': None,
                    'marketplace_integration_id': None,
                    'bling_loja_id': bling_loja_id,
                    'aggregator_store_name': None,
                    'plataforma_nome': None,
                    'is_primary': True,
                    'canal_nome': canal.get('nome'),
                    'canal_slug': canal.get('slug'),
                    'canal_ativo': True,
                    'fallback': 'canais_venda_legacy'
                }
                self._cache[cache_key] = response
                return response

            return None

        except Exception as e:
            logger.error(f"Erro ao buscar canal por bling_loja_id {bling_loja_id}: {e}", exc_info=True)
            return None

    def _extract_platform_from_store_name(self, store_name: str) -> Optional[str]:
        """Extrai nome da plataforma do aggregator_store_name."""
        if not store_name:
            return None
        
        store_name_lower = store_name.lower()
        if 'shopee' in store_name_lower:
            return 'shopee'
        elif 'amazon' in store_name_lower:
            return 'amazonfba_classic'
        elif 'mercado livre' in store_name_lower or 'mercadolivre' in store_name_lower:
            return 'mercadolivre'
        elif 'shein' in store_name_lower:
            return 'shein'
        elif 'tiktok' in store_name_lower:
            return 'tiktokshop'
        elif 'kwai' in store_name_lower:
            return 'kwai'
        elif 'loja integrada' in store_name_lower or 'lojaintegrada' in store_name_lower:
            return 'lojaintegrada'
        elif 'magazine luiza' in store_name_lower or 'magazineluiza' in store_name_lower or 'magalu' in store_name_lower:
            return 'magazineluiza'
        else:
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
            # 1. Buscar em channel_connections (nova tabela)
            query = supabase_db.table(self.table_name).select('aggregator_store_id, is_active') \
                .eq('channel_id', canal_venda_id) \
                .eq('is_active', True)

            if plataforma_nome:
                # Filtrar por plataforma usando LIKE no aggregator_store_name
                query = query.ilike('aggregator_store_name', f'%{plataforma_nome}%')

            result = query.order('created_at', desc=True).execute()

            if result.data:
                aggregator_store_id = result.data[0]['aggregator_store_id']
                if aggregator_store_id:
                    bling_loja_id = int(aggregator_store_id)
                    self._cache[cache_key] = bling_loja_id
                    return bling_loja_id

            # 2. Fallback: buscar em integracao_canais_config (tabela legada)
            fallback_legacy = supabase_db.table(self.legacy_table_name).select('bling_loja_id, is_primary') \
                .eq('canal_venda_id', canal_venda_id) \
                .eq('is_active', True)

            if plataforma_nome:
                fallback_legacy = fallback_legacy.eq('plataforma_nome', plataforma_nome.lower())

            fallback_legacy_result = fallback_legacy.order('is_primary', desc=True).execute()

            if fallback_legacy_result.data:
                bling_loja_id = fallback_legacy_result.data[0]['bling_loja_id']
                self._cache[cache_key] = bling_loja_id
                return bling_loja_id

            # 3. Fallback: buscar em canais_venda
            fallback = supabase_db.table('canais_venda').select('bling_loja_id_principal').eq('id', canal_venda_id).execute()
            if fallback.data and fallback.data[0].get('bling_loja_id_principal'):
                self._cache[cache_key] = fallback.data[0]['bling_loja_id_principal']
                return fallback.data[0]['bling_loja_id_principal']

            return None

        except Exception as e:
            logger.error(f"Erro ao buscar bling_loja_id por canal {canal_venda_id}: {e}")
            return None

    def get_integration_by_canal(
        self,
        canal_venda_id: int,
        expected_module: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        Busca a instância de integração vinculada a um canal.

        Args:
            canal_venda_id: ID do canal de venda
            expected_module: Módulo esperado ('bling', 'shopee', 'amazon', etc.)
                           Se None, usa comportamento legado (pode retornar módulo errado)

        Returns:
            Dicionário com dados da integração ou None se não encontrado
        """
        try:
            # 1. Buscar em channel_connections (nova tabela)
            result = supabase_db.table(self.table_name).select(
                "id, channel_id, integration_id, bling_integration_id, marketplace_integration_id, aggregator_store_id, aggregator_store_name, config"
            ).eq('channel_id', canal_venda_id).eq('is_active', True).order('created_at', desc=True).execute()

            if result.data:
                row = self._enrich_connection_from_erp_link(result.data[0], expected_module)
                
                # Extrair plataforma do aggregator_store_name
                plataforma_nome = self._extract_platform_from_store_name(row.get('aggregator_store_name'))

                # Selecionar integração baseada no module_id esperado
                if expected_module:
                    if expected_module.lower() == 'bling':
                        # Priorizar bling_integration_id, fallback para integration_id legado
                        target_id = row.get('bling_integration_id') or row.get('integration_id')
                    elif expected_module.lower() in ['shopee', 'amazon', 'mercadolivre', 'shein', 'tiktok']:
                        # Priorizar marketplace_integration_id, fallback para integration_id legado
                        target_id = row.get('marketplace_integration_id') or row.get('integration_id')
                    else:
                        # Módulo genérico: usar marketplace_integration_id ou integration_id
                        target_id = row.get('marketplace_integration_id') or row.get('integration_id')
                else:
                    # Comportamento legado: priorizar marketplace_integration_id
                    target_id = row.get('marketplace_integration_id') or row.get('integration_id')

                if not target_id:
                    logger.debug(f"Canal {canal_venda_id}: Nenhum ID de integração encontrado")
                    return None

                # Buscar integração com validação de module_id se expected_module for fornecido
                query = supabase_db.table('installed_integrations').select('*').eq('id', target_id)

                if expected_module:
                    query = query.eq('module_id', expected_module.lower())

                query = query.eq('is_active', True).execute()

                integration_result = query

                if not integration_result.data:
                    if expected_module:
                        logger.error(
                            f"Integração {target_id} não é do módulo '{expected_module}' ou está inativa. "
                            f"Verifique o vínculo em channel_connections para canal {canal_venda_id}"
                        )
                        return None
                    else:
                        logger.warning(
                            f"Integração {target_id} não encontrada ou inativa para canal {canal_venda_id}"
                        )
                        return None

                integration = integration_result.data[0]
                return {
                    'connection_id': row.get('id'),
                    'integration_id': target_id,
                    'bling_integration_id': row.get('bling_integration_id'),
                    'marketplace_integration_id': row.get('marketplace_integration_id'),
                    'aggregator_store_id': row.get('aggregator_store_id'),
                    'plataforma_nome': plataforma_nome,
                    'module_id': integration.get('module_id'),
                    'instance_name': integration.get('instance_name'),
                    'is_active': integration.get('is_active', True),
                    'config': integration.get('config', {}),
                    'credentials': integration.get('credentials', {}),
                }

            # 2. Fallback: buscar em integracao_canais_config (tabela legada)
            fallback_legacy = supabase_db.table(self.legacy_table_name).select(
                "id, canal_venda_id, integration_id, bling_integration_id, marketplace_integration_id, bling_loja_id, plataforma_nome"
            ).eq('canal_venda_id', canal_venda_id).eq('is_active', True).order('is_primary', desc=True).execute()

            if fallback_legacy.data:
                row = fallback_legacy.data[0]

                # Selecionar integração baseada no module_id esperado
                if expected_module:
                    if expected_module.lower() == 'bling':
                        target_id = row.get('bling_integration_id') or row.get('integration_id')
                    elif expected_module.lower() in ['shopee', 'amazon', 'mercadolivre', 'shein', 'tiktok']:
                        target_id = row.get('marketplace_integration_id') or row.get('integration_id')
                    else:
                        target_id = row.get('marketplace_integration_id') or row.get('integration_id')
                else:
                    target_id = row.get('marketplace_integration_id') or row.get('integration_id')

                if not target_id:
                    logger.debug(f"Canal {canal_venda_id}: Nenhum ID de integração encontrado (legado)")
                    return None

                # Buscar integração
                query = supabase_db.table('installed_integrations').select('*').eq('id', target_id)
                if expected_module:
                    query = query.eq('module_id', expected_module.lower())
                query = query.eq('is_active', True).execute()

                integration_result = query

                if not integration_result.data:
                    if expected_module:
                        logger.error(
                            f"Integração {target_id} não é do módulo '{expected_module}' ou está inativa."
                        )
                        return None
                    else:
                        logger.warning(
                            f"Integração {target_id} não encontrada ou inativa para canal {canal_venda_id}"
                        )
                    return None

                integration = integration_result.data[0]
                return {
                    'connection_id': row.get('id'),
                    'integration_id': target_id,
                    'bling_integration_id': row.get('bling_integration_id'),
                    'marketplace_integration_id': row.get('marketplace_integration_id'),
                    'aggregator_store_id': str(row.get('bling_loja_id')) if row.get('bling_loja_id') else None,
                    'plataforma_nome': row.get('plataforma_nome'),
                    'module_id': integration.get('module_id'),
                    'instance_name': integration.get('instance_name'),
                    'is_active': integration.get('is_active', True),
                    'config': integration.get('config', {}),
                    'credentials': integration.get('credentials', {}),
                    'fallback': 'legacy_table'
                }

            # 3. Fallback: buscar em canais_venda (colunas legacy)
            fallback = supabase_db.table('canais_venda').select('integration_id_principal').eq('id', canal_venda_id).execute()
            if fallback.data and fallback.data[0].get('integration_id_principal'):
                integration_id = fallback.data[0]['integration_id_principal']

                # Validar module_id se expected_module for fornecido
                query = supabase_db.table('installed_integrations').select('*').eq('id', integration_id)
                if expected_module:
                    query = query.eq('module_id', expected_module.lower())
                query = query.eq('is_active', True).execute()

                integration_result = query

                if integration_result.data and len(integration_result.data) > 0:
                    integration = integration_result.data[0]
                    return {
                        'connection_id': None,
                        'integration_id': integration_id,
                        'bling_integration_id': None,
                        'marketplace_integration_id': None,
                        'aggregator_store_id': None,
                        'plataforma_nome': integration.get('module_id'),
                        'module_id': integration.get('module_id'),
                        'instance_name': integration.get('instance_name'),
                        'is_active': integration.get('is_active', True),
                        'config': integration.get('config', {}),
                        'credentials': integration.get('credentials', {}),
                        'fallback': 'canais_venda_legacy'
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
                    ativo,
                    plataforma_id
                )
            """).order('created_at', desc=False)

            if plataforma_nome:
                query = query.ilike('aggregator_store_name', f'%{plataforma_nome}%')

            if canal_venda_id:
                query = query.eq('channel_id', canal_venda_id)

            if not include_inactive:
                query = query.eq('is_active', True)

            result = query.execute()
            rows = [self._enrich_connection_from_erp_link(row) for row in (result.data or [])]

            ii_ids = set()
            for row in rows:
                for k in ('integration_id', 'bling_integration_id', 'marketplace_integration_id'):
                    v = row.get(k)
                    if v is not None:
                        ii_ids.add(int(v))

            ii_map = {}
            if ii_ids:
                ir = supabase_db.table('installed_integrations').select(
                    'id, module_id, instance_name, is_active'
                ).in_('id', list(ii_ids)).execute()
                for r in (ir.data or []):
                    ii_map[r['id']] = r

            configs = []
            for row in rows:
                canal = row.get('canais_venda') or {}
                leg = ii_map.get(row.get('integration_id')) if row.get('integration_id') else None
                bi = ii_map.get(row.get('bling_integration_id')) if row.get('bling_integration_id') else None
                mi = ii_map.get(row.get('marketplace_integration_id')) if row.get('marketplace_integration_id') else None
                
                # Buscar nome da plataforma via plataforma_id (FK para plataformas)
                plataforma_nome = None
                if canal.get('plataforma_id'):
                    try:
                        plat_result = supabase_db.table('plataformas').select('nome').eq('id', canal.get('plataforma_id')).execute()
                        if plat_result.data:
                            plataforma_nome = plat_result.data[0].get('nome')
                    except Exception:
                        pass  # Se não encontrar, deixa None

                config = {
                    'id': row['id'],
                    'canal_venda_id': row['channel_id'],
                    'integration_id': row.get('integration_id'),
                    'bling_integration_id': row.get('bling_integration_id'),
                    'marketplace_integration_id': row.get('marketplace_integration_id'),
                    'bling_loja_id': row.get('aggregator_store_id'),
                    'aggregator_store_name': row.get('aggregator_store_name'),
                    'plataforma_nome': plataforma_nome or self._extract_platform_from_store_name(row.get('aggregator_store_name')),
                    'is_active': row.get('is_active', True),
                    'is_primary': str(row.get('sync_status')).lower() in ('true', 'primary'),
                    'config_json': row.get('config', {}),
                    'created_at': row.get('created_at'),
                    'updated_at': row.get('updated_at'),
                    'canal_nome': canal.get('nome') if canal else None,
                    'canal_slug': canal.get('slug') if canal else None,
                    'canal_ativo': canal.get('ativo', True) if canal else True,
                    'integration_instance_name': leg.get('instance_name') if leg else None,
                    'integration_module_id': leg.get('module_id') if leg else None,
                    'integration_active': leg.get('is_active', True) if leg else True,
                    'bling_integration': bi,
                    'marketplace_integration': mi,
                }
                configs.append(config)

            return configs

        except Exception as e:
            logger.error(f"Erro ao listar configurações: {e}", exc_info=True)
            return []

    def criar_vinculo(self, canal_venda_id: int, bling_loja_id: int,
                     plataforma_nome: str, integration_id: Optional[int] = None,
                     bling_integration_id: Optional[int] = None,
                     marketplace_integration_id: Optional[int] = None,
                     is_primary: bool = False, config_json: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """
        Cria novo vínculo entre canal e loja Bling.

        bling_integration_id / marketplace_integration_id: instâncias em installed_integrations.
        integration_id: legado; se omitido, usa marketplace_integration_id ou bling_integration_id.
        """
        try:
            # Verificar se já existe vínculo para este canal + loja
            existing = supabase_db.table(self.table_name).select('id') \
                .eq('channel_id', canal_venda_id) \
                .eq('aggregator_store_id', str(bling_loja_id)) \
                .eq('is_active', True) \
                .execute()
            if existing.data:
                logger.warning(f"Vínculo já existe para canal {canal_venda_id} e loja {bling_loja_id}")
                return None

            if is_primary:
                supabase_db.table(self.table_name).update({'sync_status': 'active'}) \
                    .eq('channel_id', canal_venda_id) \
                    .ilike('aggregator_store_name', f'%{plataforma_nome}%') \
                    .eq('is_active', True) \
                    .execute()

            legacy_integration_id = integration_id
            if legacy_integration_id is None:
                legacy_integration_id = bling_integration_id or marketplace_integration_id

            data = {
                'channel_id': canal_venda_id,
                'integration_id': legacy_integration_id,
                'bling_integration_id': bling_integration_id,
                'marketplace_integration_id': marketplace_integration_id,
                'aggregator_store_id': str(bling_loja_id),
                'aggregator_store_name': f"{plataforma_nome} ({bling_loja_id})",
                'is_active': True,
                'sync_status': 'primary' if is_primary else 'active',
                'config': config_json or {}
            }
            
            result = supabase_db.table(self.table_name).insert(data).execute()

            self._sync_erp_marketplace_link(data)
            
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
                    supabase_db.table(self.table_name).update({'sync_status': 'active'}) \
                        .eq('channel_id', existing['channel_id']) \
                        .neq('id', config_id) \
                        .eq('is_active', True) \
                        .execute()

            field_map = {
                'canal_venda_id': 'channel_id',
                'bling_loja_id': 'aggregator_store_id',
                'config_json': 'config',
            }
            for old_key, new_key in field_map.items():
                if old_key in updates:
                    updates[new_key] = updates.pop(old_key)
            if 'aggregator_store_id' in updates and updates['aggregator_store_id'] is not None:
                updates['aggregator_store_id'] = str(updates['aggregator_store_id'])
            if 'plataforma_nome' in updates:
                plataforma_nome = updates.pop('plataforma_nome')
                existing = self.get_config_by_id(config_id) or {}
                store_id = updates.get('aggregator_store_id') or existing.get('aggregator_store_id')
                updates['aggregator_store_name'] = f"{plataforma_nome} ({store_id})" if store_id else plataforma_nome
            if 'is_primary' in updates:
                updates['sync_status'] = 'primary' if updates.pop('is_primary') else 'active'

            if 'integration_id' not in updates:
                if updates.get('bling_integration_id') is not None:
                    updates['integration_id'] = updates['bling_integration_id']
                elif updates.get('marketplace_integration_id') is not None:
                    updates['integration_id'] = updates['marketplace_integration_id']

            updates['updated_at'] = datetime.utcnow().isoformat()
            
            result = supabase_db.table(self.table_name).update(updates).eq('id', config_id).execute()
            
            # Limpar cache
            self._cache.clear()
            
            if result.data:
                updated = self.get_config_by_id(config_id)
                self._sync_erp_marketplace_link(updated)
                return updated
            
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
                'bling_integration_id': config.get('bling_integration_id'),
                'marketplace_integration_id': config.get('marketplace_integration_id'),
                'plataforma': config.get('plataforma_nome'),
                'resolved_from': config.get('resolved_from') or config.get('fallback') or 'channel_connections',
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
                    'bling_integration_id': primary.get('bling_integration_id'),
                    'marketplace_integration_id': primary.get('marketplace_integration_id'),
                    'plataforma': primary.get('plataforma_nome'),
                    'resolved_from': 'plataforma_fallback',
                    'is_primary': primary.get('is_primary', False)
                }
        
        # Fallback final: retornar None para tratamento no código chamador
        return {
            'channel_id': None,
            'integration_id': None,
            'bling_integration_id': None,
            'marketplace_integration_id': None,
            'plataforma': plataforma_nome,
            'resolved_from': 'none',
            'is_primary': False
        }

    def resolver_por_bling_integration_e_loja(
        self, bling_integration_id: int, bling_loja_id: int
    ) -> Optional[Dict[str, Any]]:
        """Resolve vínculo quando há mais de uma conta Bling (contexto explícito)."""
        try:
            res = supabase_db.table(self.table_name).select("*").eq(
                'bling_integration_id', bling_integration_id
            ).eq('aggregator_store_id', str(bling_loja_id)).eq('is_active', True).execute()
            if res.data:
                return self._enrich_connection_from_erp_link(res.data[0])
            return None
        except Exception as e:
            logger.error(f"resolver_por_bling_integration_e_loja: {e}")
            return None

    def analisar_vinculos_com_status(self) -> Dict[str, Any]:
        """
        Analisa todos os vínculos e retorna status detalhado.

        Returns:
            dict com:
                - completos: vínculos com ambas integrações ativas
                - incompletos: vínculos com apenas uma integração ativa
                - orfaos: vínculos com integração que não existe
                - placeholders: vínculos com integração placeholder
        """
        vinculos = self.listar_configuracoes(include_inactive=False)

        # Buscar todas as integrações para montar mapa
        integrations_result = supabase_db.table('installed_integrations').select('*').execute()
        integrations = integrations_result.data or []
        integration_map = {i['id']: i for i in integrations}

        resultados = {
            'completos': [],
            'incompletos': [],
            'orfaos': [],
            'placeholders': []
        }

        for vinculo in vinculos:
            bling_int_id = vinculo.get('bling_integration_id')
            mp_int_id = vinculo.get('marketplace_integration_id')

            bling_int = integration_map.get(bling_int_id) if bling_int_id else None
            mp_int = integration_map.get(mp_int_id) if mp_int_id else None

            # Verificar status
            bling_ok = (bling_int and bling_int.get('is_active', False) and
                       bling_int.get('module_id') == 'bling')
            mp_ok = (mp_int and mp_int.get('is_active', False) and
                    mp_int.get('module_id') != 'bling')

            # Verificar se é placeholder
            is_placeholder = ((bling_int and bling_int.get('is_placeholder')) or
                            (mp_int and mp_int.get('is_placeholder')))

            # Verificar se há integração órfã (ID não existe)
            bling_orfao = bling_int_id and not bling_int
            mp_orfao = mp_int_id and not mp_int

            info = {
                'vinculo_id': vinculo['id'],
                'canal_venda_id': vinculo['canal_venda_id'],
                'canal_nome': vinculo.get('canal_nome'),
                'canal_slug': vinculo.get('canal_slug'),
                'bling_loja_id': vinculo['bling_loja_id'],
                'plataforma': vinculo.get('plataforma_nome'),
                'bling_integration_id': bling_int_id,
                'marketplace_integration_id': mp_int_id,
            }

            if bling_orfao or mp_orfao:
                info['problema'] = {
                    'bling_orfao': bling_orfao,
                    'marketplace_orfao': mp_orfao,
                }
                info['integrations_missing'] = {
                    'bling': bling_int_id if bling_orfao else None,
                    'marketplace': mp_int_id if mp_orfao else None,
                }
                resultados['orfaos'].append(info)
            elif is_placeholder:
                info['placeholder_info'] = {
                    'bling': bling_int.get('instance_name') if bling_int else None,
                    'marketplace': mp_int.get('instance_name') if mp_int else None,
                }
                resultados['placeholders'].append(info)
            elif bling_ok and mp_ok:
                info['integrations'] = {
                    'bling': bling_int.get('instance_name'),
                    'marketplace': mp_int.get('instance_name'),
                }
                resultados['completos'].append(info)
            else:
                info['incompleto_info'] = {
                    'bling_ok': bling_ok,
                    'marketplace_ok': mp_ok,
                    'bling_instance': bling_int.get('instance_name') if bling_int else None,
                    'marketplace_instance': mp_int.get('instance_name') if mp_int else None,
                    'bling_is_placeholder': bling_int.get('is_placeholder') if bling_int else False,
                    'marketplace_is_placeholder': mp_int.get('is_placeholder') if mp_int else False,
                }
                resultados['incompletos'].append(info)

        return resultados

    def get_vinculos_por_plataforma_com_status(self) -> List[Dict[str, Any]]:
        """
        Retorna plataformas agrupadas com status de cada vínculo.

        Returns:
            Lista de plataformas com seus vínculos e status detalhado
        """
        analise = self.analisar_vinculos_com_status()

        # Agrupar todos os vínculos por plataforma
        todas_plataformas = {}

        for categoria in ['completos', 'incompletos', 'orfaos', 'placeholders']:
            for vinculo in analise[categoria]:
                plataforma = vinculo.get('plataforma', 'unknown')

                if plataforma not in todas_plataformas:
                    todas_plataformas[plataforma] = {
                        'nome': plataforma,
                        'vinculos': [],
                        'total_vinculos': 0,
                        'vinculos_completos': 0,
                        'vinculos_incompletos': 0,
                        'vinculos_orfaos': 0,
                        'vinculos_placeholders': 0,
                    }

                vinculo_com_status = {
                    **vinculo,
                    'status_categoria': categoria,
                }
                todas_plataformas[plataforma]['vinculos'].append(vinculo_com_status)
                todas_plataformas[plataforma]['total_vinculos'] += 1

                # Atualizar contadores
                todas_plataformas[plataforma][f'vinculos_{categoria}'] += 1

        # Adicionar indicador de saúde da plataforma
        for plataforma in todas_plataformas.values():
            total = plataforma['total_vinculos']
            completos = plataforma['vinculos_completos']
            plataforma['saude'] = 'saudavel' if completos == total else 'atencao' if completos > 0 else 'critico'

        return list(todas_plataformas.values())

    def clear_cache(self):
        """Limpa o cache em memória."""
        self._cache.clear()


# Instância global
integracao_canal_service = IntegracaoCanalService()
