"""
Para cada linha em canais_venda, criar (ou localizar) installed_integration
de tipo 'marketplace' e popular config a partir das colunas + de channel_connections.

Idempotente: usa instance_name como chave; se já existir, apenas atualiza config.
Após rodar, repointa pedidos.canal_venda_id → marketplace_integration_id e zera
canais_venda (ou deixa marcada como migrated=true se preferir manter histórico).
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

from nistiprint_shared.database.supabase_db_service import supabase_db
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_canais_to_marketplace():
    """
    Migração de canais_venda para installed_integrations (marketplace).

    Corrigido:
    - plataforma_slug vem via plataforma_id → plataformas.slug
    - bling_loja_id vem via channel_connections.aggregator_store_id
    - Config é minimalista: shop_id, bling_loja_id, is_flex_capable, color
    - Regras logísticas (horario_corte, ponto_coleta_id) continuam em regras_logisticas_canal
    """
    logger.info("Iniciando migração de canais_venda para installed_integrations...")

    if not supabase_db.client:
        logger.error("Supabase client não inicializado. Verifique SUPABASE_URL e SUPABASE_SERVICE_KEY.")
        return

    # 1. Buscar todos os canais_venda ativos COM join para plataformas (não slug)
    try:
        # Query: canais_venda + plataformas para pegar nome
        # (plataformas.slug NÃO existe; slug fica em integration_modules)
        canais_response = supabase_db.table('canais_venda') \
            .select('*, plataformas!inner(id, nome, tipo)') \
            .eq('ativo', True) \
            .execute()

        if not canais_response or not hasattr(canais_response, 'data') or not canais_response.data:
            logger.warning("Nenhum canal ativo encontrado")
            return
        canais = canais_response.data
    except Exception as e:
        logger.error(f"Erro ao buscar canais_venda com plataformas: {e}")
        return

    logger.info(f"Encontrados {len(canais)} canais ativos para migrar")

    # Pre-cache de modules marketplace
    # Nota: em integration_modules, 'id' é o slug (ex: 'shopee', 'amazon')
    try:
        modules_response = supabase_db.table('integration_modules') \
            .select('id, name, tipo, is_aggregator') \
            .ilike('tipo', '%marketplace%') \
            .eq('is_active', True) \
            .execute()

        if modules_response and modules_response.data:
            # modules_by_slug: {'shopee': 'shopee', 'amazon': 'amazon', ...}
            # (id em integration_modules já é o slug)
            modules_by_slug = {m['id']: m['id'] for m in modules_response.data}
            logger.info(f"Modules marketplace encontrados: {list(modules_by_slug.keys())}")
        else:
            logger.warning("Nenhum module marketplace encontrado com ilike MARKETPLACE")
            # Fallback: buscar com LIKE
            modules_response = supabase_db.table('integration_modules') \
                .select('id, name, tipo') \
                .execute()
            modules_by_slug = {m['id']: m['id'] for m in (modules_response.data or [])
                              if m.get('is_aggregator') is False}
            logger.info(f"Fallback modules: {list(modules_by_slug.keys())}")
    except Exception as e:
        logger.warning(f"Erro ao cachear modules: {e}")
        modules_by_slug = {}

    for canal in canais:
        canal_id = canal['id']
        canal_nome = canal['nome']

        # Extrair plataforma_nome do objeto nested (JOIN)
        plataforma_obj = canal.get('plataformas')
        if isinstance(plataforma_obj, list) and plataforma_obj:
            plataforma_obj = plataforma_obj[0]

        plataforma_nome = plataforma_obj.get('nome') if isinstance(plataforma_obj, dict) else None

        if not plataforma_nome:
            logger.warning(f"Canal {canal_nome} sem plataforma_nome válida, pulando")
            continue

        # Converter nome para slug: "Shopee" → "shopee", "Mercado Livre" → "mercadolivre"
        plataforma_slug = plataforma_nome.lower().replace(' ', '')
        logger.info(f"[{canal_nome}] plataforma={plataforma_nome} (slug={plataforma_slug})")

        # Skip non-marketplace channels
        if plataforma_slug in ['nistiprint', 'nisti', 'venda', 'avulso', 'direta']:
            logger.info(f"[{canal_nome}] Pulando canal não-marketplace")
            continue

        # 2. Resolver module_id via integration_modules
        # (module_id em integration_modules é texto, ex: 'shopee', 'amazon', etc)
        module_id = modules_by_slug.get(plataforma_slug)
        if not module_id:
            logger.warning(f"[{canal_nome}] Module '{plataforma_slug}' não encontrado em cache, pulando")
            logger.info(f"[{canal_nome}] Modules disponíveis: {list(modules_by_slug.keys())}")
            continue
        logger.info(f"[{canal_nome}] module_id={module_id}")

        # 3. Buscar bling_loja_id via channel_connections
        bling_loja_id = None
        try:
            conn_response = supabase_db.table('channel_connections') \
                .select('aggregator_store_id') \
                .eq('channel_id', canal_id) \
                .maybe_single() \
                .execute()
            if conn_response and conn_response.data:
                bling_loja_id = conn_response.data.get('aggregator_store_id')
        except Exception as e:
            logger.debug(f"[{canal_nome}] channel_connections não disponível (continuando sem bling_loja_id)")

        logger.info(f"[{canal_nome}] bling_loja_id={bling_loja_id}")

        # 4. Montar config MINIMALISTA
        # Notas:
        # - shop_id e bling_loja_id são o mesmo (identificador da loja no Bling = shop_id marketplace)
        # - horario_corte, ponto_coleta_id continuam em regras_logisticas_canal
        # - is_flex_capable vem do campo 'flex' de canais_venda
        config = {
            'shop_id': bling_loja_id,
            'bling_loja_id': str(bling_loja_id) if bling_loja_id else None,
            'is_flex_capable': canal.get('flex', False),
            'color': canal.get('color'),
        }
        logger.info(f"[{canal_nome}] config={config}")

        # 5. Verificar se já existe installed_integration
        existing = None
        try:
            existing_response = supabase_db.table('installed_integrations') \
                .select('id') \
                .eq('instance_name', canal_nome) \
                .eq('module_id', module_id) \
                .maybe_single() \
                .execute()
            existing = existing_response.data if existing_response else None
        except Exception as e:
            logger.warning(f"[{canal_nome}] Erro ao buscar installed_integration existente: {e}")

        marketplace_integration_id = None
        if existing:
            # UPDATE
            logger.info(f"[{canal_nome}] Atualizando installed_integration existente")
            try:
                supabase_db.table('installed_integrations') \
                    .update({'config': config}) \
                    .eq('id', existing['id']) \
                    .execute()
                marketplace_integration_id = existing['id']
            except Exception as e:
                logger.error(f"[{canal_nome}] Erro ao atualizar: {e}")
                continue
        else:
            # INSERT
            logger.info(f"[{canal_nome}] Criando nova installed_integration")
            try:
                result = supabase_db.table('installed_integrations') \
                    .insert({
                        'instance_name': canal_nome,
                        'module_id': module_id,
                        'config': config,
                        'is_active': True,
                    }) \
                    .execute()
                if result and result.data:
                    marketplace_integration_id = result.data[0]['id']
                else:
                    logger.error(f"[{canal_nome}] INSERT retornou vazio")
                    continue
            except Exception as e:
                logger.error(f"[{canal_nome}] Erro ao criar: {e}")
                continue

        logger.info(f"[{canal_nome}] marketplace_integration_id={marketplace_integration_id}")

        # 6. Repointar dados
        try:
            # 6a. pedidos
            supabase_db.table('pedidos') \
                .update({'marketplace_integration_id': marketplace_integration_id}) \
                .eq('canal_venda_id', canal_id) \
                .execute()
            logger.info(f"[{canal_nome}] pedidos repontados")

            # 6b. regras_logisticas_canal
            supabase_db.table('regras_logisticas_canal') \
                .update({'marketplace_integration_id': marketplace_integration_id}) \
                .eq('canal_venda_id', canal_id) \
                .execute()
            logger.info(f"[{canal_nome}] regras_logisticas_canal repontadas")

            # 6c. flex_classification_rules
            supabase_db.table('flex_classification_rules') \
                .update({'marketplace_integration_id': marketplace_integration_id}) \
                .eq('canal_venda_id', canal_id) \
                .execute()
            logger.info(f"[{canal_nome}] flex_classification_rules repontadas")
        except Exception as e:
            logger.error(f"[{canal_nome}] Erro ao repontar dados: {e}")
            continue

        logger.info(f"✓ [{canal_nome}] migrado com sucesso")

    logger.info("\n=== Migração concluída ===")
    logger.info("Próximos passos (após validação):")
    logger.info("  1. Verificar dados em installed_integrations vs canais_venda")
    logger.info("  2. Validar regras_logisticas_canal apontam para marketplace_integration_id")
    logger.info("  3. Validar pedidos apontam para marketplace_integration_id")
    logger.info("  4. Executar migration para DROP colunas canal_venda_id")

if __name__ == '__main__':
    migrate_canais_to_marketplace()
