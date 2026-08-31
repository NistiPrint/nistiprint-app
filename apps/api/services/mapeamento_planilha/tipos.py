from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

import pandas as pd

Transform = Callable[[Any], Any]
Predicate = Callable[["Linha", Any], bool]


class MapeamentoPlanilhaError(ValueError):
    pass


class ColunaAusenteError(MapeamentoPlanilhaError):
    def __init__(self, campo: str, aliases: list[str], recebidas: list[str]):
        self.campo = campo
        self.aliases = aliases
        self.recebidas = recebidas
        super().__init__(
            f"Coluna obrigatoria ausente para '{campo}'. "
            f"Aliases testados: {aliases}. Colunas recebidas: {recebidas}"
        )


@dataclass(frozen=True)
class Coluna:
    nomes: str | list[str]
    transform: Transform | None = None
    obrigatorio: bool = False
    default: Any = None

    @property
    def aliases(self) -> list[str]:
        return [self.nomes] if isinstance(self.nomes, str) else list(self.nomes)


@dataclass(frozen=True)
class Opcao:
    id: str
    rotulo: str
    ajuda: str | None = None
    aplicar: Predicate | None = None


@dataclass(frozen=True)
class Filtro:
    id: str
    rotulo: str
    tipo: Literal["opcao", "toggle", "periodo"]
    opcoes: tuple[Opcao, ...] = ()
    padrao: Any = None
    campo: str | None = None
    aplicar: Predicate | None = None

    def serialize(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rotulo": self.rotulo,
            "tipo": self.tipo,
            "padrao": self.padrao,
            "campo": self.campo,
            "opcoes": [
                {"id": option.id, "rotulo": option.rotulo, "ajuda": option.ajuda}
                for option in self.opcoes
            ],
        }


@dataclass
class Linha:
    pedido: dict[str, Any]
    item: dict[str, Any]
    raw: dict[str, Any]
    numero_linha: int
    pacote: str | None = None

    @property
    def ref(self) -> str:
        return str(self.pedido.get("marketplace_order_id") or "").strip()

    @property
    def sku(self) -> str:
        return str(self.item.get("sku_externo") or "").strip()

    def get(self, field_name: str, default: Any = None) -> Any:
        return self.pedido.get(field_name, self.item.get(field_name, default))

    def as_dict(self) -> dict[str, Any]:
        return {
            "numero_linha": self.numero_linha,
            "pedido": self.pedido,
            "item": self.item,
            "pacote": self.pacote,
            "bruto": self.raw,
        }


@dataclass(frozen=True)
class MapeamentoPlanilha:
    module_id: str
    assinatura: tuple[str, ...]
    nivel: Literal["item", "pedido"]
    leitura: dict[str, Any]
    pedido: dict[str, Coluna]
    item: dict[str, Coluna]
    filtros: tuple[Filtro, ...]

    def _resolve(self, frame: pd.DataFrame, field_name: str, column: Coluna) -> str | None:
        received = [str(item) for item in frame.columns]
        for alias in column.aliases:
            if alias in frame.columns:
                return alias
        if column.obrigatorio:
            raise ColunaAusenteError(field_name, column.aliases, received)
        return None

    @staticmethod
    def _clean(value: Any) -> Any:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        return value

    def normalizar(self, frame: pd.DataFrame) -> list[Linha]:
        resolvidos: dict[str, tuple[str | None, Coluna]] = {}
        for field_name, column in {**self.pedido, **self.item}.items():
            resolvidos[field_name] = (self._resolve(frame, field_name, column), column)

        raw_rows = frame.to_dict("records")
        pacote_por_linha: dict[int, str] = {}
        if self.module_id == "mercadolivre":
            pacote = None
            for index, raw in enumerate(raw_rows):
                state = str(self._clean(raw.get("Estado")) or "")
                if state.lower().startswith("pacote de"):
                    pacote = str(self._clean(raw.get("N.º de venda")) or "")
                elif pacote and self._clean(raw.get("Total (BRL)")) not in (None, ""):
                    pacote = None
                pacote_por_linha[index] = pacote

        pacotes_validos: set[str] = set()
        if self.module_id == "mercadolivre":
            estados_validos = {
                "pronta para emitir nf-e de venda",
                "emita a nota fiscal eletrônica (nf-e)",
                "aguardando disponibilidade de estoque",
                "anúncio sem dados fiscais",
                "etiqueta pronta para imprimir",
                "para enviar amanhã",
            }
            for index, raw in enumerate(raw_rows):
                pacote = pacote_por_linha.get(index)
                estado = str(self._clean(raw.get("Estado")) or "").strip().lower()
                if pacote and estado in estados_validos:
                    pacotes_validos.add(pacote)

        linhas: list[Linha] = []
        for index, raw in enumerate(raw_rows):
            pedido: dict[str, Any] = {}
            item: dict[str, Any] = {}
            for field_name, (column_name, column) in resolvidos.items():
                value = self._clean(raw.get(column_name)) if column_name else column.default
                if column.transform:
                    value = column.transform(value)
                (pedido if field_name in self.pedido else item)[field_name] = value

            if self.module_id == "mercadolivre":
                pedido["_pacote_valido"] = pacote_por_linha.get(index) in pacotes_validos
            if self.module_id == "shein" and not pedido.get("data_limite_envio"):
                pedido["data_limite_envio"] = pedido.get("data_coleta")

            # Amazon tem uma chave operacional por remessa, mas o id de origem
            # permanece o id do cliente conforme o contrato do plano.
            if self.module_id == "amazon" and pedido.get("shipment_id"):
                pedido["shipment_order_key"] = f"{pedido.get('shipment_id')}|{pedido.get('marketplace_order_id')}"
            linhas.append(Linha(pedido, item, {str(k): self._clean(v) for k, v in raw.items()}, index + 1, pacote_por_linha.get(index)))
        return linhas


