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


class ErpMarketplaceLinksService:
    """Serviço para gestão de vínculos ERP ↔ Marketplace."""

    def __init__(self):
        self.table_name = "erp_marketplace_links"

    def create_link(
        self,
        erp_integration_id: int,
        marketplace_integration_id: int,
        erp_store_id: str,
        store_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
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
            data = {
                "erp_integration_id": erp_integration_id,
                "marketplace_integration_id": marketplace_integration_id,
                "erp_store_id": str(erp_store_id),
                "store_name": store_name,
                "config": config or {},
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }

            result = supabase_db.table(self.table_name).insert(data).execute()

            if result.data:
                link = dict(result.data[0])
                link["id"] = str(link.get("id"))
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
                marketplace:installed_integrations (
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
        config: Dict[str, Any]
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
            result = supabase_db.table(self.table_name).update({
                "config": updated_config,
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", link_id).execute()

            if result.data:
                link = dict(result.data[0])
                link["id"] = str(link.get("id"))
                return link

            return None

        except Exception as e:
            logger.error(f"Erro ao atualizar config: {e}", exc_info=True)
            return None


# Global instance
erp_marketplace_links_service = ErpMarketplaceLinksService()
