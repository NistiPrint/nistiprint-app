from .tipos import Coluna, Filtro, MapeamentoPlanilha
from .transformadores import data_tz_sp, inteiro, limpar_id, moeda_br

MAPEAMENTO = MapeamentoPlanilha(
    "amazon", ("ID do pedido do cliente", "ID da remessa", "SKU"), "item", {"formato": "csv"},
    pedido={
        "marketplace_order_id": Coluna("ID do pedido do cliente", limpar_id, True),
        "shipment_id": Coluna("ID da remessa", limpar_id, True),
        "status_original": Coluna("Status"),
        "data_limite_envio": Coluna("Data prevista para envio", data_tz_sp),
        "total_pedido": Coluna(["Total", "Total do pedido"], moeda_br),
    },
    item={
        "sku_externo": Coluna("SKU", limpar_id, True),
        "titulo_anuncio": Coluna("Título"),
        "quantidade": Coluna("Unidades", inteiro, True, 1),
        "preco_unitario": Coluna(["Preço unitário", "Preço"], moeda_br),
    }, filtros=(Filtro("periodo", "Data prevista de envio", "periodo", campo="data_limite_envio"),),
)
