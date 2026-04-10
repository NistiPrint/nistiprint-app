"""
Script de backfill para marcar pedidos e produtos existentes como personalizados.

Este script deve ser executado uma única vez para retroativamente marcar:
1. Pedidos em `pedidos_bling` que têm extrações de IA salvas
2. Itens em `itens_pedido_bling` correspondentes
3. Produtos internos vinculados a produtos Bling personalizados
4. Pedidos e itens no modelo unificado (`pedidos`, `itens_pedido`)

Uso:
    python packages/shared/nistiprint_shared/scripts/backfill_personalizado.py
"""

import logging
import sys
import os

# Adicionar path para imports
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, '..', '..', '..', '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Carregar variáveis de ambiente antes de qualquer import do shared
try:
    from dotenv import load_dotenv
    # Tenta .env na raiz do projeto
    env_path = os.path.join(_PROJECT_ROOT, 'apps', 'api', '.env')
    print(env_path)
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)
        logging.info(f"Environment loaded from {env_path}")
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger("BackfillPersonalizado")

# Agora importa o serviço de banco de dados
from nistiprint_shared.database.supabase_db_service import supabase_db, SupabaseDBService


def _ensure_db():
    """Garante que o cliente Supabase foi inicializado."""
    if not supabase_db._ensure_client():
        raise RuntimeError(
            "Supabase não configurado. Defina SUPABASE_URL e SUPABASE_SERVICE_KEY "
            "no .env do projeto ou como variáveis de ambiente."
        )


def backfill_from_personalizations():
    """
    Backfill baseado em extrações de IA já existentes em order_personalizations.
    Se um pedido tem personalizações salvas, ele é personalizado.
    """
    logger.info("=" * 60)
    logger.info("BACKFILL: order_personalizations → pedidos_bling/itens")
    logger.info("=" * 60)

    # 1. Buscar todos os shopee_order_sn únicos com personalizações
    response = supabase_db.table('personalizacoes_pedido') \
        .select('shopee_order_sn, item_description') \
        .execute()

    if not response.data:
        logger.info("Nenhuma personalização existente encontrada. Pulando.")
        return 0

    order_sns = set()
    item_descs = {}
    for p in response.data:
        sn = p.get('shopee_order_sn')
        desc = p.get('item_description')
        if sn:
            order_sns.add(sn)
            if sn not in item_descs:
                item_descs[sn] = set()
            if desc:
                item_descs[sn].add(desc)

    logger.info(f"Encontrados {len(order_sns)} pedidos com personalizações de IA.")

    # 2. Marcar pedidos_bling como personalizados
    marked_pedidos = 0
    for sn in order_sns:
        result = supabase_db.table('pedidos_bling') \
            .update({'personalizado': True}) \
            .eq('numero_loja', sn) \
            .execute()

        if result.data:
            marked_pedidos += 1

    logger.info(f"✓ {marked_pedidos} pedidos_bling marcados como personalizados.")

    # 3. Marcar itens_pedido_bling como personalizados
    marked_itens = 0
    for sn, descs in item_descs.items():
        for desc in descs:
            result = supabase_db.table('itens_pedido_bling') \
                .update({'personalizado': True}) \
                .eq('descricao', desc) \
                .execute()

            if result.data:
                marked_itens += len(result.data)

    logger.info(f"✓ {marked_itens} itens_pedido_bling marcados como personalizados.")

    return marked_pedidos


def backfill_from_bling_items():
    """
    Backfill baseado em itens que já estão marcados como personalizados
    em itens_pedido_bling mas cujos pedidos podem não estar marcados.
    """
    logger.info("=" * 60)
    logger.info("BACKFILL: itens_pedido_bling → pedidos_bling")
    logger.info("=" * 60)

    # Buscar pedidos que têm itens personalizados mas não estão marcados
    result = supabase_db.table('pedidos_bling') \
        .select('id, numero_loja') \
        .eq('personalizado', False) \
        .neq('deletado', True) \
        .execute()

    if not result.data:
        logger.info("Nenhum pedido candidato para backfill. Pulando.")
        return 0

    marked = 0
    for pedido in result.data:
        # Verificar se tem itens personalizados
        itens_result = supabase_db.table('itens_pedido_bling') \
            .select('id') \
            .eq('pedido_bling_id', pedido['id']) \
            .eq('personalizado', True) \
            .limit(1) \
            .execute()

        if itens_result.data:
            supabase_db.table('pedidos_bling') \
                .update({'personalizado': True}) \
                .eq('id', pedido['id']) \
                .execute()
            marked += 1

    logger.info(f"✓ {marked} pedidos_bling marcados via itens existentes.")
    return marked


