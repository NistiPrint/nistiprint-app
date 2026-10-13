import logging
from typing import List, Dict, Any, Optional
from nistiprint_shared.database.supabase_db_service import supabase_db

logger = logging.getLogger("InventoryService")

class InventoryService:
    """
    Serviço para gestão de inventários físicos e auditoria de estoque.
    Implementa a Task 4.2 do PRD.
    """

    def __init__(self):
        self.sessao_table = supabase_db.table('sessoes_inventario')
        self.contagem_table = supabase_db.table('contagens_inventario')
        self.db = supabase_db

    def start_inventory(self, deposito_id: int, usuario_id: int, products_filter: List[int] = None, observacoes: str = "") -> Dict[str, Any]:
        """
        Inicia uma nova sessão de inventário, capturando o snapshot do saldo atual do sistema.
        """
        response = self.db.rpc('abrir_sessao_inventario', {
            'p_deposito_id': int(deposito_id),
            'p_usuario_id': int(usuario_id),
            'p_produtos': [int(product_id) for product_id in products_filter] if products_filter else None,
            'p_observacoes': observacoes or '',
        }).execute()
        if not isinstance(response.data, dict) or not response.data.get('sessao_id'):
            raise RuntimeError('O banco não confirmou a abertura da sessão de inventário.')
        return response.data

    def update_count(self, sessao_id: str, produto_id: int, quantidade_contada: float, justificativa: str = ""):
        """Registra a contagem física de um item."""
        response = self.db.rpc('registrar_contagem_inventario', {
            'p_sessao_id': str(sessao_id),
            'p_produto_id': int(produto_id),
            'p_quantidade': quantidade_contada,
            'p_justificativa': justificativa or '',
        }).execute()
        if response.data is False:
            raise RuntimeError('O banco não confirmou a contagem.')

    def finalize_inventory(self, sessao_id: str, usuario_id: int) -> Dict[str, Any]:
        """
        Finaliza o inventário e gera movimentações de ajuste para as divergências encontradas.
        """
        response = self.db.rpc('finalizar_sessao_inventario', {
            'p_sessao_id': str(sessao_id),
            'p_usuario_id': int(usuario_id),
        }).execute()
        if not isinstance(response.data, dict) or response.data.get('status') != 'success':
            raise RuntimeError('O banco não confirmou o fechamento do inventário.')
        return response.data

    def get_session_results(self, sessao_id: str) -> List[Dict[str, Any]]:
        """Retorna os itens da sessão com o cálculo de divergência para o frontend."""
        res = self.contagem_table.select("*, produtos(nome, sku)").eq('sessao_id', sessao_id).execute()
        
        results = []
        for row in res.data:
            item = dict(row)
            item['divergencia'] = (float(item['quantidade_contada']) if item['quantidade_contada'] is not None else 0) - float(item['quantidade_sistema'])
            results.append(item)
        return results

inventory_service = InventoryService()

