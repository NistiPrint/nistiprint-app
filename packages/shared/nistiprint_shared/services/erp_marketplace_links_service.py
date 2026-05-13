"""
Serviço para gerenciar vínculos entre instâncias ERP (ex: Bling) e Marketplaces.

Este serviço permite:
- Vincular uma instância Bling a múltiplas instâncias de Marketplace
- Associar cada marketplace a uma loja específica no Bling (loja_id)
- Configurar parâmetros específicos por vínculo (ex: id_campo_personalizado)

Arquitetura:
- erp_integration_id: Instância do ERP (ex: Bling - Conta 01)
- marketplace_integration_id: Instância do Marketplace (ex: Shopee - CNPJ X)
- erp_store_id: ID da loja no ERP (ex: bling_loja_id = 204047801)
"""

from typing import Optional, Dict, Any, List
from nistiprint_shared.database.supabase_db_service import supabase_db
from datetime import datetime
import logging

logger = logging.getLogger("ErpMarketplaceLinksService")


MARKETPLACE_MODULES = {
    "shopee": {"name": "Shopee", "color": "#EE4D2D"},
    "mercadolivre": {"name": "Mercado Livre", "color": "#FFF159"},
    "amazon": {"name": "Amazon FBA Classic", "color": "#FF9900"},
    "amazonfba_classic": {"name": "Amazon FBA Classic", "color": "#FF9900"},
    "amazon_fulfillment": {"name": "Amazon Fulfillment", "color": "#FF9900"},
    "shein": {"name": "Shein", "color": "#FF6B6B"},
    "tiktok": {"name": "TikTok Shop", "color": "#000000"},
    "tiktokshop": {"name": "TikTok Shop", "color": "#000000"},
    "kwai": {"name": "Kwai", "color": "#FF0000"},
    "lojaintegrada": {"name": "Loja Integrada", "color": "#0066CC"},
    "magazineluiza": {"name": "Magazine Luiza", "color": "#0086FF"},
}


