from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.mappers.order_mappers import BlingMapper, ShopeeMapper
from nistiprint_shared.services.personalized_classification_service import (
    item_indicates_personalized,
)
from nistiprint_shared.services.canonical_order_repository import (
    CanonicalOrderIdentityError,
    canonical_order_repository,
)
import logging

class OrderService:
    """
    Serviço unificado para gestão de pedidos.
    Implementa a arquitetura Core Order + Integration Links (V3) + Canonical Payload & Events.

    NOTA: Enriquecimento de marketplace (Shopee) agora é feito no pipeline
    unificado de ingest (bling_order_processing_service). Este serviço
    legado mantém apenas compatibilidade para callers existentes.
    """

    def __init__(self):
        self.pedidos_table = supabase_db.table('pedidos')
        self.itens_table = supabase_db.table('itens_pedido')
        self.vinculos_table = supabase_db.table('vinculos_integracao_pedido')
        self.eventos_table = supabase_db.table('eventos_pedido')

    def _get_mapper(self, platform: str):
        if platform.upper() == 'BLING': return BlingMapper
        if platform.upper() == 'SHOPEE': return ShopeeMapper
        return None

    def upsert_order(self, order_data: Dict[str, Any], platform: str, platform_order_id: str,
                     raw_payload: Dict[str, Any], items: List[Dict[str, Any]] = None,
                     channel_id: Optional[int] = None, integration_id: Optional[str] = None,
                     correlation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Realiza o Upsert inteligente de um pedido.
        Garante a unicidade, normaliza os dados e registra na timeline.
        """
        external_id = order_data.get('codigo_pedido_externo')
        if not external_id:
            raise ValueError("codigo_pedido_externo é obrigatório para upsert.")

        # Gerar Payload Canônico se o Mapper existir
        mapper = self._get_mapper(platform)
        # Passar canal_venda_id para o mapper derivar modalidade logística
        canonical_payload = mapper.map(raw_payload, canal_venda_id=channel_id) if mapper else {}

        try:
            module_hint = order_data.get('marketplace_module_id') or order_data.get('origem')
            if str(module_hint or '').strip().lower() == 'bling':
                module_hint = None
            marketplace_module_id = canonical_order_repository.normalize_module_id(
                module_hint or (platform if platform.upper() != 'BLING' else None)
            )
            marketplace_order_id = canonical_order_repository.normalize_order_id(
                order_data.get('marketplace_order_id') or external_id or platform_order_id
            )
            if not marketplace_module_id or not marketplace_order_id:
                raise CanonicalOrderIdentityError(
                    'Legacy order upsert requires a resolved marketplace identity'
                )

            existing_order = (
                self.pedidos_table.select('id,situacao_pedido_id')
                .eq('marketplace_module_id', marketplace_module_id)
                .eq('marketplace_order_id', marketplace_order_id)
                .limit(1).execute()
            )
            old_status = (existing_order.data or [{}])[0].get('situacao_pedido_id')
            canonical_order = {
                **order_data,
                'marketplace_module_id': marketplace_module_id,
                'marketplace_order_id': marketplace_order_id,
                'marketplace_integration_id': integration_id if platform.upper() != 'BLING' else order_data.get('marketplace_integration_id'),
                'ingest_source': platform.lower(),
                'canal_venda_id': channel_id,
                'customer': order_data.get('informacoes_cliente') or {},
            }
            snapshot = {
                'identity': {
                    'ingest_source': platform.lower(),
                    'marketplace': marketplace_module_id,
                    'marketplace_order_id': marketplace_order_id,
                    'marketplace_integration_id': canonical_order.get('marketplace_integration_id'),
                },
                'customer': order_data.get('informacoes_cliente') or {
                    'name': order_data.get('cliente_nome'),
                    'document': order_data.get('cliente_documento'),
                    'phone': order_data.get('cliente_telefone'),
                    'email': order_data.get('cliente_email'),
                },
                'items': items or [],
                'logistics': {
                    'is_flex': order_data.get('is_flex'),
                    'is_fulfillment': order_data.get('is_fulfillment'),
                    'deadline': order_data.get('data_limite_envio'),
                    'service': order_data.get('servico_logistico'),
                },
                'financial': {
                    'total': order_data.get('total_pedido'),
                    'currency': order_data.get('moeda') or 'BRL',
                },
                'platform_fields': canonical_payload or {},
                'raw_refs': {platform.lower(): raw_payload},
                'source_history': [{
                    'source': platform.lower(),
                    'at': datetime.now(timezone.utc).isoformat(),
                    'correlation_id': correlation_id,
                }],
            }
            refs = [{
                'integration_id': integration_id,
                'module_id': marketplace_module_id,
                'role': 'sales_origin',
                'external_order_id': marketplace_order_id,
                'external_status': order_data.get('status_original'),
            }]
            if platform.upper() == 'BLING':
                refs.append({
                    'integration_id': integration_id,
                    'module_id': 'bling',
                    'role': 'erp',
                    'external_order_id': str(platform_order_id),
                })
            core_id = canonical_order_repository.upsert(
                canonical_order, snapshot=snapshot, refs=refs
            )
            if not existing_order.data:
                self.register_event(
                    core_id, 'ORDER_CREATED', f"Pedido criado via {platform}",
                    raw_payload, correlation_id=correlation_id
                )

            # 2. Registrar Mudança de Status na Timeline
            new_status = order_data.get('situacao_pedido_id')
            if old_status and new_status and old_status != new_status:
                self.register_event(
                    core_id,
                    'STATUS_CHANGED',
                    f"Status alterado de {old_status} para {new_status}",
                    raw_payload,
                    status_de=str(old_status),
                    status_para=str(new_status),
                    correlation_id=correlation_id
                )

            # 3. Upsert do Vínculo de Integração
            vinculo = {
                'pedido_id': core_id,
                'plataforma': platform,
                'id_na_plataforma': platform_order_id,
                'status_na_plataforma': order_data.get('status_original'),
                'integration_id': integration_id,
                'dados_brutos': raw_payload,
                'last_synced_at': datetime.now(timezone.utc).isoformat()
            }
            self.vinculos_table.upsert(vinculo, on_conflict='pedido_id,plataforma').execute()

            # NOTA: Enriquecimento de marketplace removido - agora feito no pipeline unificado
            # de ingest (bling_order_processing_service) para garantir dados consistentes.

            # 4. Processar Itens
            if items:
                existing_items = self.itens_table.select("id", count='exact').eq('pedido_id', core_id).execute()
                if existing_items.count == 0:
                    has_personalized_item = False
                    for item in items:
                        # Verificar se o item é personalizado pela descrição
                        is_personalizado = item_indicates_personalized(item)
                        if is_personalizado:
                            has_personalized_item = True

                        item_record = {
                            'pedido_id': core_id,
                            'produto_id': item.get('produto_id'),
                            'sku_externo': item.get('sku_externo'),
                            'descricao': item.get('descricao'),
                            'quantidade': item.get('quantidade', 1),
                            'preco_unitario': item.get('preco_unitario', 0),
                            'subtotal': item.get('subtotal') or (float(item.get('preco_unitario', 0)) * float(item.get('quantidade', 1))),
                            'personalizado': is_personalizado,
                            'created_at': datetime.now(timezone.utc).isoformat()
                        }
                        self.itens_table.insert(item_record).execute()

                    # Se algum item é personalizado, marcar o pedido como personalizado
                    if has_personalized_item:
                        self.pedidos_table.update({
                            'personalizado': True,
                            'updated_at': datetime.now(timezone.utc).isoformat()
                        }).eq('id', core_id).execute()

            return {"id": core_id, "external_id": external_id, "status": "success"}

        except Exception as e:
            logging.error(f"Erro no upsert_order: {str(e)}")
            raise e

    def register_event(self, pedido_id: int, tipo: str, descricao: str, payload: Dict = None,
                       status_de: str = None, status_para: str = None, correlation_id: str = None):
        """Registra um evento na timeline do pedido com correlation_id para rastreamento."""
        try:
            event = {
                'pedido_id': pedido_id,
                'tipo_evento': tipo,
                'descricao': descricao,
                'status_de': status_de,
                'status_para': status_para,
                'payload_origem': payload,
                'correlation_id': correlation_id,
                'created_at': datetime.now(timezone.utc).isoformat()
            }
            self.eventos_table.insert(event).execute()
        except Exception as e:
            logging.error(f"Erro ao registrar evento para pedido {pedido_id}: {e}")

    def get_order_details(self, order_id: int) -> Dict[str, Any]:
        """Retorna os detalhes completos de um pedido, incluindo itens, vínculos e timeline."""
        order = self.pedidos_table.select("*").eq('id', order_id).single().execute().data
        if not order:
            return None
            
        items = self.itens_table.select("*").eq('pedido_id', order_id).execute().data
        links = self.vinculos_table.select("*").eq('pedido_id', order_id).execute().data
        events = self.eventos_table.select("*").eq('pedido_id', order_id).order('created_at', desc=True).execute().data
        
        return {
            **order,
            "itens": items,
            "integracoes": links,
            "timeline": events
        }


    def list_orders(self, page: int = 1, per_page: int = 50, filters: Dict = None) -> Dict[str, Any]:
        """Lista pedidos com paginação e filtros avançados."""
        # Join com canais_venda, situacoes_pedido e vinculos_integracao_pedido para as pills
        # Além de incluir as novas colunas relacionais do cliente
        query = self.pedidos_table.select(
            "*, canal_venda:canais_venda(nome), situacao_pedido:situacoes_pedido(nome, cor_status), "
            "demandas:demandas_producao!pedido_id(id, status, descricao, demanda_id), "
            "integracoes:vinculos_integracao_pedido(plataforma, status_na_plataforma, id_na_plataforma)",
            count='exact'
        )

        if filters:
            if filters.get('origem'):
                query = query.eq('origem', filters['origem'].upper())
            if filters.get('status'):
                # Usar situacao_pedido_id para filtrar diretamente
                query = query.eq('situacao_pedido_id', filters['status'])
            if filters.get('canal_venda_id'):
                query = query.eq('canal_venda_id', filters['canal_venda_id'])
            if filters.get('searchTerm'):
                q = filters['searchTerm']
                query = query.or_(f"cliente_nome.ilike.%{q}%,codigo_pedido_externo.ilike.%{q}%,numero_pedido.ilike.%{q}%")
            if filters.get('startDate'):
                query = query.gte('data_venda', filters['startDate'])
            if filters.get('endDate'):
                query = query.lte('data_venda', filters['endDate'])
            
            # Filtro por pedidos Flex (Entrega Rápida)
            if filters.get('is_flex') is not None:
                is_flex = filters.get('is_flex')
                if isinstance(is_flex, str):
                    is_flex = is_flex.lower() in ('true', '1', 'yes')
                query = query.eq('is_flex', is_flex)

            # Filtro por pedidos Fulfillment
            if filters.get('is_fulfillment') is not None:
                is_fulfillment = filters.get('is_fulfillment')
                if isinstance(is_fulfillment, str):
                    is_fulfillment = is_fulfillment.lower() in ('true', '1', 'yes')
                query = query.eq('is_fulfillment', is_fulfillment)

            # Novos filtros para consolidação
            if filters.get('has_demanda') is not None:
                # Filtrar pedidos com ou sem demanda vinculada
                if filters.get('has_demanda'):
                    # Pedidos COM demanda
                    query = query.not_('demandas', 'is', None)
                else:
                    # Pedidos SEM demanda
                    query = query.or_(f"demandas.is.null,numero_pedido.not.in.()")
                    # Nota: Este filtro é complexo, pode precisar de ajuste
            
            # Filtro por período de entrega (data_limite_envio)
            if filters.get('deliveryStartDate'):
                query = query.gte('data_limite_envio', filters['deliveryStartDate'])
            if filters.get('deliveryEndDate'):
                query = query.lte('data_limite_envio', filters['deliveryEndDate'])
            
            # Filtro por plataformas (integrações)
            if filters.get('plataformas'):
                plataformas = filters['plataformas']
                if isinstance(plataformas, list) and len(plataformas) > 0:
                    # Filtrar pedidos que têm pelo menos uma das plataformas
                    plataforma_filters = [f"integracoes.plataforma.eq.{p}" for p in plataformas]
                    # Nota: Supabase não suporta OR complexo em joins, pode precisar de ajuste

        offset = (page - 1) * per_page
        res = query.range(offset, offset + per_page - 1).order('data_venda', desc=True).execute()

        # Formatar dados para garantir que o status tenha nome e cor
        orders_formatted = []
        for order in res.data:
            order_dict = dict(order)
            order_dict['data_compra_marketplace'] = order.get('data_compra_marketplace') or order.get('purchase_at') or order.get('dataCompraMarketplace')
            order_dict['data_pagamento_marketplace'] = order.get('data_pagamento_marketplace') or order.get('payment_at') or order.get('dataPagamentoMarketplace')
            order_dict['data_coleta'] = order.get('data_coleta') or order.get('collection_at') or order.get('dataColeta')
            order_dict['data_envio_marketplace'] = order.get('data_envio_marketplace') or order.get('marketplace_shipped_at') or order.get('dataEnvioMarketplace')
            
            # Garantir formato consistente do status
            situacao = order.get('situacao_pedido')
            if situacao:
                order_dict['status'] = {
                    'id': order.get('situacao_pedido_id'),
                    'nome': situacao.get('nome', 'Desconhecido'),
                    'cor': situacao.get('cor_status', '#9ca3af')
                }
            else:
                # Fallback: usar apenas o ID se não houver join
                order_dict['status'] = {
                    'id': order.get('situacao_pedido_id'),
                    'nome': 'Desconhecido',
                    'cor': '#9ca3af'
                }
            
            orders_formatted.append(order_dict)

        return {
            "orders": orders_formatted,
            "total": res.count,
            "page": page,
            "per_page": per_page
        }

    def get_order_status_options(self) -> List[Dict[str, Any]]:
        """Retorna as opções de status unificados disponíveis."""
        try:
            res = supabase_db.table('situacoes_pedido').select('id, nome, cor_status').order('id').execute()
            return res.data
        except Exception as e:
            logging.error(f"Erro ao obter opções de status de pedido: {e}")
            return []

order_service = OrderService()
