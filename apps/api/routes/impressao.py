"""
Endpoints para geração do template de impressão (papéis de pedido).

Fluxo:
1. Frontend chama GET /api/v2/pedidos/impressao?order_ids=1,2,3
2. Backend monta dados completos de cada pedido (cliente, itens, personalizações, custom_tags)
3. Frontend renderiza componente React com CSS @media print e dispara window.print()
"""

from flask import Blueprint, request
from routes.auth import login_required
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.order_erp_reference_service import order_erp_reference_service
from nistiprint_shared.utils import process_string
from utils.api_response import ApiResponse
import logging

logger = logging.getLogger("ImpressaoAPI")

impressao_api_bp = Blueprint('impressao_api', __name__, url_prefix='/api/v2/pedidos/impressao')

# Nome de exibicao por marketplace. O template usa este valor para o cabecalho
# do pedido e para escolher o icone.
MARKETPLACE_DISPLAY_NAMES = {
    'shopee': 'Shopee',
    'mercadolivre': 'Mercado Livre',
    'amazonfba_classic': 'Amazon',
    'amazon_fulfillment': 'Amazon',
    'shein': 'Shein',
    'tiktokshop': 'TikTok Shop',
    'kwai': 'Kwai',
    'lojaintegrada': 'Loja Integrada',
    'magazineluiza': 'Magazine Luiza',
}


@impressao_api_bp.route('', methods=['GET'])
@login_required
def get_impressao_data():
    """
    Retorna dados formatados para o template de impressão.

    Query params:
    - order_ids: str (lista de IDs separados por vírgula)
    - plataforma: str (filtrar por plataforma: BLING, SHOPEE)

    Retorna:
    - orders: lista de pedidos formatados para impressão
    """
    try:
        order_ids_param = request.args.get('order_ids')
        plataforma = request.args.get('plataforma')

        if not order_ids_param:
            return ApiResponse.error('order_ids é obrigatório', 400)

        order_ids = [int(id.strip()) for id in order_ids_param.split(',') if id.strip()]

        orders_data = []
        blocked_orders = []

        resolution = order_erp_reference_service.resolve_many(order_ids, allow_remote=True)
        ready_ids = {item['pedido_id'] for item in resolution['ready']}
        blocked_orders.extend(resolution['blocked'])
        for order_id in order_ids:
            if order_id not in ready_ids:
                continue
            order = _build_order_print_data(order_id, plataforma)
            if order:
                orders_data.append(order)
            else:
                blocked_orders.append({
                    'pedido_id': order_id,
                    'status': 'invalid_print_data',
                    'message': 'Pedido sem número Bling ou dados para impressão',
                })

        orders_data.sort(key=_print_sort_key)

        return ApiResponse.success({
            'orders': orders_data,
            'total': len(orders_data),
            'blocked_orders': blocked_orders,
            'blocked_total': len(blocked_orders)
        })

    except Exception as e:
        logger.error(f"Erro ao buscar dados de impressão: {e}", exc_info=True)
        return ApiResponse.error(str(e), 500)


def _primeira_custom_tag(order: dict) -> str:
    """Primeira tag de personalizacao do pedido, em ordem de item."""
    for item in order.get('itens') or []:
        tag = (item.get('custom_tag') or '').strip()
        if tag:
            return tag
    return ''


def _primeiro_valor_preenchido(*valores):
    """Retorna o primeiro valor textual que nao esteja vazio."""
    for valor in valores:
        if valor is not None and str(valor).strip():
            return valor
    return ''


def _nome_completo(primeiro, ultimo) -> str:
    """Monta um nome completo sem criar espacos extras."""
    return ' '.join(
        str(parte).strip()
        for parte in (primeiro, ultimo)
        if parte is not None and str(parte).strip()
    )


