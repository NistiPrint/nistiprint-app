"""Leitura, normalizacao e filtragem das exportacoes de marketplaces.

O modulo deliberadamente nao conhece Supabase. Ele transforma uma planilha em
linhas canonicas, o que deixa a etapa de conferencia testavel sem banco e evita
que cada rota volte a codificar nomes de colunas em pandas.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .amazon import MAPEAMENTO as AMAZON
from .mercadolivre import MAPEAMENTO as MERCADOLIVRE
from .shein import MAPEAMENTO as SHEIN
from .shopee import MAPEAMENTO as SHOPEE
from .tipos import (
    ColunaAusenteError,
    Filtro,
    FiltroResultado,
    Linha,
    MapeamentoPlanilha,
    MapeamentoPlanilhaError,
    aplicar_filtros,
)

MAPEAMENTOS: dict[str, MapeamentoPlanilha] = {
    item.module_id: item for item in (SHOPEE, MERCADOLIVRE, AMAZON, SHEIN)
}


def normalizar_module_id(value: Any) -> str | None:
    key = str(value or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    return {
        "shopee": "shopee",
        "shopeebr": "shopee",
        "shopeeflex": "shopee",
        "mercadolivre": "mercadolivre",
        "mercadolivrebr": "mercadolivre",
        "mercadolivreclassic": "mercadolivre",
        "ml": "mercadolivre",
        "amazon": "amazon",
        "amazonbr": "amazon",
        "shein": "shein",
        "sheinbr": "shein",
    }.get(key)


def detectar_mapeamento(columns: Iterable[Any]) -> MapeamentoPlanilha:
    nomes = {str(column).strip() for column in columns}
    candidatos = []
    for mapping in MAPEAMENTOS.values():
        assinatura = set(mapping.assinatura)
        score = len(assinatura & nomes)
        if score == len(assinatura):
            return mapping
        candidatos.append((score, mapping))
    score, mapping = max(candidatos, key=lambda value: value[0], default=(0, None))
    if not mapping or score == 0:
        esperado = "; ".join(", ".join(m.assinatura) for m in MAPEAMENTOS.values())
        raise MapeamentoPlanilhaError(
            f"Nao foi possivel detectar a plataforma pelo cabecalho. "
            f"Assinaturas esperadas: {esperado}. Colunas recebidas: {sorted(nomes)}"
        )
    raise MapeamentoPlanilhaError(
        f"Cabecalho ambiguo/incompleto para {mapping.module_id}: "
        f"faltam {sorted(set(mapping.assinatura) - nomes)}; "
        f"colunas recebidas: {sorted(nomes)}"
    )


def ler_dataframe(source: Any, mapping: MapeamentoPlanilha | None = None, module_id: str | None = None) -> tuple[pd.DataFrame, MapeamentoPlanilha]:
    """Le um caminho ou file-like e devolve o dataframe bruto e seu mapping."""
    mapping = mapping or MAPEAMENTOS.get(normalizar_module_id(module_id or ""))
    if mapping is not None:
        reader = pd.read_csv if mapping.leitura.get("formato") == "csv" else pd.read_excel
        frame = reader(source, **{k: v for k, v in mapping.leitura.items() if k != "formato"})
        return frame, mapping

    suffix = Path(getattr(source, "name", source)).suffix.lower()
    frame = pd.read_csv(source) if suffix == ".csv" else pd.read_excel(source)
    return frame, detectar_mapeamento(frame.columns)


def ler_linhas(source: Any, mapping: MapeamentoPlanilha | None = None, module_id: str | None = None) -> tuple[list[Linha], MapeamentoPlanilha]:
    frame, mapping = ler_dataframe(source, mapping, module_id)
    return mapping.normalizar(frame), mapping


def conferir_linhas(
    linhas: list[Linha],
    mapping: MapeamentoPlanilha,
    filtro: dict[str, Any] | None = None,
) -> FiltroResultado:
    return aplicar_filtros(linhas, mapping.filtros, filtro or {})


__all__ = [
    "AMAZON", "MERCADOLIVRE", "SHEIN", "SHOPEE", "MAPEAMENTOS",
    "ColunaAusenteError", "Filtro", "FiltroResultado", "Linha",
    "MapeamentoPlanilha", "MapeamentoPlanilhaError", "aplicar_filtros",
    "conferir_linhas", "detectar_mapeamento", "ler_dataframe", "ler_linhas",
    "normalizar_module_id",
]
