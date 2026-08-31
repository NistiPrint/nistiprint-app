import pandas as pd
import pytest

from services.mapeamento_planilha import MAPEAMENTOS, conferir_linhas
from services.mapeamento_planilha.tipos import ColunaAusenteError


def test_shopee_normaliza_id_float_e_filtro_comum():
    frame = pd.DataFrame([
        {
            "ID do pedido": "2000018149273500.0",
            "Opção de envio": "Normal",
            "Status do pedido": "Pago",
            "Data prevista de envio": "30/08/2026",
            "Número de referência SKU": "CAPA-01",
            "Nome do Produto": "Capa",
            "Nome da variação": "Azul",
            "Quantidade": 2,
            "Número de rastreamento": None,
        },
        {
            "ID do pedido": "2000018149273501",
            "Opção de envio": "Entrega Rápida",
            "Status do pedido": "Pago",
            "Data prevista de envio": "30/08/2026",
            "Número de referência SKU": "CAPA-02",
            "Nome do Produto": "Capa",
            "Nome da variação": "Vermelha",
            "Quantidade": 1,
            "Número de rastreamento": None,
        },
    ])
    mapping = MAPEAMENTOS["shopee"]
    linhas = mapping.normalizar(frame)
    resultado = conferir_linhas(linhas, mapping, {})
    assert resultado.refs == ["2000018149273500"]
    assert resultado.contagens["modalidade"] == 1


def test_coluna_obrigatoria_exibe_aliases_e_cabecalho():
    frame = pd.DataFrame([{"ID do pedido": "1", "Opção de envio": "Normal"}])
    with pytest.raises(ColunaAusenteError) as erro:
        MAPEAMENTOS["shopee"].normalizar(frame)
    assert "sku_externo" in str(erro.value)
    assert "Colunas recebidas" in str(erro.value)


def test_mercadolivre_avalia_pacote_em_conjunto():
    frame = pd.DataFrame([
        {"N.º de venda": "P1", "Estado": "Pacote de 2", "SKU": None, "Unidades": None, "Forma de entrega": "Normal"},
        {"N.º de venda": "P1", "Estado": "", "SKU": "SKU-1", "Unidades": 1, "Forma de entrega": "Normal"},
        {"N.º de venda": "P1", "Estado": "Etiqueta pronta para imprimir", "SKU": "SKU-2", "Unidades": 1, "Forma de entrega": "Normal"},
    ])
    mapping = MAPEAMENTOS["mercadolivre"]
    resultado = conferir_linhas(mapping.normalizar(frame), mapping, {})
    assert resultado.refs == ["P1"]
    assert {line.sku for line in resultado.linhas} == {"SKU-1", "SKU-2"}


def test_shein_usa_data_de_coleta_como_fallback():
    frame = pd.DataFrame([
        {
            "Número do pedido": "S1",
            "SKU do vendedor": "SKU-1",
            "Nome do produto": "Produto",
            "Status do pedido": "Pago",
            "Data e hora requeridas para coleta": "31/08/2026",
            "Código de rastreio": None,
        }
    ])
    mapping = MAPEAMENTOS["shein"]
    resultado = conferir_linhas(mapping.normalizar(frame), mapping, {"periodo": {"inicio": "2026-08-31", "fim": "2026-08-31"}})
    assert resultado.refs == ["S1"]
