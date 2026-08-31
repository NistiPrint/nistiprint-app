from .tipos import Coluna, Filtro, MapeamentoPlanilha, Opcao
from .transformadores import data_tz_sp, forma_entrega_para_canonica, inteiro, limpar_id, moeda_br, situacao_mercadolivre

VALID_STATES = (
    "Pronta para emitir NF-e de venda", "Emita a Nota Fiscal eletrônica (NF-e)",
    "Aguardando disponibilidade de estoque", "Anúncio sem dados fiscais",
    "Etiqueta pronta para imprimir", "Para enviar amanhã",
)


def estado_valido(line, _value):
    # O estado de um pacote é decidido pelo pacote inteiro. Linhas sem pacote
    # continuam sendo avaliadas individualmente.
    if line.pacote:
        return bool(line.get("_pacote_valido"))
    return str(line.get("status_original") or "") in VALID_STATES


FILTROS = (
    Filtro("estado", "Estado válido do pedido", "opcao", opcoes=(Opcao("valido", "Estados que entram", aplicar=estado_valido), Opcao("todos", "Todos os estados", aplicar=lambda _line, _value: True)), padrao="valido"),
)

MAPEAMENTO = MapeamentoPlanilha(
    "mercadolivre", ("N.º de venda", "Estado", "SKU"), "item", {"skiprows": 5},
    pedido={
        "marketplace_order_id": Coluna("N.º de venda", limpar_id, True),
        "status_original": Coluna("Estado"),
        "situacao_pedido_id": Coluna("Estado", situacao_mercadolivre),
        "metodo_envio_rotulo": Coluna("Forma de entrega"),
        "modalidade_logistica": Coluna("Forma de entrega", forma_entrega_para_canonica),
        "cliente_nome": Coluna("Comprador"),
        "cliente_documento": Coluna("CPF"),
        "total_pedido": Coluna(["Total (BRL)", "Receita por produtos (BRL)"], moeda_br),
    },
    item={
        "sku_externo": Coluna("SKU", limpar_id, True),
        "titulo_anuncio": Coluna("Título do anúncio"),
        "variacao_externa": Coluna("Variação"),
        "quantidade": Coluna("Unidades", inteiro, True, 1),
        "preco_unitario": Coluna(["Preço unitário", "Preço"], moeda_br),
    }, filtros=FILTROS,
)