def _nome_destinatario_mercadolivre(
    *,
    logistics: dict | None,
    customer: dict | None,
    platform_fields: dict | None,
    fallback: str,
) -> str:
    """Resolve o nome do comprador MercadoLivre sem confundir nickname com nome."""
    logistics = logistics if isinstance(logistics, dict) else {}
    customer = customer if isinstance(customer, dict) else {}
    platform_fields = platform_fields if isinstance(platform_fields, dict) else {}

    address = logistics.get('address')
    if not isinstance(address, dict):
        address = {}

    # Snapshots antigos podem ter o endereco somente dentro do payload bruto
    # especifico do MercadoLivre. Mantemos esse fallback para nao exigir
    # reingestao dos pedidos ja existentes.
    meli_fields = platform_fields.get('mercadolivre')
    if not isinstance(meli_fields, dict):
        meli_fields = {}
    meli_order = meli_fields.get('order')
    if not isinstance(meli_order, dict):
        meli_order = {}
    meli_shipment = meli_fields.get('shipment')
    if not isinstance(meli_shipment, dict):
        meli_shipment = {}
    meli_shipping = meli_order.get('shipping')
    if not isinstance(meli_shipping, dict):
        meli_shipping = {}
    raw_address = meli_shipment.get('receiver_address') or meli_shipping.get('receiver_address')
    addresses = [address]
    if isinstance(raw_address, dict) and raw_address != address:
        addresses.append(raw_address)

    raw_buyer = customer.get('raw')
    if not isinstance(raw_buyer, dict):
        raw_buyer = {}

    nome_comprador = _nome_completo(
        raw_buyer.get('first_name') or customer.get('first_name'),
        raw_buyer.get('last_name') or customer.get('last_name'),
    )
    return _primeiro_valor_preenchido(
        nome_comprador,
        *(campo
          for address_candidate in addresses
          for campo in (
              address_candidate.get('receiver_name'),
              address_candidate.get('recipient_name'),
              address_candidate.get('name'),
          )),
        fallback,
    )


def _numero_externo_mercadolivre_sort_key(order: dict):
    """Ordena IDs numericos e usa o texto como fallback."""
    numero = str(order.get('numeroLoja') or '').strip()
    if numero.isdigit():
        return (0, int(numero), numero)
    return (1, 0, numero)


def _print_sort_key(order: dict):
    """Ordem de impressao por plataforma.

    MercadoLivre usa o numero externo crescente. As demais plataformas usam
    a chave legada abaixo.

    Do legado (`kb/legado/services/bling/bling.py`):

        1. itens personalizados: nao depois sim (agrupa pedidos com item
           personalizado)
        2. quais itens personalizados: ordem alfabetica (agrupa os
           personalizados por modelo)
        3. quantidade total de itens: ordem crescente
        4. quantos itens diferentes: ordem crescente

    A versao anterior mantinha so o primeiro criterio e usava `numeroLoja` como
    desempate. `numeroLoja` e efetivamente aleatorio em relacao ao produto, o
    que desfazia justamente o agrupamento por modelo — que e o ganho
    operacional da ordenacao: quem imprime quer as mesmas capas juntas.
    """
    if order.get('plataforma_slug') == 'mercadolivre':
        return (0, *_numero_externo_mercadolivre_sort_key(order))

    itens = order.get('itens') or []
    return (
        1 if order.get('hasCustomItem') else 0,
        order.get('total_items') or 0,
        len(itens),
        len([i for i in itens if (i.get('custom_tag') or '').strip()]),
        _primeira_custom_tag(order),
    )


