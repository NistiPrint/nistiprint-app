from typing import List, Dict, Any, Optional
from .estoque import demanda_alocacao_estoque_service

class DemandaAlocacaoWaterfallService:
    """
    Wrapper de compatibilidade para a lógica waterfall de estoque.
    Delega a execução real para o DemandaAlocacaoEstoqueService em estoque.py.
    """
    def __init__(self):
        self._service = demanda_alocacao_estoque_service

    def processar_insumos_por_bom_recursivo(self, *args, **kwargs):
        return self._service.processar_insumos_por_bom_recursivo(*args, **kwargs)

    def _registrar_alocacao_estoque(self, *args, **kwargs):
        return self._service._registrar_alocacao_estoque(*args, **kwargs)

    def _calcular_saldo_a_processar(self, *args, **kwargs):
        return self._service._calcular_saldo_a_processar(*args, **kwargs)

    def get_item_by_id(self, *args, **kwargs):
        return self._service.get_item_by_id(*args, **kwargs)

demanda_alocacao_waterfall_service = DemandaAlocacaoWaterfallService()
