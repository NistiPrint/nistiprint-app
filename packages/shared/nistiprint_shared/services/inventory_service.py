import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.estoque_service import estoque_service

logger = logging.getLogger("InventoryService")

class InventoryService:
    """
    Serviço para gestão de inventários físicos e auditoria de estoque.
    Implementa a Task 4.2 do PRD.
    """

    def __init__(self):
        self.sessao_table = supabase_db.table('sessoes_inventario')
        self.contagem_table = supabase_db.table('contagens_inventario')

    def start_inventory(self, deposito_id: int, usuario_id: int, products_filter: List[int] = None, observacoes: str = "") -> Dict[str, Any]:
        """
        Inicia uma nova sessão de inventário, capturando o snapshot do saldo atual do sistema.
        """
        # 1. Criar a Sessão
        sessao_res = self.sessao_table.insert({
            'deposito_id': deposito_id,
            'usuario_id': usuario_id,
            'observacoes': observacoes,
            'status': 'ABERTA'
        }).execute()
        
        if not sessao_res.data:
            raise Exception("Falha ao criar sessão de inventário.")
        
        sessao_id = sessao_res.data[0]['id']

        # 2. Capturar Snapshot de Saldos
        # Se products_filter for None, pegamos todos os produtos que possuem saldo no depósito
        query = supabase_db.table('estoque_atual').select("produto_id, saldo_atual").eq('deposito_id', deposito_id)
        if products_filter:
            query = query.in_('produto_id', products_filter)
        
        saldos = query.execute().data
        
        # 3. Criar registros de contagem inicial
        contagens = []
        for s in saldos:
            contagens.append({
                'sessao_id': sessao_id,
                'produto_id': s['produto_id'],
                'quantidade_sistema': s['saldo_atual'],
                'quantidade_contada': None # Aguardando contagem física
            })
        
        if contagens:
            self.contagem_table.insert(contagens).execute()

        return {"sessao_id": sessao_id, "items_count": len(contagens)}

    def update_count(self, sessao_id: str, produto_id: int, quantidade_contada: float, justificativa: str = ""):
        """Registra a contagem física de um item."""
        self.contagem_table.update({
            'quantidade_contada': quantidade_contada,
            'justificativa': justificativa,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }).eq('sessao_id', sessao_id).eq('produto_id', produto_id).execute()

    def finalize_inventory(self, sessao_id: str, usuario_id: int) -> Dict[str, Any]:
        """
        Finaliza o inventário e gera movimentações de ajuste para as divergências encontradas.
        """
        # 1. Obter dados da sessão e contagens
        sessao = self.sessao_table.select("*").eq('id', sessao_id).single().execute().data
        if not sessao or sessao['status'] != 'ABERTA':
            raise ValueError("Sessão não encontrada ou já finalizada.")

        contagens = self.contagem_table.select("*").eq('sessao_id', sessao_id).execute().data
        
        ajustes_realizados = 0
        for item in contagens:
            if item['quantidade_contada'] is None:
                continue # Pula itens não contados (ou assume sistema se preferir)
            
            divergencia = float(item['quantidade_contada']) - float(item['quantidade_sistema'])
            
            if divergencia != 0:
                # Realizar ajuste de estoque
                estoque_service.registrar_balanco(
                    produto_id=item['produto_id'],
                    deposito_id=sessao['deposito_id'],
                    quantidade_ajuste=float(item['quantidade_contada']), # No registrar_balanco, enviamos o saldo final desejado
                    motivo=f"Ajuste via Inventário {sessao_id}. Justificativa: {item.get('justificativa', 'N/A')}",
                    usuario_id=usuario_id,
                    user_context=None  # Não temos contexto de usuário aqui
                )
                ajustes_realizados += 1

        # 2. Fechar Sessão
        self.sessao_table.update({
            'status': 'FINALIZADA',
            'data_fim': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }).eq('id', sessao_id).execute()

        return {"status": "success", "ajustes_realizados": ajustes_realizados}

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

