"""
Serviço para identificação de pedidos personalizados.

Este serviço identifica se um pedido contém itens personalizados, usando os seguintes critérios:
1. Descrição do item contém "personaliza" (case-insensitive) - NÃO requer API call
2. Nome do produto contém "personaliza" (case-insensitive) - Requer API call se não cacheado
3. Produto tem campo customizado de personalização = true - Requer API call

Otimização:
- Verifica descrição primeiro (já vem no payload do pedido)
- Agrupa products IDs únicos para batch lookup
- Cache interno de produtos para reduzir chamadas à API do Bling
"""

from typing import Optional, Dict, Any, List
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.bling.bling_client import BlingClient
from nistiprint_shared.services.erp_marketplace_links_service import erp_marketplace_links_service
from datetime import datetime
import logging

logger = logging.getLogger("PersonalizedOrderIdentifier")


class PersonalizedOrderIdentifier:
    """Serviço para identificação de pedidos personalizados."""

    def __init__(self):
        self._product_cache: Dict[int, dict] = {}

    def process_order(self, order_data: dict) -> dict:
        """
        Fluxo completo de identificação de itens personalizados.

        Args:
            order_data: Dados completos do pedido do Bling

        Returns:
            {
                'success': bool,
                'personalized_items': [índices dos itens personalizados],
                'order_id': id_do_pedido,
                'error': 'mensagem de erro se falhar'
            }
        """
        try:
            # 1. Identificar loja Bling do pedido
            bling_loja_id = order_data.get('loja', {}).get('id')
            if not bling_loja_id:
                logger.warning("Pedido sem bling_loja_id: %s", order_data.get('id'))
                return {
                    'success': False,
                    'error': 'No bling_loja_id in order data'
                }

            # 2. Lookup rápido: loja → instância Bling (usa índice em channel_connections)
            bling_integration_id = self._lookup_bling_integration(str(bling_loja_id))
            if not bling_integration_id:
                logger.warning(
                    "Não encontrou bling_integration_id para loja %s",
                    bling_loja_id
                )
                return {
                    'success': False,
                    'error': f'Bling integration not found for loja {bling_loja_id}'
                }

            # 3. Buscar ID do campo customizado
            custom_field_id = erp_marketplace_links_service.get_custom_field_id(
                int(bling_integration_id)
            )

            # 4. Identificar itens personalizados
            personalized_indices = self._identify_personalized_items(
                order_data,
                custom_field_id
            )

            # 5. Marcar no banco se houver itens personalizados
            if personalized_indices:
                # Primeiro precisamos do ID do pedido no Supabase
                pedido_bling_id = self._get_pedido_bling_id(order_data)
                if pedido_bling_id:
                    self._mark_as_personalized(
                        pedido_bling_id,
                        order_data,
                        personalized_indices
                    )
                    logger.info(
                        "Pedido %s marcado como personalizado: %d itens",
                        order_data.get('numero'),
                        len(personalized_indices)
                    )
                else:
                    logger.warning(
                        "Não encontrou pedido_bling_id para %s",
                        order_data.get('numero')
                    )
            else:
                logger.debug(
                    "Pedido %s não possui itens personalizados",
                    order_data.get('numero')
                )

            return {
                'success': True,
                'personalized_items': personalized_indices,
                'order_id': order_data.get('id')
            }

        except Exception as e:
            logger.error(f"Erro ao processar pedido personalizado: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def _lookup_bling_integration(self, bling_loja_id: str) -> Optional[str]:
        """
        Lookup otimizado usando índice em channel_connections.

        Args:
            bling_loja_id: ID da loja no Bling

        Returns:
            bling_integration_id ou None
        """
        try:
            result = supabase_db.table('channel_connections') \
                .select('bling_integration_id') \
                .eq('aggregator_store_id', bling_loja_id) \
                .eq('is_active', True) \
                .execute()

            if result.data:
                return result.data[0]['bling_integration_id']

            return None

        except Exception as e:
            logger.error(f"Erro ao lookup bling_integration: {e}", exc_info=True)
            return None

    def _identify_personalized_items(
        self,
        order_data: dict,
        custom_field_id: int
    ) -> List[int]:
        """
        Identifica itens personalizados em um pedido.

        Critérios (por ordem de prioridade/eficiência):
        1. Descrição do item contém "personaliza" (já vem no payload, sem API call)
        2. Nome do produto contém "personaliza" (requer API call se não cacheado)
        3. Produto tem campo customizado = true (requer API call)

        Args:
            order_data: Dados do pedido do Bling
            custom_field_id: ID do campo customizado de personalização

        Returns:
            Lista de índices dos itens personalizados
        """
        items = order_data.get('itens', [])
        personalized_indices = []

        # Coletar product IDs únicos para batch lookup
        product_ids_to_check = set()
        item_product_map = {}  # índice → product_id

        for idx, item in enumerate(items):
            descricao = item.get('descricao', '').lower()
            produto = item.get('produto', {})
            nome_item = produto.get('nome', '').lower()

            # Critério 1: Descrição do item (já vem no payload do pedido) - MAIS RÁPIDO
            if 'personaliza' in descricao or 'personaliza' in nome_item:
                personalized_indices.append(idx)
                logger.debug(
                    "Item %d marcado como personalizado por descrição: %s",
                    idx,
                    descricao[:50] if len(descricao) > 50 else descricao
                )
                continue

            # Se não tem produto vinculado, não é personalizável via campo customizado
            product_id = produto.get('id')
            if product_id:
                product_ids_to_check.add(product_id)
                item_product_map[idx] = product_id

        # Critério 2 e 3: Batch lookup de produtos (otimização de API calls)
        if product_ids_to_check:
            personalized_products = self._identify_personalized_products_batch(
                list(product_ids_to_check),
                custom_field_id
            )

            # Verificar quais itens têm produtos personalizados
            for idx, product_id in item_product_map.items():
                if personalized_products.get(product_id, False):
                    personalized_indices.append(idx)
                    logger.debug(
                        "Item %d marcado como personalizado por produto (id=%d)",
                        idx,
                        product_id
                    )

        return personalized_indices

    def _identify_personalized_products_batch(
        self,
        product_ids: List[int],
        custom_field_id: int
    ) -> Dict[int, bool]:
        """
        Verifica múltiplos produtos de uma vez.

        Args:
            product_ids: Lista de IDs de produtos
            custom_field_id: ID do campo customizado

        Returns:
            Dicionário {product_id: is_personalized}
        """
        results = {}

        # Obter BlingClient para a conta correta
        # Nota: Precisamos criar um client genérico aqui
        # Em produção, isso deve ser injetado ou obtido via factory
        try:
            bling_client = BlingClient.create_client_for_platform(
                'shopee',  # Fallback - idealmente deveria vir do contexto
                function_name='ORDER_IMPORT'
            )
        except Exception as e:
            logger.error(f"Erro ao criar BlingClient: {e}")
            # Retorna tudo como False se não conseguir criar client
            return {pid: False for pid in product_ids}

        for product_id in product_ids:
            # Verificar cache primeiro
            if product_id in self._product_cache:
                product = self._product_cache[product_id]
            else:
                # Buscar produto (com throttle interno)
                product = bling_client.get_product(product_id)
                if product:
                    self._product_cache[product_id] = product

            if not product:
                results[product_id] = False
                continue

            # Critério 2: Nome do produto (rápido, já temos os dados)
            if 'personaliza' in product.get('nome', '').lower():
                results[product_id] = True
                continue

            # Critério 3: Campo customizado (requer parsing)
            is_personalized = False
            for campo in product.get('camposCustomizados', []):
                if (campo.get('idCampoCustomizado') == custom_field_id and
                    str(campo.get('valor', '')).lower() == 'true'):
                    is_personalized = True
                    break

            results[product_id] = is_personalized

        return results

    def _get_pedido_bling_id(self, order_data: dict) -> Optional[int]:
        """
        Obtém ID do pedido no Supabase (pedidos_bling).

        Args:
            order_data: Dados do pedido

        Returns:
            ID do pedido em pedidos_bling ou None
        """
        try:
            # Tentar por bling_id primeiro
            bling_id = order_data.get('id')
            if bling_id:
                result = supabase_db.table('pedidos_bling') \
                    .select('id') \
                    .eq('bling_id', str(bling_id)) \
                    .execute()

                if result.data:
                    return result.data[0]['id']

            # Fallback: tentar por numero_loja
            numero_loja = order_data.get('numeroLoja')
            if numero_loja:
                result = supabase_db.table('pedidos_bling') \
                    .select('id') \
                    .eq('numero_loja', str(numero_loja)) \
                    .execute()

                if result.data:
                    return result.data[0]['id']

            return None

        except Exception as e:
            logger.error(f"Erro ao buscar pedido_bling_id: {e}", exc_info=True)
            return None

    def _mark_as_personalized(
        self,
        pedido_bling_id: int,
        order_data: dict,
        personalized_indices: List[int]
    ):
        """
        Marca pedido e itens como personalizados no Supabase.
        Marca tanto nas tabelas legado (pedidos_bling, itens_pedido_bling)
        quanto nas tabelas unificadas (pedidos, itens_pedido).
        Também marca produtos internos como personalizados se vinculados.

        Args:
            pedido_bling_id: ID do pedido em pedidos_bling
            order_data: Dados do pedido do Bling
            personalized_indices: Índices dos itens personalizados
        """
        try:
            # 1. Marcar pedido legado como personalizado
            supabase_db.table('pedidos_bling').update({
                'personalizado': True,
                'updated_at': datetime.utcnow().isoformat()
            }).eq('id', pedido_bling_id).execute()

            # 1.1 Marcar pedido unificado como personalizado
            self._mark_unified_pedido_as_personalized(order_data)

            # 2. Marcar itens legado e unificado como personalizados
            items = order_data.get('itens', [])

            for idx in personalized_indices:
                if idx < len(items):
                    item = items[idx]
                    bling_item_id = item.get('id')
                    produto_bling_id = item.get('produto', {}).get('id')
                    item_descricao = item.get('descricao', '')

                    if bling_item_id:
                        # 2a. Atualizar item legado por bling_item_id
                        supabase_db.table('itens_pedido_bling').update({
                            'personalizado': True,
                            'updated_at': datetime.utcnow().isoformat()
                        }).eq('bling_item_id', str(bling_item_id)).execute()

                    # 2b. Atualizar item unificado por pedido + descricao
                    self._mark_unified_item_as_personalized(order_data, item_descricao)

                    # 3. NOVO: Marcar produto interno como personalizado
                    if produto_bling_id:
                        self._mark_internal_product_as_personalized(produto_bling_id)

            logger.info(
                "Pedido %d e %d itens marcados como personalizados",
                pedido_bling_id,
                len(personalized_indices)
            )

        except Exception as e:
            logger.error(f"Erro ao marcar como personalizado: {e}", exc_info=True)

    def _mark_unified_pedido_as_personalized(self, order_data: dict):
        """
        Marca pedido unificado (tabela 'pedidos') como personalizado.

        Busca por codigo_pedido_externo (numeroLoja) ou numero_pedido.
        """
        try:
            numero_loja = order_data.get('numeroLoja')
            numero_pedido = order_data.get('numero')

            if numero_loja:
                result = supabase_db.table('pedidos') \
                    .select('id') \
                    .eq('codigo_pedido_externo', str(numero_loja)) \
                    .execute()
                if result.data:
                    supabase_db.table('pedidos').update({
                        'personalizado': True,
                        'updated_at': datetime.utcnow().isoformat()
                    }).eq('id', result.data[0]['id']).execute()
                    logger.debug(
                        "Pedido unificado %d marcado como personalizado (via numeroLoja=%s)",
                        result.data[0]['id'], numero_loja
                    )
                    return

            if numero_pedido:
                result = supabase_db.table('pedidos') \
                    .select('id') \
                    .eq('numero_pedido', str(numero_pedido)) \
                    .execute()
                if result.data:
                    supabase_db.table('pedidos').update({
                        'personalizado': True,
                        'updated_at': datetime.utcnow().isoformat()
                    }).eq('id', result.data[0]['id']).execute()
                    logger.debug(
                        "Pedido unificado %d marcado como personalizado (via numero=%s)",
                        result.data[0]['id'], numero_pedido
                    )
                    return

            logger.warning(
                "Não encontrou pedido unificado para marcar como personalizado: numeroLoja=%s, numero=%s",
                numero_loja, numero_pedido
            )

        except Exception as e:
            logger.error(f"Erro ao marcar pedido unificado como personalizado: {e}", exc_info=True)

    def _mark_unified_item_as_personalized(self, order_data: dict, item_descricao: str):
        """
        Marca item unificado (tabela 'itens_pedido') como personalizado.

        Busca por pedido_id + descricao.
        """
        try:
            numero_loja = order_data.get('numeroLoja')
            if not numero_loja or not item_descricao:
                return

            # Primeiro, encontrar o pedido unificado
            pedido_result = supabase_db.table('pedidos') \
                .select('id') \
                .eq('codigo_pedido_externo', str(numero_loja)) \
                .execute()

            if not pedido_result.data:
                logger.debug(
                    "Não encontrou pedido unificado para marcar item personalizado (numeroLoja=%s)",
                    numero_loja
                )
                return

            pedido_id = pedido_result.data[0]['id']

            # Marcar itens por pedido_id + descricao
            supabase_db.table('itens_pedido').update({
                'personalizado': True,
                'updated_at': datetime.utcnow().isoformat()
            }).eq('pedido_id', pedido_id).eq('descricao', item_descricao).execute()

            logger.debug(
                "Item unificado marcado como personalizado (pedido_id=%d, descricao=%s)",
                pedido_id, item_descricao[:50]
            )

        except Exception as e:
            logger.error(f"Erro ao marcar item unificado como personalizado: {e}", exc_info=True)

    def _mark_internal_product_as_personalized(self, bling_product_id: int):
        """
        Marca produto interno como personalizado se vinculado ao produto Bling.

        Fluxo:
        1. Buscar vínculo Bling → produto interno via vinculos_bling
        2. Se encontrado, update produtos.personalizado = true
        3. Se não encontrado, log para revisão manual
        """
        try:
            from nistiprint_shared.database.supabase_db_service import supabase_db

            # Buscar produto interno vinculado
            result = supabase_db.table('vinculos_bling') \
                .select('produto_id') \
                .eq('codigo_bling', str(bling_product_id)) \
                .limit(1) \
                .execute()

            if result.data:
                internal_product_id = result.data[0]['produto_id']

                # Verificar se já está marcado
                product_check = supabase_db.table('produtos') \
                    .select('id, personalizado') \
                    .eq('id', internal_product_id) \
                    .limit(1) \
                    .execute()

                if product_check.data and not product_check.data[0].get('personalizado'):
                    supabase_db.table('produtos').update({
                        'personalizado': True,
                        'updated_at': datetime.utcnow().isoformat()
                    }).eq('id', internal_product_id).execute()

                    logger.info(
                        "Produto interno %d marcado como personalizado (Bling ID: %d)",
                        internal_product_id, bling_product_id
                    )
                elif product_check.data:
                    logger.debug(
                        "Produto interno %d já está marcado como personalizado",
                        internal_product_id
                    )
            else:
                logger.warning(
                    "Produto Bling %d não vinculado a produto interno — revisar cadastro",
                    bling_product_id
                )
        except Exception as e:
            logger.error(f"Erro ao marcar produto interno como personalizado (Bling {bling_product_id}): {e}")

    def clear_cache(self):
        """Limpa cache de produtos."""
        self._product_cache = {}


# Global instance
personalized_order_identifier = PersonalizedOrderIdentifier()
