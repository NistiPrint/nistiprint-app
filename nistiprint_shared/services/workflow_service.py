import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.estoque_service import estoque_service

logger = logging.getLogger("WorkflowService")


class WorkflowService:
    """
    Serviço de State Machine para gerenciar transições de status de pedidos
    e disparar ações automáticas (Side Effects).
    """

    def __init__(self):
        self.pedidos_table = supabase_db.table('pedidos')
        self.situacoes_table = supabase_db.table('situacoes_pedido')
        self.transicoes_table = supabase_db.table('transicoes_situacao')
        self.historico_table = supabase_db.table(
            'historico_status_pedido')

    def change_status(self, order_id: int, new_status_id: int, usuario_id: Optional[int] = None, observacao: str = "") -> Dict[str, Any]:
        """
        Altera o status de um pedido validando a transição e executando side-effects.
        """
        try:
            # 1. Obter status atual do pedido
            order = self.pedidos_table.select("id, situacao_pedido_id, codigo_pedido_externo").eq(
                'id', order_id).single().execute().data
            if not order:
                raise ValueError(f"Pedido {order_id} não encontrado.")

            old_status_id = order.get('situacao_pedido_id')

            # 2. Validar se a transição é permitida
            if old_status_id:
                transicao = self.transicoes_table.select("*").eq('situacao_origem_id', old_status_id).eq('situacao_destino_id', new_status_id).execute()

                if not transicao.data:
                    # Se não houver transição explícita, verificamos se o status é o mesmo (permitir re-save)
                    if old_status_id != new_status_id:
                        raise ValueError(
                            f"Transição de status não permitida para o pedido {order_id}.")

            # 3. Buscar metadados dos status (Flags de estoque)
            old_status_meta = self.situacoes_table.select(
                "*").eq('id', old_status_id).single().execute().data if old_status_id else {}
            new_status_meta = self.situacoes_table.select(
                "*").eq('id', new_status_id).single().execute().data

            if not new_status_meta:
                raise ValueError(f"Status destino {new_status_id} inválido.")

            # 4. Executar Side Effects de Estoque
            self._handle_stock_side_effects(
                order_id, old_status_meta, new_status_meta, usuario_id)

            # 5. Atualizar o pedido
            self.pedidos_table.update({
                'situacao_pedido_id': new_status_id,
                'status_unificado': new_status_meta['nome'].upper(),
                'updated_at': datetime.now(timezone.utc).isoformat()
            }).eq('id', order_id).execute()

            # 6. Registrar no Histórico
            self.historico_table.insert({
                'pedido_id': order_id,
                'situacao_anterior_id': old_status_id,
                'situacao_nova_id': new_status_id,
                'usuario_id': usuario_id,
                'observacao': observacao or f"Mudança para {new_status_meta['nome']}"
            }).execute()

            logger.info(
                f"Pedido {order_id} alterado para status {new_status_meta['nome']}")
            return {"status": "success", "new_status": new_status_meta['nome']}

        except Exception as e:
            logger.error(
                f"Erro ao mudar status do pedido {order_id}: {str(e)}")
            raise e

    def _handle_stock_side_effects(self, order_id: int, old_meta: Dict, new_meta: Dict, usuario_id: Optional[int]):
        """
        Gerencia reservas e baixas de estoque baseadas nas flags do status.
        """
        items = supabase_db.table('itens_pedido').select(
            "produto_id, quantidade").eq('pedido_id', order_id).execute().data
        if not items:
            return

        # Flag de Reserva
        old_reserva = old_meta.get('flag_reserva_estoque', False)
        new_reserva = new_meta.get('flag_reserva_estoque', False)

        # Flag de Baixa (Fatura/Saída)
        old_baixa = old_meta.get('flag_fatura', False)
        new_baixa = new_meta.get('flag_fatura', False)

        for item in items:
            p_id = item['produto_id']
            qtd = float(item['quantidade'])
            if not p_id:
                continue

            # Obter o depósito padrão para produção
            from nistiprint_shared.services.app_config_service import app_config_service
            deposito_id = app_config_service.get_config(
                'default_production_deposit_id')

            # Ação A: Entrou em status de reserva e não estava reservado
            if new_reserva and not old_reserva:
                try:
                    estoque_service.reservar_estoque(p_id, qtd, deposito_id)
                except Exception as e:
                    logger.warning(
                        f"Não foi possível reservar estoque para o produto {p_id}: {e}")

            # Ação B: Saiu de status de reserva e não baixou estoque (ex: Cancelou)
            if old_reserva and not new_reserva and not new_baixa:
                estoque_service.liberar_reserva(p_id, qtd, deposito_id)

            # Ação C: Entrou em status de baixa (ex: Enviado/Faturado)
            if new_baixa and not old_baixa:
                # Se estava reservado, confirma a saída liberando a reserva
                # Nesse caso específico, não temos contexto de usuário, então passamos None
                # O comportamento vai depender da lógica de permissão no serviço
                if old_reserva:
                    estoque_service.confirmar_saida_reservada(
                        p_id, qtd, deposito_id, motivo=f"Pedido {order_id} faturado.", usuario_id=usuario_id, user_context=None)
                else:
                    estoque_service.registrar_saida(
                        p_id, deposito_id, qtd, motivo=f"Venda direta pedido {order_id}", usuario_id=usuario_id, user_context=None)


workflow_service = WorkflowService()

