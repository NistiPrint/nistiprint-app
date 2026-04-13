from typing import Optional, Dict, Any, List
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.order_service import order_service
from nistiprint_shared.services.marketplace_enrichment_service import marketplace_enrichment_service
import logging

logger = logging.getLogger(__name__)

class OrderReprocessService:
    """
    Serviço para reprocessamento de pedidos pelo administrador.
    Permite buscar dados atualizados de todas as integrações.
    """

    def __init__(self):
        self.pedidos_table = supabase_db.table('pedidos')
        self.vinculos_table = supabase_db.table('vinculos_integracao_pedido')
        self.erp_links_table = supabase_db.table('erp_marketplace_links')

    def reprocess_order(self, pedido_id: int, integration_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Reprocessa um pedido específico, buscando dados atualizados de todas as integrações.
        
        Args:
            pedido_id: ID do pedido a ser reprocessado
            integration_id: (opcional) ID da integração específica para reprocessar
        
        Returns:
            Resultado do reprocessamento com status e detalhes
        """
        try:
            # Buscar pedido
            response = self.pedidos_table.select("*").eq('id', pedido_id).single().execute()
            
            if not response.data:
                return {"success": False, "error": "Pedido não encontrado", "pedido_id": pedido_id}
            
            pedido = response.data[0]
            codigo_pedido_externo = pedido.get('codigo_pedido_externo')
            
            if not codigo_pedido_externo:
                return {"success": False, "error": "Pedido não tem codigo_pedido_externo", "pedido_id": pedido_id}
            
            # Buscar vínculos de integração existentes
            vinculos_query = self.vinculos_table.select("*").eq('pedido_id', pedido_id)
            if integration_id:
                vinculos_query = vinculos_query.eq('integration_id', integration_id)
            
            vinculos_response = vinculos_query.execute()
            vinculos = vinculos_response.data if vinculos_response.data else []
            
            results = []
            errors = []
            
            # Re-enriquecer com dados do marketplace
            for vinculo in vinculos:
                plataforma = vinculo.get('plataforma')
                vinculo_integration_id = vinculo.get('integration_id')
                
                if not vinculo_integration_id:
                    continue
                
                # Se integration_id foi especificado, apenas processar essa integração
                if integration_id and vinculo_integration_id != integration_id:
                    continue
                
                # Para vínculos BLING, tentar enriquecer com marketplace
                if plataforma == 'BLING':
                    try:
                        # Extrair bling_loja_id do dados_brutos
                        raw_payload = vinculo.get('dados_brutos', {})
                        if isinstance(raw_payload, dict):
                            bling_loja_id = raw_payload.get('loja', {}).get('id')
                            
                            if bling_loja_id:
                                # Enriquecer com dados do marketplace
                                enriched = marketplace_enrichment_service.enrich_order_from_marketplace(
                                    pedido_id=pedido_id,
                                    codigo_pedido_externo=codigo_pedido_externo,
                                    erp_integration_id=int(vinculo_integration_id),
                                    erp_store_id=str(bling_loja_id)
                                )
                                
                                if enriched:
                                    results.append({
                                        "plataforma": plataforma,
                                        "integration_id": vinculo_integration_id,
                                        "action": "enriched",
                                        "status": "success"
                                    })
                                else:
                                    results.append({
                                        "plataforma": plataforma,
                                        "integration_id": vinculo_integration_id,
                                        "action": "enriched",
                                        "status": "no_marketplace_data"
                                    })
                    except Exception as e:
                        errors.append({
                            "plataforma": plataforma,
                            "integration_id": vinculo_integration_id,
                            "error": str(e)
                        })
                        logger.error(f"Erro ao enriquecer pedido {pedido_id} da integração {vinculo_integration_id}: {e}")
            
            # Registrar evento de reprocessamento
            order_service.register_event(
                pedido_id=pedido_id,
                tipo='ORDER_REPROCESSED',
                descricao=f"Pedido reprocessado pelo administrador",
                payload={"integration_id": integration_id, "results": results, "errors": errors}
            )
            
            return {
                "success": True,
                "pedido_id": pedido_id,
                "codigo_pedido_externo": codigo_pedido_externo,
                "results": results,
                "errors": errors,
                "total_processed": len(results)
            }
            
        except Exception as e:
            logger.error(f"Erro ao reprocessar pedido {pedido_id}: {e}")
            return {"success": False, "error": str(e), "pedido_id": pedido_id}

    def reprocess_batch(self, pedido_ids: List[int], integration_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Reprocessa um lote de pedidos.
        
        Args:
            pedido_ids: Lista de IDs dos pedidos a serem reprocessados
            integration_id: (opcional) ID da integração específica para reprocessar
        
        Returns:
            Resultado do reprocessamento em lote
        """
        results = []
        errors = []
        
        for pedido_id in pedido_ids:
            try:
                result = self.reprocess_order(pedido_id, integration_id)
                if result.get('success'):
                    results.append(result)
                else:
                    errors.append(result)
            except Exception as e:
                errors.append({
                    "pedido_id": pedido_id,
                    "error": str(e)
                })
                logger.error(f"Erro ao reprocessar pedido {pedido_id} em lote: {e}")
        
        return {
            "success": True,
            "total_requested": len(pedido_ids),
            "total_processed": len(results),
            "total_errors": len(errors),
            "results": results,
            "errors": errors
        }

    def reprocess_by_canal(self, canal_venda_id: int, date_range: Optional[Dict[str, str]] = None, 
                          integration_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Reprocessa pedidos de um canal de venda específico.
        
        Args:
            canal_venda_id: ID do canal de venda
            date_range: (opcional) Dicionário com 'start_date' e 'end_date' (formato ISO)
            integration_id: (opcional) ID da integração específica para reprocessar
        
        Returns:
            Resultado do reprocessamento por canal
        """
        try:
            query = self.pedidos_table.select("id").eq('canal_venda_id', canal_venda_id)
            
            if date_range:
                start_date = date_range.get('start_date')
                end_date = date_range.get('end_date')
                
                if start_date:
                    query = query.gte('data_venda', start_date)
                if end_date:
                    query = query.lte('data_venda', end_date)
            
            response = query.execute()
            pedido_ids = [p['id'] for p in response.data] if response.data else []
            
            if not pedido_ids:
                return {
                    "success": True,
                    "message": "Nenhum pedido encontrado para os critérios especificados",
                    "total_requested": 0,
                    "total_processed": 0,
                    "results": [],
                    "errors": []
                }
            
            # Limitar a 100 pedidos por vez para evitar timeout
            if len(pedido_ids) > 100:
                logger.warning(f"Limitando reprocessamento a 100 pedidos (encontrados {len(pedido_ids)})")
                pedido_ids = pedido_ids[:100]
            
            return self.reprocess_batch(pedido_ids, integration_id)
            
        except Exception as e:
            logger.error(f"Erro ao reprocessar pedidos do canal {canal_venda_id}: {e}")
            return {"success": False, "error": str(e), "canal_venda_id": canal_venda_id}

# Instância global
order_reprocess_service = OrderReprocessService()
