from .tipos import Coluna, Filtro, MapeamentoPlanilha, Opcao
from .transformadores import data_tz_sp, inteiro, limpar_id, moeda_br, situacao_shopee


def _contem(*termos):
    return lambda line, _value: any(str(line.get("metodo_envio_rotulo") or "").lower().find(t.lower()) >= 0 for t in termos)


def _nao_contem(*termos):
    return lambda line, _value: not any(str(line.get("metodo_envio_rotulo") or "").lower().find(t.lower()) >= 0 for t in termos)


FILTROS = (
    Filtro("modalidade", "Modalidade", "opcao", opcoes=(
        Opcao("comum", "Lote comum", "exclui Entrega Rápida, Full e Estoque", _nao_contem("Entrega Rápida", "Full", "Estoque")),
        Opcao("flex", "Entrega Rápida (Flex)", aplicar=_contem("Entrega Rápida")),
        Opcao("tudo", "Sem filtro de modalidade", aplicar=lambda _line, _value: True),
    ), padrao="comum"),
    Filtro("ja_rastreado", "Ocultar pedidos já com rastreio", "toggle", padrao=True, aplicar=lambda line, value: not value or not line.get("numero_rastreamento")),
    Filtro("periodo", "Data prevista de envio", "periodo", campo="data_limite_envio"),
)

MAPEAMENTO = MapeamentoPlanilha(
    "shopee", ("ID do pedido", "Opção de envio"), "item", {"skiprows": 0},
    pedido={
        "marketplace_order_id": Coluna("ID do pedido", limpar_id, True),
        "status_original": Coluna("Status do pedido"),
        "situacao_pedido_id": Coluna("Status do pedido", situacao_shopee),
        "data_limite_envio": Coluna("Data prevista de envio", data_tz_sp),
        "metodo_envio_rotulo": Coluna("Opção de envio"),
        "numero_rastreamento": Coluna("Número de rastreamento"),
        "buyer_username": Coluna("Nome de usuário (comprador)"),
        "message_to_seller": Coluna("Observação do comprador"),
        "cliente_nome": Coluna("Nome do destinatário"),
        "total_pedido": Coluna("Valor total do pedido", moeda_br),
    },
    item={
        "sku_externo": Coluna(["Número de referência SKU", "Nº de referência do SKU principal"], obrigatorio=True),
        "titulo_anuncio": Coluna("Nome do Produto"),
        "variacao_externa": Coluna("Nome da variação"),
        "quantidade": Coluna("Quantidade", inteiro, True, 1),
        "preco_unitario": Coluna("Preço acordado", moeda_br),
    }, filtros=FILTROS,
)
