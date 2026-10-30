"""Pure planning helpers for batch bill-of-materials changes.

Persistence and database-side concurrency checks must be performed separately.
"""
from decimal import Decimal, InvalidOperation


def planejar_composicao(linhas, operacoes):
    """Apply explicit changes to a complete effective BOM without mutating it."""
    resultado = {}
    for linha in linhas:
        componente = int(linha['componente_id'])
        if componente in resultado:
            raise ValueError(f'BOM_DUPLICATE_COMPONENT:{componente}')
        resultado[componente] = dict(linha)

    vistos = set()
    for operacao in operacoes:
        componente = int(operacao['componente_id'])
        if componente in vistos:
            raise ValueError(f'BOM_DUPLICATE_OPERATION:{componente}')
        vistos.add(componente)
        acao = operacao.get('acao')
        if acao == 'remover':
            resultado.pop(componente, None)
        elif acao == 'definir':
            try:
                quantidade = Decimal(str(operacao['quantidade']))
            except (InvalidOperation, KeyError):
                raise ValueError(f'BOM_INVALID_QUANTITY:{componente}') from None
            if not quantidade.is_finite() or quantidade <= 0 or quantidade.as_tuple().exponent < -6 or quantidade >= Decimal('1000000000'):
                raise ValueError(f'BOM_INVALID_QUANTITY:{componente}')
            atual = resultado.get(componente, {'componente_id': componente})
            resultado[componente] = {**atual, 'quantidade_necessaria': str(quantidade)}
        else:
            raise ValueError(f'BOM_INVALID_ACTION:{componente}')
    return list(resultado.values())


def validar_grafo(grafo):
    """Validate the complete proposed graph, including all changes in the batch."""
    ativos = set()
    completos = set()
    caminho = []

    def visitar(produto):
        if produto in ativos:
            inicio = caminho.index(produto)
            ciclo = caminho[inicio:] + [produto]
            raise ValueError('BOM_CYCLE: ' + ' -> '.join(map(str, ciclo)))
        if produto in completos:
            return
        ativos.add(produto)
        caminho.append(produto)
        for componente in grafo.get(produto, []):
            visitar(int(componente['componente_id']))
        caminho.pop()
        ativos.remove(produto)
        completos.add(produto)

    for produto in grafo:
        visitar(int(produto))