@dataclass
class FiltroResultado:
    linhas: list[Linha]
    descartes: list[dict[str, Any]] = field(default_factory=list)
    contagens: dict[str, int] = field(default_factory=dict)

    @property
    def refs(self) -> list[str]:
        return list(dict.fromkeys(line.ref for line in self.linhas if line.ref and line.sku))

    def as_dict(self) -> dict[str, Any]:
        return {
            "linhas": [line.as_dict() for line in self.linhas],
            "refs": self.refs,
            "descartes": self.descartes,
            "contagens": self.contagens,
        }


def _valor_filtro(filtro: Filtro, valores: dict[str, Any]) -> Any:
    value = valores.get(filtro.id, filtro.padrao)
    return filtro.padrao if value is None and filtro.padrao is not None else value


def aplicar_filtros(linhas: list[Linha], filtros: tuple[Filtro, ...] | list[Filtro], valores: dict[str, Any] | None = None) -> FiltroResultado:
    valores = valores or {}
    atuais = list(linhas)
    descartes: list[dict[str, Any]] = []
    contagens = {"linhas": len(linhas)}
    for filtro in filtros:
        valor = _valor_filtro(filtro, valores)
        if filtro.tipo == "opcao":
            opcao = next((item for item in filtro.opcoes if item.id == valor), None)
            predicate = opcao.aplicar if opcao else None
        else:
            predicate = filtro.aplicar
        if not predicate or valor in (None, "", False) and filtro.tipo == "periodo":
            contagens[filtro.id] = len(atuais)
            continue

        antes = atuais
        if filtro.tipo == "periodo":
            periodo = valor if isinstance(valor, dict) else {}
            inicio = _parse_date(periodo.get("inicio") or periodo.get("start"))
            fim = _parse_date(periodo.get("fim") or periodo.get("end"))
            atuais = [line for line in atuais if _in_period(line.get(filtro.campo or ""), inicio, fim)]
        else:
            atuais = [line for line in atuais if predicate(line, valor)]
        removidas = [line for line in antes if line not in atuais]
        descartes.extend({"etapa": filtro.id, "numero_linha": line.numero_linha, "ref": line.ref, "motivo": filtro.id} for line in removidas)
        contagens[filtro.id] = len(atuais)
    contagens["refs"] = len({line.ref for line in atuais if line.ref and line.sku})
    return FiltroResultado(atuais, descartes, contagens)


def _parse_date(value: Any):
    if value in (None, ""):
        return None
    text = str(value)
    timestamp = pd.to_datetime(value, errors="coerce", dayfirst="/" in text)
    return None if pd.isna(timestamp) else timestamp.date()


def _in_period(value: Any, inicio, fim) -> bool:
    atual = _parse_date(value)
    if atual is None:
        return False if inicio or fim else True
    return (not inicio or atual >= inicio) and (not fim or atual <= fim)
