from .tipos import Coluna, Filtro, MapeamentoPlanilha
from .transformadores import constante, data_tz_sp, limpar_id

MAPEAMENTO = MapeamentoPlanilha(
    "shein", ("Número do pedido", "SKU do vendedor", "Status do pedido"), "item", {"skiprows": 1},
    pedido={
        "marketplace_order_id": Coluna("Número do pedido", limpar_id, True),
        "status_original": Coluna("Status do pedido"),
        "data_limite_envio": Coluna(["Prazo final de impressão de etiqueta", "Prazo para imprimir etiqueta", "Data e hora requeridas para coleta"], data_tz_sp, True),
        "data_coleta": Coluna("Data e hora requeridas para coleta", data_tz_sp),
        "numero_rastreamento": Coluna("Código de rastreio"),
    },
    item={
        "sku_externo": Coluna("SKU do vendedor", limpar_id, True),
        "titulo_anuncio": Coluna("Nome do produto"),
        "quantidade": Coluna("Quantidade", constante, default=1),
    }, filtros=(
        Filtro("ja_rastreado", "Ocultar pedidos já com rastreio", "toggle", padrao=True, aplicar=lambda line, value: not value or not line.get("numero_rastreamento")),
        Filtro("periodo", "Prazo final de impressão de etiqueta", "periodo", campo="data_limite_envio"),
    ),
)
