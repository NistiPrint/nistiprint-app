from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from nistiprint_shared.database.supabase_db_service import supabase_db

class OrdemCompraService:
    """Serviço para gerenciamento de ordens de compra"""

    def __init__(self):
        self.table = supabase_db.table('ordens_compra')
        self.itens_table = supabase_db.table('ordem_compra_itens')

    def create_ordem_compra(self, oc_data: Dict[str, Any]) -> str:
        """Cria nova ordem de compra"""
        # Gera número único da OC se não fornecido
        if 'numero_oc' not in oc_data:
            oc_data['numero_oc'] = self._generate_numero_oc()

        doc_data = {
            **oc_data,
            'status': 'ABERTA',
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }

        # Calcula valor total se não fornecido
        if 'valor_total' not in doc_data:
            doc_data['valor_total'] = 0

        response = self.table.insert(doc_data).execute()
        if response.data:
            return str(response.data[0]['id'])
        return None

    def update_ordem_compra(self, oc_id: str, update_data: Dict[str, Any]) -> bool:
        """Atualiza ordem de compra"""
        try:
            update_data['updated_at'] = datetime.utcnow().isoformat()
            response = self.table.update(update_data).eq('id', oc_id).execute()
            return len(response.data) > 0
        except Exception:
            return False

    def get_ordem_compra(self, oc_id: str) -> Optional[Dict[str, Any]]:
        """Busca ordem de compra por ID"""
        response = self.table.select("*").eq('id', oc_id).execute()
        if not response.data:
            return None

        oc = {**dict(response.data[0]), 'id': str(response.data[0]['id'])}

        # Busca itens da OC
        itens_response = self.itens_table.select("*").eq('ordem_compra_id', oc_id).execute()
        oc['itens'] = [{**dict(item), 'id': str(item['id'])} for item in itens_response.data]

        return oc

    def list_ordens_compra(self, fornecedor_id: Optional[int] = None, status: Optional[str] = None,
                          limit: int = 50) -> List[Dict[str, Any]]:
        """Lista ordens de compra com filtros"""
        query = self.table.order('data_emissao', desc=True).limit(limit)

        if fornecedor_id:
            query = query.eq('fornecedor_id', fornecedor_id)

        if status:
            query = query.eq('status', status)

        response = query.execute()
        return [{**dict(doc), 'id': str(doc['id'])} for doc in response.data]

    def add_item_to_ordem_compra(self, oc_id: str, item_data: Dict[str, Any]) -> str:
        """Adiciona item à ordem de compra"""
        item_doc_data = {
            **item_data,
            'ordem_compra_id': oc_id,
            'quantidade_recebida': 0,
            'created_at': datetime.utcnow().isoformat()
        }

        response = self.itens_table.insert(item_doc_data).execute()
        self._update_oc_valor_total(oc_id)
        if response.data:
            return str(response.data[0]['id'])
        return None

    def receber_item(self, item_id: str, quantidade_recebida: float,
                    deposito_id: int, usuario_id: Optional[int] = None) -> bool:
        """Registra recebimento de item da OC"""
        try:
            # Busca item atual
            item_data = self._get_item_by_id(item_id)
            if not item_data:
                return False

            quantidade_anterior = item_data.get('quantidade_recebida', 0) or 0
            nova_quantidade = quantidade_anterior + quantidade_recebida

            # Atualiza item
            update_data = {
                'quantidade_recebida': nova_quantidade,
                'data_ultima_recebimento': datetime.utcnow().isoformat()
            }

            response = self.itens_table.update(update_data).eq('id', item_id).execute()
            if not response.data:
                return False

            # Lança entrada no estoque
            from nistiprint_shared.services.estoque_service import estoque_service
            estoque_service.registrar_entrada(
                produto_id=item_data['produto_id'],
                deposito_id=deposito_id,
                quantidade=quantidade_recebida,
                observacao=f'Recebimento OC - Item {item_id}',
                ordem_compra_id=item_data['ordem_compra_id'],
                usuario_id=usuario_id,
                user_context=None  # Não temos contexto de usuário aqui
            )

            # Atualiza custo do produto (custo médio)
            self._atualizar_custo_produto(item_data['produto_id'], item_data['custo_unitario'])

            # Verifica se OC está completa
            self._check_oc_completa(item_data['ordem_compra_id'])

            return True
        except Exception as e:
            print(f"Erro no recebimento: {str(e)}")
            return False

    def cancelar_ordem_compra(self, oc_id: str) -> bool:
        """Cancela ordem de compra"""
        try:
            response = self.table.update({
                'status': 'CANCELADA',
                'updated_at': datetime.utcnow().isoformat()
            }).eq('id', oc_id).execute()
            return len(response.data) > 0
        except Exception:
            return False

    def _get_item_by_id(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Busca item por ID"""
        response = self.itens_table.select("*").eq('id', item_id).execute()
        if response.data:
            return dict(response.data[0])
        return None

    def _generate_numero_oc(self) -> str:
        """Gera número único para OC"""
        timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        return f'OC{timestamp}'

    def _update_oc_valor_total(self, oc_id: str) -> None:
        """Recalcula valor total da OC de forma otimizada."""
        try:
            # Traz apenas as colunas necessárias para o cálculo
            response = supabase_db.execute_with_retry(
                self.itens_table.select("quantidade, custo_unitario").eq('ordem_compra_id', oc_id)
            )

            total = sum(float(item.get('quantidade', 0)) * float(item.get('custo_unitario', 0)) for item in response.data)
            supabase_db.execute_with_retry(self.table.update({'valor_total': total}).eq('id', oc_id))
        except Exception as e:
            print(f"Erro atualizando valor total: {str(e)}")

    def _check_oc_completa(self, oc_id: str) -> None:
        """Verifica se OC está completa de forma otimizada."""
        try:
            response = supabase_db.execute_with_retry(
                self.itens_table.select("quantidade, quantidade_recebida").eq('ordem_compra_id', oc_id)
            )

            itens = response.data
            if not itens: return

            todos_recebidos = all(float(i.get('quantidade_recebida', 0)) >= float(i.get('quantidade', 0)) for i in itens)
            algum_recebido = any(float(i.get('quantidade_recebida', 0)) > 0 for i in itens)

            if todos_recebidos:
                updates = {
                    'status': 'FINALIZADA',
                    'data_recebimento': datetime.utcnow().isoformat(),
                    'updated_at': datetime.utcnow().isoformat()
                }
            elif algum_recebido:
                updates = {
                    'status': 'RECEBIDA_PARCIAL',
                    'updated_at': datetime.utcnow().isoformat()
                }
            else:
                return

            supabase_db.execute_with_retry(self.table.update(updates).eq('id', oc_id))
        except Exception as e:
            print(f"Erro verificando OC completa: {str(e)}")

    def _atualizar_custo_produto(self, produto_id: str, novo_custo: float) -> None:
        """Atualiza custo médio do produto"""
        from nistiprint_shared.services.product_service import product_service

        try:
            # Busca custo atual do produto
            produto = product_service.get_by_id(produto_id)
            if not produto:
                return

            custo_atual = produto.get('custo', 0)

            # Busca saldo atual em estoque
            from nistiprint_shared.services.estoque_service import estoque_service
            from nistiprint_shared.services.app_config_service import app_config_service
            deposito_id = app_config_service.get_config('default_production_deposit_id')
            posicao_estoque = estoque_service.get_posicao_estoque(filtro_produtos=[produto_id])
            quantidade_total = sum(item['quantidade'] for item in posicao_estoque if item['produto_id'] == produto_id)

            if quantidade_total > 0:
                # Cálculo do custo médio ponderado
                # Novo custo = (quantidade_atual * custo_atual + quantidade_entrada * custo_entrada) / (quantidade_atual + quantidade_entrada)
                # Como estamos fazendo entrada incremental, simplificamos
                custo_medio = (custo_atual + novo_custo) / 2  # Simplificado - implementar cálculo completo depois

                product_service.update_custo(produto_id, custo_medio)
        except Exception as e:
            print(f"Erro atualizando custo produto: {str(e)}")

ordem_compra_service = OrdemCompraService()