class ErpMarketplaceLinksService:
    """Serviço para gestão de vínculos ERP ↔ Marketplace."""

    def __init__(self):
        self.table_name = "erp_marketplace_links"

    def _normalize_module_id(self, module_id: Optional[str]) -> Optional[str]:
        if not module_id:
            return None

        normalized = module_id.strip().lower()
        aliases = {
            "amazon": "amazonfba_classic",
            "tiktok": "tiktokshop",
            "loja_integrada": "lojaintegrada",
            "loja-integrada": "lojaintegrada",
            "mercado_livre": "mercadolivre",
            "mercado-livre": "mercadolivre",
            "magalu": "magazineluiza",
            "magazine_luiza": "magazineluiza",
            "magazine-luiza": "magazineluiza",
        }
        return aliases.get(normalized, normalized)

    def _module_metadata(self, module_id: str) -> Dict[str, str]:
        module_id = self._normalize_module_id(module_id)
        default_name = module_id.replace("_", " ").title()
        return MARKETPLACE_MODULES.get(module_id, {"name": default_name, "color": "#007bff"})

    def _get_marketplace_module_from_integration(self, marketplace_integration_id: Optional[int]) -> Optional[str]:
        if not marketplace_integration_id:
            return None

        result = supabase_db.table("installed_integrations") \
            .select("module_id") \
            .eq("id", marketplace_integration_id) \
            .execute()

        if result.data:
            return self._normalize_module_id(result.data[0].get("module_id"))
        return None

    def _ensure_sales_channel(self, module_id: str) -> Optional[int]:
        module_id = self._normalize_module_id(module_id)
        metadata = self._module_metadata(module_id)

        result = supabase_db.table("canais_venda") \
            .select("id") \
            .eq("nome", metadata["name"]) \
            .execute()
        if result.data:
            return result.data[0]["id"]

        created = supabase_db.table("canais_venda").insert({
            "nome": metadata["name"],
            "slug": module_id,
            "descricao": f"Canal criado automaticamente para {metadata['name']}",
            "ativo": True,
            "color": metadata["color"],
            "configuracao": {"marketplace_module_id": module_id},
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }).execute()

        if created.data:
            return created.data[0]["id"]
        return None

    def _sync_channel_connection(
        self,
        erp_integration_id: int,
        marketplace_integration_id: Optional[int],
        marketplace_module_id: str,
        erp_store_id: str,
        store_name: Optional[str],
        config: Optional[Dict[str, Any]] = None,
        process_webhooks: bool = True
    ) -> None:
        channel_id = self._ensure_sales_channel(marketplace_module_id)
        if not channel_id:
            logger.warning("Nao foi possivel garantir canal para modulo %s", marketplace_module_id)
            return

        payload = {
            "channel_id": channel_id,
            "integration_id": erp_integration_id,
            "bling_integration_id": erp_integration_id,
            "marketplace_integration_id": marketplace_integration_id,
            "marketplace_module_id": marketplace_module_id,
            "aggregator_store_id": str(erp_store_id),
            "aggregator_store_name": store_name or f"{self._module_metadata(marketplace_module_id)['name']} ({erp_store_id})",
            "config": config or {},
            "process_webhooks": process_webhooks is not False,
            "is_active": True,
            "sync_status": "active",
            "updated_at": datetime.utcnow().isoformat(),
        }

        existing = supabase_db.table("channel_connections") \
            .select("id") \
            .eq("channel_id", channel_id) \
            .eq("bling_integration_id", erp_integration_id) \
            .eq("aggregator_store_id", str(erp_store_id)) \
            .eq("is_active", True) \
            .execute()

        if existing.data:
            supabase_db.table("channel_connections") \
                .update(payload) \
                .eq("id", existing.data[0]["id"]) \
                .execute()
            return

        supabase_db.table("channel_connections") \
            .update({
                "is_active": False,
                "updated_at": datetime.utcnow().isoformat(),
            }) \
            .eq("bling_integration_id", erp_integration_id) \
            .eq("aggregator_store_id", str(erp_store_id)) \
            .neq("channel_id", channel_id) \
            .eq("is_active", True) \
            .execute()

        payload["created_at"] = datetime.utcnow().isoformat()
        supabase_db.table("channel_connections").insert(payload).execute()

    def create_link(
        self,
        erp_integration_id: int,
        marketplace_integration_id: Optional[int],
        erp_store_id: str,
        store_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        marketplace_module_id: Optional[str] = None,
        process_webhooks: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Cria vínculo entre ERP e Marketplace.

        Args:
            erp_integration_id: ID da instância ERP em installed_integrations
            marketplace_integration_id: ID da instância Marketplace em installed_integrations
            erp_store_id: ID da loja no ERP (ex: bling_loja_id)
            store_name: Nome amigável da loja (ex: "Shopee Antiga")
            config: Configurações específicas (ex: {"id_campo_personalizado": 2797770})

        Returns:
            Dicionário com dados do vínculo criado ou None se falhar
        """
        try:
            marketplace_module_id = (
                self._normalize_module_id(marketplace_module_id)
                or self._get_marketplace_module_from_integration(marketplace_integration_id)
            )

            if not marketplace_module_id:
                raise ValueError("marketplace_module_id e obrigatorio quando nao ha marketplace_integration_id")

            data = {
                "erp_integration_id": erp_integration_id,
                "marketplace_integration_id": marketplace_integration_id,
                "marketplace_module_id": marketplace_module_id,
                "erp_store_id": str(erp_store_id),
                "store_name": store_name,
                "config": config or {},
                "process_webhooks": process_webhooks is not False,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }

            result = supabase_db.table(self.table_name) \
                .upsert(data, on_conflict="erp_integration_id,erp_store_id") \
                .execute()

            if result.data:
                link = dict(result.data[0])
                link["id"] = str(link.get("id"))
                self._sync_channel_connection(
                    erp_integration_id=erp_integration_id,
                    marketplace_integration_id=marketplace_integration_id,
                    marketplace_module_id=marketplace_module_id,
                    erp_store_id=erp_store_id,
                    store_name=store_name,
                    config=config,
                    process_webhooks=process_webhooks,
                )
                logger.info(
                    "Vínculo criado: ERP=%s, Marketplace=%s, Loja=%s",
                    erp_integration_id,
                    marketplace_integration_id,
                    erp_store_id
                )
                return link

            return None

        except Exception as e:
            logger.error(f"Erro ao criar vínculo: {e}", exc_info=True)
            return None

    def delete_link(self, link_id: str) -> bool:
        """
        Remove vínculo ERP ↔ Marketplace.

        Args:
            link_id: ID do vínculo em erp_marketplace_links

        Returns:
            True se removido com sucesso, False caso contrário
        """
        try:
            current = supabase_db.table(self.table_name) \
                .select("erp_integration_id, erp_store_id, marketplace_module_id") \
                .eq("id", link_id) \
                .execute()

            result = supabase_db.table(self.table_name).delete().eq("id", link_id).execute()

            if result.data:
                logger.info("Vínculo %s removido", link_id)
                return True

            return False

        except Exception as e:
            logger.error(f"Erro ao remover vínculo: {e}", exc_info=True)
            return False

    def get_links_by_erp(self, erp_integration_id: int) -> List[Dict[str, Any]]:
        """
        Retorna todos marketplaces vinculados a um ERP.

        Args:
            erp_integration_id: ID da instância ERP

        Returns:
            Lista de vínculos com dados do marketplace
        """
        try:
            result = supabase_db.table(self.table_name).select("""
                *,
                marketplace:installed_integrations!erp_marketplace_links_marketplace_integration_id_fkey (
                    id,
                    module_id,
                    instance_name,
                    is_active
                )
            """).eq("erp_integration_id", erp_integration_id).execute()

            if result.data:
                links = []
                for link in result.data:
                    link["id"] = str(link.get("id"))
                    if not link.get("marketplace") and link.get("marketplace_module_id"):
                        metadata = self._module_metadata(link["marketplace_module_id"])
                        link["marketplace"] = {
                            "id": None,
                            "module_id": link["marketplace_module_id"],
                            "instance_name": metadata["name"],
                            "is_active": False,
                            "catalog_only": True,
                        }
                    links.append(link)
                return links

            return []

        except Exception as e:
            logger.error(f"Erro ao buscar vínculos por ERP: {e}", exc_info=True)
            return []

    def get_links_by_marketplace(self, marketplace_integration_id: int) -> List[Dict[str, Any]]:
        """
        Retorna todos ERPs vinculados a um marketplace.

        Args:
            marketplace_integration_id: ID da instância Marketplace

        Returns:
            Lista de vínculos com dados do ERP
        """
        try:
            result = supabase_db.table(self.table_name).select("""
                *,
                erp:installed_integrations (
                    id,
                    module_id,
                    instance_name,
                    is_active
                )
            """).eq("marketplace_integration_id", marketplace_integration_id).execute()

            if result.data:
                links = []
                for link in result.data:
                    link["id"] = str(link.get("id"))
                    links.append(link)
                return links

            return []

        except Exception as e:
            logger.error(f"Erro ao buscar vínculos por Marketplace: {e}", exc_info=True)
            return []

    def get_erp_store_for_marketplace(
        self,
        erp_integration_id: int,
        marketplace_integration_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Retorna vínculo específico ERP ↔ Marketplace.

        Args:
            erp_integration_id: ID da instância ERP
            marketplace_integration_id: ID da instância Marketplace

        Returns:
            Dicionário com dados do vínculo ou None se não encontrado
        """
        try:
            result = supabase_db.table(self.table_name).select("*") \
                .eq("erp_integration_id", erp_integration_id) \
                .eq("marketplace_integration_id", marketplace_integration_id) \
                .execute()

            if result.data:
                link = dict(result.data[0])
                link["id"] = str(link.get("id"))
                return link

            return None

        except Exception as e:
            logger.error(f"Erro ao buscar vínculo específico: {e}", exc_info=True)
            return None

    def get_marketplace_for_erp_store(
        self,
        erp_integration_id: int,
        erp_store_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Retorna marketplace vinculado a uma loja do ERP.

        Args:
            erp_integration_id: ID da instância ERP
            erp_store_id: ID da loja no ERP (ex: bling_loja_id)

        Returns:
            Dicionário com dados do vínculo ou None se não encontrado
        """
        try:
            result = supabase_db.table(self.table_name).select("""
                *,
                marketplace:installed_integrations (
                    id,
                    module_id,
                    instance_name,
                    is_active
                )
            """) \
                .eq("erp_integration_id", erp_integration_id) \
                .eq("erp_store_id", str(erp_store_id)) \
                .execute()

            if result.data:
                link = dict(result.data[0])
                link["id"] = str(link.get("id"))
                return link

            return None

        except Exception as e:
            logger.error(f"Erro ao buscar marketplace por loja ERP: {e}", exc_info=True)
            return None

    def get_custom_field_id(
        self,
        erp_integration_id: int,
        marketplace_integration_id: Optional[int] = None
    ) -> int:
        """
        Retorna ID do campo customizado de personalização.

        Args:
            erp_integration_id: ID da instância ERP
            marketplace_integration_id: ID da instância Marketplace (opcional)

        Returns:
            ID do campo customizado (default: 2797770)
        """
        try:
            # Se marketplace específico for informado, buscar config do vínculo
            if marketplace_integration_id:
                link = self.get_erp_store_for_marketplace(
                    erp_integration_id,
                    marketplace_integration_id
                )
                if link and link.get("config"):
                    return link["config"].get("id_campo_personalizado", 2797770)

            # Buscar primeira config disponível para este ERP
            links = self.get_links_by_erp(erp_integration_id)
            for link in links:
                if link.get("config") and link["config"].get("id_campo_personalizado"):
                    return link["config"]["id_campo_personalizado"]

            # Default
            return 2797770

        except Exception as e:
            logger.error(f"Erro ao buscar id_campo_personalizado: {e}", exc_info=True)
            return 2797770  # Default fallback

    def update_config(
        self,
        link_id: str,
        config: Dict[str, Any],
        process_webhooks: Optional[bool] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Atualiza configurações de um vínculo.

        Args:
            link_id: ID do vínculo
            config: Novas configurações (merge com existente)

        Returns:
            Dicionário com dados atualizados ou None se falhar
        """
        try:
            # Buscar config atual
            current = supabase_db.table(self.table_name).select("config").eq("id", link_id).execute()

            if not current.data:
                return None

            # Merge com nova config
            updated_config = {**current.data[0].get("config", {}), **config}

            # Atualizar
            update_payload = {
                "config": updated_config,
                "updated_at": datetime.utcnow().isoformat()
            }
            if process_webhooks is not None:
                update_payload["process_webhooks"] = process_webhooks is not False

            result = supabase_db.table(self.table_name).update(update_payload).eq("id", link_id).execute()

            if result.data:
                link = dict(result.data[0])
                link["id"] = str(link.get("id"))
                self._sync_channel_connection(
                    erp_integration_id=link["erp_integration_id"],
                    marketplace_integration_id=link.get("marketplace_integration_id"),
                    marketplace_module_id=link.get("marketplace_module_id"),
                    erp_store_id=link.get("erp_store_id"),
                    store_name=link.get("store_name"),
                    config=link.get("config"),
                    process_webhooks=link.get("process_webhooks", True),
                )
                return link

            return None

        except Exception as e:
            logger.error(f"Erro ao atualizar config: {e}", exc_info=True)
            return None


# Global instance
erp_marketplace_links_service = ErpMarketplaceLinksService()
