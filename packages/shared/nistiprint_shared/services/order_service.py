from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.mappers.order_mappers import BlingMapper, ShopeeMapper
import logging

class OrderService:
    """
    Serviço unificado para gestão de pedidos.
    Implementa a arquitetura Core Order + Integration Links (V3) + Canonical Payload & Events.
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
                     channel_id: Optional[int] = None, integration_id: Optional[str] = None) -> Dict[str, Any]:
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
            # 1. Tentar encontrar o pedido Core existente
            existing_order = self.pedidos_table.select("id, situacao_pedido_id, is_flex, servico_logistico").eq('codigo_pedido_externo', external_id).execute()
            
            core_id = None
            old_status = None
            if existing_order.data:
                core_id = existing_order.data[0]['id']
                old_status = existing_order.data[0]['situacao_pedido_id']

                # Atualiza dados operacionais básicos
                # IMPORTANTE: numero_pedido e codigo_pedido_externo devem ser atualizados se vierem do Bling
                update_core = {
                    'situacao_pedido_id': order_data.get('situacao_pedido_id'),
                    'total_pedido': order_data.get('total_pedido'),
                    'canal_venda_id': channel_id,
                    'cliente_nome': order_data.get('cliente_nome'),
                    'cliente_telefone': order_data.get('cliente_telefone'),
                    'cliente_email': order_data.get('cliente_email'),
                    'is_flex': order_data.get('is_flex'),
                    'data_limite_envio': order_data.get('data_limite_envio'),
                    'servico_logistico': order_data.get('servico_logistico'),
                    'payload_canonico': canonical_payload,
                    'updated_at': datetime.now(timezone.utc).isoformat()
                }

                # Atualizar numero_pedido e codigo_pedido_externo apenas se vierem do Bling (prioridade)
                if platform.upper() == 'BLING':
                    if order_data.get('numero_pedido'):
                        update_core['numero_pedido'] = order_data.get('numero_pedido')
                    if order_data.get('codigo_pedido_externo'):
                        update_core['codigo_pedido_externo'] = order_data.get('codigo_pedido_externo')
                    # Cliente: se vier do Bling, sempre atualizar (é a fonte mais confiável)
                    if order_data.get('cliente_nome'):
                        update_core['cliente_nome'] = order_data.get('cliente_nome')
                    if order_data.get('cliente_telefone'):
                        update_core['cliente_telefone'] = order_data.get('cliente_telefone')
                    if order_data.get('cliente_email'):
                        update_core['cliente_email'] = order_data.get('cliente_email')
                # Shopee/Outros: NÃO atualizar numero_pedido, codigo_pedido_externo ou dados do cliente
                # para não sobrescrever dados do Bling. Apenas atualiza dados enriquecidos:
                # - is_flex, data_limite_envio, servico_logistico, informacoes_cliente
                if platform.upper() != 'BLING':
                    # Dados enriquecidos da Shopee (sempre atualizar se vierem)
                    if order_data.get('is_flex') is not None:
                        # PROTEÇÃO: Se já for Flex, não permitir voltar para False via planilha
                        # a menos que o status atual permita essa mudança (ex: raras correções)
                        # No momento, vamos ser conservadores: uma vez Flex, sempre Flex.
                        current_is_flex = existing_order.data[0].get('is_flex', False)
                        if current_is_flex and order_data.get('is_flex') is False:
                            logging.info(f"Ignorando atualização de is_flex para FALSE no pedido {core_id} (já é TRUE)")
                            if 'is_flex' in update_core:
                                del update_core['is_flex']
                        else:
                            update_core['is_flex'] = order_data.get('is_flex')

                    if order_data.get('data_limite_envio'):
                        update_core['data_limite_envio'] = order_data.get('data_limite_envio')
                    
                    if order_data.get('servico_logistico'):
                        # PROTEÇÃO similar para servico_logistico
                        current_servico = existing_order.data[0].get('servico_logistico', '')
                        new_servico = order_data.get('servico_logistico', '')
                        
                        # Se o atual é Entrega Rápida e o novo não é, ignore
                        if 'ENTREGA RÁPIDA' in str(current_servico).upper() and 'ENTREGA RÁPIDA' not in str(new_servico).upper():
                             logging.info(f"Ignorando atualização de servico_logistico no pedido {core_id} para preservar Flex")
                             if 'servico_logistico' in update_core:
                                 del update_core['servico_logistico']
                        else:
                            update_core['servico_logistico'] = order_data.get('servico_logistico')
                    
                    # CRÍTICO: Atualizar informacoes_cliente com shipping_carrier e outros dados da Shopee
                    # Isso garante que o trigger SQL possa calcular is_flex automaticamente
                    if order_data.get('informacoes_cliente'):
                        # Mesclar com dados existentes para não perder informações
                        existing = self.pedidos_table.select('informacoes_cliente').eq('id', core_id).single().execute()
                        if existing.data:
                            info_existente = existing.data.get('informacoes_cliente', {}) or {}
                            if isinstance(info_existente, dict):
                                # Mesclar: dados novos sobrescrevem existentes
                                info_existente.update(order_data.get('informacoes_cliente'))
                                update_core['informacoes_cliente'] = info_existente
                            else:
                                update_core['informacoes_cliente'] = order_data.get('informacoes_cliente')
                        else:
                            update_core['informacoes_cliente'] = order_data.get('informacoes_cliente')
                
                update_core = {k: v for k, v in update_core.items() if v is not None}
                self.pedidos_table.update(update_core).eq('id', core_id).execute()
            else:
                # Criar novo pedido Core
                new_core = {
                    'numero_pedido': order_data.get('numero_pedido') or external_id,
                    'codigo_pedido_externo': external_id,
                    'origem': order_data.get('origem') or platform,
                    'cliente_nome': order_data.get('cliente_nome'),
                    'cliente_documento': order_data.get('cliente_documento'),
                    'cliente_telefone': order_data.get('cliente_telefone'),
                    'cliente_email': order_data.get('cliente_email'),
                    'is_flex': order_data.get('is_flex', False),
                    'data_limite_envio': order_data.get('data_limite_envio'),
                    'servico_logistico': order_data.get('servico_logistico'),
                    'data_venda': order_data.get('data_venda') or datetime.now(timezone.utc).isoformat(),
                    'situacao_pedido_id': order_data.get('situacao_pedido_id'),
                    'total_pedido': order_data.get('total_pedido', 0),
                    'informacoes_cliente': order_data.get('informacoes_cliente', {}),
                    'payload_canonico': canonical_payload,
                    'canal_venda_id': channel_id,
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'updated_at': datetime.now(timezone.utc).isoformat()
                }
                res = self.pedidos_table.insert(new_core).execute()
                if not res.data:
                    raise Exception(f"Falha ao criar pedido core {external_id}")
                core_id = res.data[0]['id']
                
                # Registrar Evento de Criação
                self.register_event(core_id, 'ORDER_CREATED', f"Pedido criado via {platform}", raw_payload)

            # 2. Registrar Mudança de Status na Timeline
            new_status = order_data.get('situacao_pedido_id')
            if old_status and new_status and old_status != new_status:
                self.register_event(
                    core_id, 
                    'STATUS_CHANGED', 
                    f"Status alterado de {old_status} para {new_status}",
                    raw_payload,
                    status_de=str(old_status),
                    status_para=str(new_status)
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

            # 4. Processar Itens
            if items:
                existing_items = self.itens_table.select("id", count='exact').eq('pedido_id', core_id).execute()
                if existing_items.count == 0:
                    has_personalized_item = False
                    for item in items:
                        descricao = item.get('descricao', '').lower()
                        # Verificar se o item é personalizado pela descrição
                        is_personalizado = 'personaliza' in descricao
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
                       status_de: str = None, status_para: str = None):
        """Registra um evento na timeline do pedido."""
        try:
            event = {
                'pedido_id': pedido_id,
                'tipo_evento': tipo,
                'descricao': descricao,
                'status_de': status_de,
                'status_para': status_para,
                'payload_origem': payload,
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