def backfill_internal_products():
    """
    Backfill para marcar produtos internos como personalizados
    baseado em vínculos Bling com itens já marcados.
    """
    logger.info("=" * 60)
    logger.info("BACKFILL: produtos Bling personalizados → produtos internos")
    logger.info("=" * 60)

    # Buscar produtos Bling que aparecem em itens personalizados
    bling_products = supabase_db.table('itens_pedido_bling') \
        .select('produto') \
        .eq('personalizado', True) \
        .not_.is_('produto', 'null') \
        .execute()

    if not bling_products.data:
        logger.info("Nenhum produto Bling personalizado encontrado. Pulando.")
        return 0

    # Extrair IDs únicos de produtos Bling
    bling_ids = set()
    for item in bling_products.data:
        produto = item.get('produto', {})
        if isinstance(produto, dict):
            pid = produto.get('id')
            if pid:
                bling_ids.add(str(pid))

    logger.info(f"Encontrados {len(bling_ids)} produtos Bling em itens personalizados.")

    # Buscar vínculos e marcar produtos internos
    marked_products = 0
    for bling_id in bling_ids:
        vinculo = supabase_db.table('vinculos_bling') \
            .select('produto_id') \
            .eq('codigo_bling', bling_id) \
            .limit(1) \
            .execute()

        if vinculo.data:
            product_id = vinculo.data[0]['produto_id']

            # Verificar se já está marcado
            check = supabase_db.table('produtos') \
                .select('id, personalizado') \
                .eq('id', product_id) \
                .limit(1) \
                .execute()

            if check.data and not check.data[0].get('personalizado'):
                supabase_db.table('produtos') \
                    .update({'personalizado': True}) \
                    .eq('id', product_id) \
                    .execute()
                marked_products += 1

    logger.info(f"✓ {marked_products} produtos internos marcados como personalizados.")
    return marked_products


def backfill_unified_model():
    """
    Backfill para o modelo unificado (pedidos + itens_pedido).
    Marca itens_pedido como personalizado baseado em itens_pedido_bling.
    NOTA: A coluna pedidos.personalizado precisa existir (migration 20260409_add_pedidos_personalizado).
    """
    logger.info("=" * 60)
    logger.info("BACKFILL: itens_pedido_bling → itens_pedido (modelo unificado)")
    logger.info("=" * 60)

    # Verificar se a coluna pedidos.personalizado existe
    try:
        supabase_db.table('pedidos').select('personalizado').limit(1).execute()
        pedidos_has_column = True
    except Exception:
        pedidos_has_column = False
        logger.warning("Coluna pedidos.personalizado NÃO existe. Pulando update em pedidos.")

    # Buscar itens_pedido_bling personalizados com suas descrições e pedidos_bling vinculados
    itens_bling = supabase_db.table('itens_pedido_bling') \
        .select('pedido_bling_id, descricao') \
        .eq('personalizado', True) \
        .execute()

    if not itens_bling.data:
        logger.info("Nenhum item_pedido_bling personalizado encontrado. Pulando.")
        return 0, 0

    # Agrupar por pedido_bling_id
    pedido_itens_map = {}
    for item in itens_bling.data:
        pid = item.get('pedido_bling_id')
        desc = item.get('descricao')
        if pid and desc:
            if pid not in pedido_itens_map:
                pedido_itens_map[pid] = []
            pedido_itens_map[pid].append(desc)

    marked_pedidos = 0
    marked_itens = 0

    for pb_id, descs in pedido_itens_map.items():
        # Buscar o numero_loja do pedido_bling
        pb_result = supabase_db.table('pedidos_bling') \
            .select('numero_loja') \
            .eq('id', pb_id) \
            .limit(1) \
            .execute()

        if not pb_result.data:
            continue

        numero_loja = pb_result.data[0].get('numero_loja')
        if not numero_loja:
            continue

        # Buscar pedido unificado correspondente
        pedido_unificado = supabase_db.table('pedidos') \
            .select('id') \
            .or_(f"codigo_pedido_externo.eq.{numero_loja}") \
            .limit(1) \
            .execute()

        if pedido_unificado.data:
            pedido_id = pedido_unificado.data[0]['id']

            # Marcar pedido como personalizado (se coluna existir)
            if pedidos_has_column:
                supabase_db.table('pedidos') \
                    .update({'personalizado': True}) \
                    .eq('id', pedido_id) \
                    .execute()
                marked_pedidos += 1

            # Marcar itens correspondentes
            for desc in descs:
                result = supabase_db.table('itens_pedido') \
                    .update({'personalizado': True}) \
                    .eq('pedido_id', pedido_id) \
                    .eq('descricao', desc) \
                    .execute()

                if result.data:
                    marked_itens += len(result.data)

    logger.info(f"✓ {marked_pedidos} pedidos unificados marcados.")
    logger.info(f"✓ {marked_itens} itens_pedido unificados marcados.")
    return marked_pedidos, marked_itens


def main():
    logger.info("Iniciando backfill de campos personalizado...")
    _ensure_db()

    total_pedidos_ia = backfill_from_personalizations()
    total_pedidos_itens = backfill_from_bling_items()
    total_produtos = backfill_internal_products()
    total_unified_pedidos, total_unified_itens = backfill_unified_model()

    logger.info("=" * 60)
    logger.info("RESUMO DO BACKFILL:")
    logger.info(f"  Pedidos marcados via IA:      {total_pedidos_ia}")
    logger.info(f"  Pedidos marcados via itens:   {total_pedidos_itens}")
    logger.info(f"  Produtos internos marcados:   {total_produtos}")
    logger.info(f"  Pedidos unificados marcados:  {total_unified_pedidos}")
    logger.info(f"  Itens unificados marcados:    {total_unified_itens}")
    logger.info("=" * 60)
    logger.info("Backfill concluído!")


if __name__ == "__main__":
    main()
