import logging
import json
import unicodedata
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from nistiprint_shared.services.platform_api_service import platform_api_service
from nistiprint_shared.services.order_service import order_service
from nistiprint_shared.services.integracao_canal_service import integracao_canal_service
from nistiprint_shared.database.supabase_db_service import supabase_db

logger = logging.getLogger("OrderSyncService")

def normalize_text(text: str) -> str:
    """Remove acentos e converte para maiúsculas para facilitar comparação."""
    if not text:
        return ""
    text = str(text)
    nfkd_form = unicodedata.normalize('NFKD', text)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)]).upper().strip()

def clean_date(date_str: Any) -> Optional[str]:
    """Valida e limpa strings de data para evitar erros no Postgres (ex: '0000-00-00')."""
    if not date_str or not isinstance(date_str, str):
        return None
    if date_str.startswith('0000') or '0000-00-00' in date_str:
        return None
    return date_str

def safe_float(value: Any, default: float = 0.0) -> float:
    """Converte valores de forma segura, tratando se vierem como dicionários da API."""
    if value is None: return default
    if isinstance(value, (int, float)): return float(value)
    if isinstance(value, dict):
        # Tenta pegar campos comuns de valor em objetos (Bling v3 style)
        for k in ['valor', 'total', 'quantidade']:
            if k in value: return safe_float(value[k], default)
        return default
    try:
        return float(str(value).replace(',', '.'))
    except:
        return default