def _build_order_print_data(pedido_id: int, plataforma_filter: str = None) -> dict | None:
    """
    Monta dados completos de um pedido para o template de impressão.
    Inclui: cliente, itens, personalizações, custom_tags.
    """
    try:
        # 1. Buscar pedido core
        pedido_result = supabase_db.table('pedidos').select('*').eq('id', pedido_id).single().execute()
        if not pedido_result.data:
            return None

        pedido = pedido_result.data
        erp_number = pedido.get('erp_order_number')
        if not erp_number:
            return None

        # 2. Plataforma de origem.
        #
        # Antes isto vinha de `vinculos_integracao_pedido`, tabela que esta
        # vazia em producao. O efeito era duplo: `plataforma` chegava sempre em
        # branco no template (que a usa para o icone e o cabecalho do pedido) e,
        # pior, informar `plataforma_filter` fazia *todo* pedido ser descartado,
        # porque a lista de vinculos nunca tinha nada para casar.
        #
        # A origem canonica ja esta no proprio pedido.
        plataforma_slug = (pedido.get('marketplace_module_id') or '').strip().lower()
        if plataforma_filter:
            filtro = plataforma_filter.strip().lower()
            # `BLING` nao e marketplace: e o caminho de ingest. Um pedido
            # ingerido via ERP satisfaz o filtro qualquer que seja seu canal.
            if filtro == 'bling':
                if (pedido.get('ingest_source') or '').lower() != 'bling':
                    return None
            elif plataforma_slug != filtro:
                return None

        # 3. Buscar itens do pedido com tag_impressao_pdf do produto
        itens_result = supabase_db.table('itens_pedido').select(
            '*, produtos(tag_impressao_pdf)'
        ).eq('pedido_id', pedido_id).execute()
        itens_raw = itens_result.data or []

        # 4. Buscar personalizações
        personalizations_result = supabase_db.table('personalizacoes_pedido').select('*').eq('shopee_order_sn', pedido.get('codigo_pedido_externo')).execute()
        personalizations_raw = personalizations_result.data or []

        # 5. Montar estrutura de itens formatada
        itens_formatted = []
        for item in itens_raw:
            # Extrair tag do produto relacionado, se existir
            tag_do_produto = None
            if item.get('produtos'):
                tag_do_produto = item.get('produtos').get('tag_impressao_pdf')
            
            # Buscar personalizações associadas a este item
            item_pers = []
            for p in personalizations_raw:
                # Match por item_pedido_id (prioridade) ou descricao (fallback)
                if (p.get('item_pedido_id') == item.get('id')) or \
                   (p.get('item_pedido_id') is None and p.get('item_description') == item.get('descricao')):
                    detalhes = p.get('detalhes_personalizacao') or {}
                    metadata = p.get('metadata') or {}
                    item_pers.append({
                        'customization_name': p.get('customization_name'),
                        'customization_initial': p.get('customization_initial'),
                        'quantity_to_personalize': detalhes.get('quantity_to_personalize')
                            or metadata.get('quantity_to_personalize', 1),
                        'status': p.get('status'),
                    })

            # A variacao do anuncio ("CAPA 1", "Cabelo 6") vem do snapshot do
            # marketplace e ja esta gravada no item. Ela e o nome que o modelo
            # tem na origem — e, na pratica, o unico identificador de modelo que
            # existe para todo item personalizado.
            variacao = (item.get('variacao_externa') or '').strip()

            # A tag do modelo, na ordem de quem sabe mais sobre o produto:
            #   1. o cadastro interno, quando o SKU esta vinculado;
            #   2. a tabela do legado (`process_string`), que so conhece a
            #      geracao de SKUs da epoca em que foi escrita;
            #   3. a variacao do anuncio.
            #
            # Sem o terceiro degrau a folha do personalizado sai com o rodape em
            # branco: hoje nenhum SKU pendente tem `tag_impressao_pdf` e nenhum
            # e reconhecido por `process_string`, enquanto todos os 45 itens
            # personalizados pendentes tem variacao. Sem tag no papel, quem
            # monta o pedido nao sabe qual capa pegar.
            custom_tag = (tag_do_produto or '').strip()
            if not custom_tag and item.get('personalizado'):
                custom_tag = (process_string({
                    'codigo': item.get('sku_externo', ''),
                    'descricao': item.get('descricao', '')
                }) or '').strip() or variacao

            item_formatted = {
                # O titulo do anuncio e como o produto se chama na origem; e o
                # que o operador reconhece ao conferir contra o marketplace.
                'descricao': (item.get('titulo_anuncio') or item.get('descricao') or ''),
                'codigo': item.get('sku_externo', ''),
                'quantidade': item.get('quantidade', 0),
                'valor': item.get('preco_unitario', 0),
                'variacao': variacao or None,
                'personalizado': item.get('personalizado', False),
                'personalizations': item_pers,
                'custom_tag': custom_tag,
            }
            itens_formatted.append(item_formatted)

        # 5b. Mensagem do comprador.
        #
        # O nome a ser gravado nao chega estruturado: na Shopee ele vem no
        # `message_to_seller` ("Nome na capa sera: Melissa Pereira"), e o legado
        # tinha uma ferramenta de IA so para extrair o nome dali para
        # `personalizacoes_pedido` — tabela que hoje tem uma linha no banco
        # inteiro. Enquanto essa extracao nao existir de novo, imprimir a
        # mensagem crua e melhor que imprimir nada: sem ela o operador teria que
        # abrir o painel da Shopee pedido a pedido para saber o que gravar.
        #
        # No Mercado Livre a personalizacao chega pela thread de mensagens do
        # pacote, que e outra chamada de API — nao esta no pedido e por isso nao
        # aparece aqui.
        mensagem_comprador = ''
        tem_personalizado = any(i.get('personalizado') for i in itens_formatted)
        tem_nome_estruturado = any(
            p.get('customization_name')
            for i in itens_formatted
            for p in (i.get('personalizations') or [])
        )
        if tem_personalizado and not tem_nome_estruturado:
            try:
                snap = (
                    supabase_db.table('pedido_snapshots')
                    .select('platform_fields')
                    .eq('pedido_id', pedido_id)
                    .limit(1)
                    .execute()
                )
                campos = ((snap.data or [{}])[0] or {}).get('platform_fields') or {}
                bruto = ((campos.get('shopee') or {}).get('raw') or {})
                mensagem_comprador = (bruto.get('message_to_seller') or bruto.get('note') or '').strip()
            except Exception:
                logger.warning('Falha ao ler a mensagem do comprador do pedido %s', pedido_id)

        # 6. Montar dados do contato
        contato = pedido.get('informacoes_cliente', {}) or {}
        if isinstance(contato, str):
            import json
            try:
                contato = json.loads(contato)
            except:
                contato = {}

        snapshot_customer = {}
        snapshot_logistics = {}
        snapshot_platform_fields = {}
        if plataforma_slug == 'mercadolivre':
            try:
                snapshot_result = (
                    supabase_db.table('pedido_snapshots')
                    .select('customer, logistics, platform_fields')
                    .eq('pedido_id', pedido_id)
                    .limit(1)
                    .execute()
                )
                snapshot = ((snapshot_result.data or [{}])[0] or {})
                snapshot_customer = snapshot.get('customer') or {}
                snapshot_logistics = snapshot.get('logistics') or {}
                snapshot_platform_fields = snapshot.get('platform_fields') or {}
            except Exception:
                logger.warning('Falha ao ler dados do destinatario MercadoLivre do pedido %s', pedido_id)

        # O campo legado `numeroDocumento` pode existir vazio em
        # `informacoes_cliente`; nesse caso `dict.get(..., fallback)` nao
        # aciona o fallback. Os pedidos novos tambem usam `document`/`documento`
        # no snapshot e `cliente_documento` na tabela principal.
        documento = _primeiro_valor_preenchido(
            pedido.get('cliente_documento'),
            contato.get('numeroDocumento'),
            contato.get('document'),
            contato.get('documento'),
        )
        if not documento:
            try:
                snapshot_result = (
                    supabase_db.table('pedido_snapshots')
                    .select('customer')
                    .eq('pedido_id', pedido_id)
                    .limit(1)
                    .execute()
                )
                snapshot_customer = ((snapshot_result.data or [{}])[0] or {}).get('customer') or {}
                snapshot_raw_customer = snapshot_customer.get('raw') or {}
                documento = _primeiro_valor_preenchido(
                    snapshot_customer.get('document'),
                    snapshot_customer.get('documento'),
                    snapshot_customer.get('numeroDocumento'),
                    snapshot_raw_customer.get('document'),
                    snapshot_raw_customer.get('documento'),
                    snapshot_raw_customer.get('numeroDocumento'),
                )
            except Exception:
                logger.warning('Falha ao ler documento do cliente do pedido %s', pedido_id)

        # 7. Nome de exibição da plataforma e numeroLoja
        plataforma_nome = MARKETPLACE_DISPLAY_NAMES.get(
            plataforma_slug, plataforma_slug.replace('_', ' ').title()
        ) if plataforma_slug else ''
        numero_loja = pedido.get('marketplace_order_id') or pedido.get('codigo_pedido_externo', '')

        # 8. Calcular total
        total_produtos = sum(i.get('valor', 0) * i.get('quantidade', 0) for i in itens_formatted)
        total_items = sum(i.get('quantidade', 0) for i in itens_formatted)
        has_custom_item = 1 if any(i.get('personalizado') or i.get('custom_tag') for i in itens_formatted) else 0

        # 9. Flag Flex
        is_flex = pedido.get('is_flex', False)
        servico_logistico = pedido.get('servico_logistico', '')

        nome_contato = pedido.get('cliente_nome', contato.get('nome', ''))
        if plataforma_slug == 'mercadolivre':
            nome_contato = _nome_destinatario_mercadolivre(
                logistics=snapshot_logistics,
                customer=snapshot_customer,
                platform_fields=snapshot_platform_fields,
                fallback=nome_contato,
            )

        return {
            'id': pedido.get('id'),
            'numero': str(erp_number),
            'numeroLoja': numero_loja,
            'plataforma_slug': plataforma_slug,
            'contato': {
                'nome': nome_contato,
                'numeroDocumento': documento,
                'endereco': contato.get('endereco', ''),
                'telefone': contato.get('telefone', pedido.get('cliente_telefone', '')),
                'email': contato.get('email', pedido.get('cliente_email', '')),
            },
            'itens': itens_formatted,
            'totalProdutos': total_produtos,
            'total_items': total_items,
            'hasCustomItem': has_custom_item,
            'mensagem_comprador': mensagem_comprador,
            'plataforma': plataforma_nome,
            'is_flex': is_flex,
            'servico_logistico': servico_logistico,
            'data_pedido': pedido.get('data_venda'),
        }

    except Exception as e:
        logger.error(f"Erro ao montar dados de impressão para pedido {pedido_id}: {e}", exc_info=True)
        return None