class OrderSyncService:
    """
    Serviço centralizado para sincronizar e normalizar pedidos.
    Garante que dados relacionais (nome, telefone, flex, canal) sejam persistidos em colunas próprias.
    """

    def _get_canal_id_by_loja_id(self, loja_id: int) -> Optional[int]:
        """
        Mapeia o loja_id do Bling para o ID do canal_venda interno.
        Usa o novo serviço de configuração de vínculos.
        """
        if not loja_id:
            return None
        
        try:
            # Usar o novo serviço de configuração dinâmica
            config = integracao_canal_service.get_canal_by_bling_loja_id(loja_id)
            if config:
                return config['canal_venda_id']
            
            # Fallback: buscar na tabela canais_venda (legado)
            res = supabase_db.table('canais_venda').select('id').eq('conta_bling_id', str(loja_id)).execute()
            if res.data:
                return res.data[0]['id']
        except Exception as e:
            logger.warning(f"Erro ao resolver canal para loja_id {loja_id}: {e}")
        
        return None

    def sync_shopee_order(self, order_sn: str, instance_id: Optional[str] = None) -> Dict[str, Any]:
        """
        FASE 2: Enriquece pedido com dados da API Shopee.

        Este método:
        - É OPCIONAL: Dados do Bling já foram persistidos na FASE 1
        - É INDEPENDENTE: Pode ser chamado em outros pontos do sistema
        - Adiciona dados específicos da Shopee que o Bling não fornece

        Args:
            order_sn: Número do pedido (numeroLoja no Bling)
            instance_id: ID da instância de integração Shopee

        Returns:
            Dict com resultado do enriquecimento
        """
        try:
            logger.info("[FASE 2] Enriquecendo pedido Shopee: %s", order_sn)
            shopee_data = platform_api_service.get_order_detail([order_sn], instance_id, "shopee")

            if "error" in shopee_data and shopee_data["error"]:
                logger.error(f"Erro Shopee {order_sn}: {shopee_data['error']}")
                return shopee_data

            raw_order = shopee_data.get("raw", {})
            recipient = raw_order.get('recipient_address', {})

            # Extração Relacional
            cliente_nome = recipient.get('name') or raw_order.get('buyer_username')
            cliente_telefone = recipient.get('phone')

            # Data real de envio (ship_by_date) - CRÍTICO para Shopee
            ship_by_date_raw = raw_order.get('ship_by_date')
            data_prevista = datetime.fromtimestamp(ship_by_date_raw, tz=timezone.utc).isoformat() if ship_by_date_raw else None
            data_prevista = clean_date(data_prevista)

            # Identificação FLEX (Entrega Rápida)
            # Shopee o termo: "Entrega Rápida"
            shipping_carrier = raw_order.get('shipping_carrier', '')
            norm_carrier = normalize_text(shipping_carrier)

            # Verifica múltiplos indicadores de entrega rápida
            is_flex = any(termo in norm_carrier for termo in [
                "ENTREGA RÁPIDA",    # Termo principal em português
            ])

            # Log para depuração
            if is_flex:
                logger.info("🚀 Pedido FLEX detectado: %s (carrier: %s)", order_sn, shipping_carrier)

            # Upsert
            # Para pedidos Shopee puros (sem Bling), usar order_sn como numero_pedido e codigo_pedido_externo
            # Se já existir vínculo Bling, o numero_pedido já estará correto (vindo do Bling)
            # Dados do cliente NÃO são enviados pois o Bling é a fonte prioritária
            order_core_dto = {
                'numero_pedido': order_sn,  # Será sobrescrito se existir Bling
                'codigo_pedido_externo': order_sn,
                'origem': 'SHOPEE',
                'is_flex': is_flex,
                'data_limite_envio': data_prevista,
                'servico_logistico': shipping_carrier,  # shipping_carrier vai em servico_logistico, NÃO em informacoes_cliente
                'data_venda': clean_date(shopee_data.get('date_created')),
                'total_pedido': safe_float(shopee_data.get('total')),
                'situacao_pedido_id': self._map_shopee_status(shopee_data.get('status_original')),
                'status_original': shopee_data.get('status_original'),
                'informacoes_cliente': {
                    'buyer_username': raw_order.get('buyer_username'),
                    'full_address': recipient.get('full_address')
                    # shipping_carrier NÃO vai mais em informacoes_cliente - é dado logístico, não do cliente
                }
            }

            # Itens
            items_dto = []
            for item in raw_order.get('item_list', []):
                items_dto.append({
                    'sku_externo': item.get('item_sku') or item.get('model_sku'),
                    'descricao': item.get('item_name'),
                    'quantidade': item.get('model_quantity_purchased', 1),
                    'preco_unitario': item.get('model_original_price', 0),
                    'subtotal': float(item.get('model_original_price', 0)) * float(item.get('model_quantity_purchased', 1))
                })

            # Upsert
            # Resolver channel_id dinamicamente baseado na configuração
            # Fallback para ID 1 (Shopee) se não houver configuração
            channel_id = 1  # Default Shopee
            config = integracao_canal_service.get_canal_by_bling_loja_id(204047801)  # Shopee antiga como referência
            if config:
                channel_id = config['canal_venda_id']
            
            result = order_service.upsert_order(
                order_data=order_core_dto,
                platform='SHOPEE',
                platform_order_id=order_sn,
                raw_payload=raw_order,
                items=items_dto,
                channel_id=channel_id
            )
            
            # Legacy Sync
            self._save_to_shopee_table(order_sn, raw_order, data_prevista)
            
            logger.info("[FASE 2] ✓ Enriquecimento Shopee concluído para %s", order_sn)
            return result
        except Exception as e:
            logger.error("[FASE 2] ✗ Erro sync_shopee_order: %s", e)
            return {"error": str(e)}

    def sync_bling_order(self, bling_order_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        FASE 1: Sincroniza pedido vindo do Bling (Webhook ou Importação).
        
        Este método:
        - Processa pedidos de TODAS as plataformas (Shopee, Amazon, MercadoLivre, Shein, etc.)
        - É a fonte primária de dados para todos os pedidos
        - Deve ser executado ANTES de qualquer enriquecimento com marketplace
        
        Args:
            bling_order_data: Dados completos do pedido no Bling
            
        Returns:
            Dict com resultado da sincronização (id, external_id, status)
        """
        try:
            bling_id = str(bling_order_data.get('id'))
            order_sn = bling_order_data.get('numeroLoja')
            bling_numero = str(bling_order_data.get('numero'))
            external_id = order_sn if order_sn else f"BLING-{bling_numero}"
            
            loja_id = bling_order_data.get('loja', {}).get('id')
            logger.info(
                "[FASE 1] Sincronizando pedido Bling %s (numeroLoja=%s, loja_id=%s)",
                bling_id,
                order_sn or "N/A",
                loja_id or "N/A"
            )

            # Extração Relacional
            contato = bling_order_data.get('contato', {})
            transporte = bling_order_data.get('transporte', {})
            volumes = transporte.get('volumes', [])
            servico_logistico = volumes[0].get('servico', '') if volumes else ""

            norm_servico = normalize_text(servico_logistico)
            
            # Identificação FLEX (Entrega Rápida) - Bling
            # Bling pode receber vários termos da Shopee e outros marketplaces
            is_flex = any(termo in norm_servico for termo in [
                "ENTREGA RAPIDA","ENTREGA RÁPIDA",    # Termo principal em português
                "SPX EXPRESS",       # Shopee SPX Express
                "SPX_FLEX",          # Variação SPX Flex
                "FLEX",              # Termo genérico
                "LOGGI",             # Loggi (usado para entrega rápida em alguns casos)
            ])
            
            # Log para depuração
            if is_flex:
                logger.info("🚀 Pedido FLEX detectado (Bling): %s (servico: %s)", bling_id, servico_logistico)

            canal_id = self._get_canal_id_by_loja_id(loja_id)
            
            logger.info(
                "[FASE 1] Pedido %s: canal_id=%s, is_flex=%s",
                bling_id,
                canal_id or "N/A",
                is_flex
            )
            
            order_core_dto = {
                'numero_pedido': bling_numero,
                'codigo_pedido_externo': external_id,
                'origem': 'MARKETPLACE' if order_sn else 'BLING',
                'cliente_nome': contato.get('nome'),
                'cliente_telefone': contato.get('telefone') or contato.get('celular'),
                'cliente_email': contato.get('email'),
                'is_flex': is_flex,
                'data_limite_envio': clean_date(bling_order_data.get('dataPrevista')),
                'servico_logistico': servico_logistico,
                'data_venda': clean_date(bling_order_data.get('data')),
                'total_pedido': safe_float(bling_order_data.get('total')),
                'situacao_pedido_id': self._map_bling_status(bling_order_data.get('situacao', {}).get('id')),
                'status_original': str(bling_order_data.get('situacao', {}).get('id')),
                'informacoes_cliente': {
                    'servico_logistico': servico_logistico,
                    'contato_id': contato.get('id'),
                    'numero_loja': order_sn,
                    'bling_loja_id': loja_id
                }
            }

            items_dto = []
            for item in bling_order_data.get('itens', []):
                items_dto.append({
                    'sku_externo': item.get('codigo'),
                    'descricao': item.get('descricao'),
                    'quantidade': safe_float(item.get('quantidade'), 1.0),
                    'preco_unitario': safe_float(item.get('valor')),
                    'subtotal': safe_float(item.get('valor')) * safe_float(item.get('quantidade'), 1.0)
                })

            result = order_service.upsert_order(
                order_data=order_core_dto,
                platform='BLING',
                platform_order_id=bling_id,
                raw_payload=bling_order_data,
                items=items_dto,
                channel_id=canal_id
            )
            
            logger.info(
                "[FASE 1] ✓ Pedido Bling %s sincronizado (external_id=%s, status=%s)",
                bling_id,
                external_id,
                result.get('status', 'unknown')
            )
            
            return result
        except Exception as e:
            logger.error("[FASE 1] ✗ Erro sync_bling_order: %s", e)
            return {"error": str(e)}

    def _save_to_shopee_table(self, order_sn: str, raw_order: dict, data_envio: str):
        try:
            payload = {
                'codigo_pedido': order_sn,
                'status_pedido': raw_order.get('order_status'),
                'valor_total': float(raw_order.get('total_amount', 0)),
                'data_criacao': datetime.fromtimestamp(raw_order.get('create_time'), tz=timezone.utc).isoformat() if raw_order.get('create_time') else None,
                'data_envio': data_envio,
                'endereco_entrega': raw_order.get('recipient_address'),
                'itens_pedido': raw_order.get('item_list'),
                'informacoes_comprador': {'username': raw_order.get('buyer_username')},
                'updated_at': datetime.utcnow().isoformat()
            }
            res = supabase_db.table('pedidos_shopee').select('id').eq('codigo_pedido', order_sn).execute()
            if res.data:
                supabase_db.table('pedidos_shopee').update(payload).eq('id', res.data[0]['id']).execute()
            else:
                payload['created_at'] = datetime.utcnow().isoformat()
                supabase_db.table('pedidos_shopee').insert(payload).execute()
        except: pass

    def _map_bling_status(self, id: int) -> int:
        """
        Mapeia status do Bling para status internos do sistema.
        
        Mapeamento:
        - Bling 6 (Em Aberto)     -> Interno 1 (Em Aberto/Pendente)
        - Bling 15 (Em Andamento) -> Interno 2 (Em Andamento/Produção)
        - Bling 9 (Atendido)      -> Interno 5 (Enviado)
        - Bling 12 (Cancelado)    -> Interno 7 (Cancelado)
        - Bling 18 (Arquivado)    -> Interno 5 (Enviado)
        
        Args:
            id: ID do status no Bling
            
        Returns:
            ID do status interno correspondente
        """
        mapeamento = {
            6: 1,   # Em Aberto -> Em Aberto
            15: 2,  # Em Andamento -> Pago/Em Andamento
            24: 4,  # Verificado -> Pronto para Envio (Produzido/Checkout)
            9: 5,   # Atendido -> Enviado
            12: 7,  # Cancelado -> Cancelado
            18: 5,  # Arquivado -> Enviado
        }
        return mapeamento.get(id, 1)  # Default: Em Aberto

    def _map_shopee_status(self, status: str) -> int:
        return {
            'UNPAID': 1, 'READY_TO_SHIP': 2, 'PROCESSED': 3,
            'SHIPPED': 5, 'COMPLETED': 6, 'IN_CANCEL': 7,
            'CANCELLED': 7, 'INVOICED': 5
        }.get(status, 1)

order_sync_service = OrderSyncService()
